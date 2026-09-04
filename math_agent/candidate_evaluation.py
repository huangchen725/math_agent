"""Deterministic/model verification, criticism, and reflection."""

from __future__ import annotations

from .agent_config import AgentConfig
from .agent_prompts import CRITIC_PROMPT, POLICY_PROMPT, REFLECTION_PROMPT, VERIFIER_PROMPT
from .agent_types import ModelCallResult, Verification
from .budget import BudgetExceeded
from .candidate_generation import (
    model_result_trace,
    reasoning_instruction,
    reasoning_target_tokens,
)
from .context import SolveContext
from .deterministic_verifier import verify_task_plan
from .model_calls import call_model_result
from .response_processing import (
    extract_answer,
    extract_first_line_answer,
    parse_verdict,
    review_excerpt,
)
from .task_router import TaskAnalysis, analyze_task
from .truncation import mark_truncation


class CandidateEvaluator:
    """Attach bounded verification evidence and optionally produce a reflection."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def verify(
        self,
        context: SolveContext,
        candidate: str,
        candidate_id: int,
        *,
        task_analysis: TaskAnalysis | None = None,
    ) -> tuple[float, list[dict], list[Verification]]:
        votes: list[bool] = []
        trace: list[dict] = []
        verifications: list[Verification] = []
        task_analysis = task_analysis or analyze_task(context.problem)
        candidate_answer = extract_answer(candidate)
        plan = task_analysis.verification_plan

        if self.config.enable_deterministic_verification and plan and candidate_answer:
            try:
                context.budget.consume_tool_call()
                evidence = verify_task_plan(
                    plan,
                    candidate_answer,
                    timeout_seconds=self.config.tool_timeout_seconds,
                )
            except BudgetExceeded as exc:
                evidence = Verification(
                    source=f"deterministic:{plan.kind}",
                    status="unknown",
                    confidence=0.0,
                    detail=f"budget unavailable: {str(exc)[:160]}",
                )
            verifications.append(evidence)
            trace.append({
                "step": f"deterministic_verify_{candidate_id}",
                "content": {
                    "source": evidence.source,
                    "status": evidence.status,
                    "detail": evidence.detail[:200],
                },
            })

        review_text = review_excerpt(candidate)
        for vote_id in range(self.config.verifier_voting_times):
            try:
                result = call_model_result(
                    context,
                    VERIFIER_PROMPT,
                    f"题目：\n{context.problem}\n\n候选解答：\n{review_text}\n\n"
                    "判断是否正确。只输出：VERDICT: A 或 VERDICT: B",
                    stage="verifier",
                    candidate_id=candidate_id,
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens,
                    thinking_mode=self.config.verifier_thinking_mode,
                )
                if result.truncated:
                    result = self.retry_truncated_verifier(
                        context,
                        review_text,
                        candidate_id,
                        result,
                    )
                verdict = result.text
                parsed = parse_verdict(verdict) if not result.truncated else None
                if parsed is not None:
                    votes.append(parsed)
                verifications.append(Verification(
                    source="model",
                    status=("pass" if parsed else "fail") if parsed is not None else "unknown",
                    confidence=1.0 if parsed is True else (0.0 if parsed is False else 0.5),
                    detail=(
                        verdict[:200]
                        if not result.truncated
                        else "truncated verifier response quarantined"
                    ),
                ))
                trace.append({
                    "step": f"verify_{candidate_id}_{vote_id}",
                    "content": verdict[:200] if not result.truncated else "截断结果已隔离",
                })
            except BudgetExceeded:
                raise
            except Exception as exc:
                verifications.append(Verification(
                    source="model",
                    status="unknown",
                    confidence=0.0,
                    detail=f"{type(exc).__name__}: {str(exc)[:160]}",
                ))
                trace.append({
                    "step": f"verify_err_{candidate_id}_{vote_id}",
                    "content": str(exc)[:200],
                })
        confidence = sum(votes) / len(votes) if votes else 0.5
        return confidence, trace, verifications

    def critic(self, context: SolveContext, candidate: str) -> str:
        try:
            result = call_model_result(
                context,
                CRITIC_PROMPT,
                f"题目：\n{context.problem}\n\n候选解答：\n{review_excerpt(candidate)}\n\n"
                "请找出错误或改进点。",
                stage="critic",
                temperature=self.config.critic_temperature,
                max_tokens=self.config.critic_max_tokens,
                thinking_mode=self.config.critic_thinking_mode,
            )
            if result.truncated:
                mark_truncation(
                    context,
                    result,
                    "quarantined",
                    bool(extract_first_line_answer(result.text)),
                )
                context.trace.append({
                    "step": "critic_truncated",
                    "content": {"action": "discard"},
                })
                return ""
            context.trace.append({"step": "critic", "content": result.text[:500]})
            return result.text
        except BudgetExceeded:
            raise
        except Exception as exc:
            context.trace.append({"step": "critic_error", "content": str(exc)[:200]})
            return ""

    def reflect_result(
        self,
        context: SolveContext,
        previous: str,
        feedback: str,
        *,
        candidate_id: int,
    ) -> ModelCallResult:
        try:
            prompt = REFLECTION_PROMPT.format(
                problem=context.problem,
                prev_answer=review_excerpt(previous, limit=2000),
                feedback=feedback[:500],
            )
            prompt += "\n" + reasoning_instruction(
                reasoning_target_tokens(context.problem, self.config)
            )
            result = call_model_result(
                context,
                POLICY_PROMPT,
                prompt,
                stage="reflection",
                candidate_id=candidate_id,
                temperature=self.config.reflection_temperature,
                max_tokens=self.config.max_tokens,
                thinking_mode=self.config.policy_thinking_mode,
            )
            context.trace.extend(model_result_trace(result, "reflection"))
            return result
        except BudgetExceeded:
            raise
        except Exception as exc:
            context.trace.append({"step": "reflect_error", "content": str(exc)[:200]})
            return ModelCallResult(
                text="",
                stage="reflection",
                finish_reason=f"error:{type(exc).__name__}",
                candidate_id=candidate_id,
            )

    def retry_truncated_verifier(
        self,
        context: SolveContext,
        review_text: str,
        candidate_id: int,
        original: ModelCallResult,
    ) -> ModelCallResult:
        """Retry a truncated verifier once; unresolved output remains unknown."""
        try:
            retried = call_model_result(
                context,
                VERIFIER_PROMPT,
                f"题目：\n{context.problem}\n\n候选解答：\n{review_text}\n\n"
                "上次验证输出被截断。只输出一行 VERDICT: A 或 VERDICT: B。",
                stage="verifier",
                candidate_id=candidate_id,
                temperature=self.config.verifier_temperature,
                max_tokens=self.config.verifier_max_tokens,
                thinking_mode=self.config.verifier_thinking_mode,
            )
        except BudgetExceeded:
            mark_truncation(context, original, "quarantined", False)
            context.trace.append({
                "step": "verifier_recovery",
                "content": {"candidate_id": candidate_id, "result": "budget_exhausted"},
            })
            return original

        parsed = None if retried.truncated else parse_verdict(retried.text)
        if parsed is not None:
            mark_truncation(context, original, "recovered", False)
            status = "success"
        else:
            mark_truncation(context, original, "recovery_failed", False)
            status = "truncated_again" if retried.truncated else "unknown"
        if retried.truncated:
            mark_truncation(context, retried, "quarantined", False)
        context.trace.append({
            "step": "verifier_recovery",
            "content": {"candidate_id": candidate_id, "result": status},
        })
        return retried
