"""Compact model verification for the conservative formal pipeline."""

from __future__ import annotations

from .agent_config import AgentConfig
from .agent_prompts import VERIFIER_PROMPT
from .agent_types import ModelCallResult, Verification
from .budget import BudgetExceeded
from .context import SolveContext
from .model_calls import call_model_result
from .response_processing import parse_verdict, review_excerpt
from .truncation import mark_truncation


class CandidateEvaluator:
    """Attach one bounded model verdict to each eligible candidate."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def verify(
        self,
        context: SolveContext,
        candidate: str,
        candidate_id: int,
    ) -> tuple[float, list[dict], list[Verification]]:
        votes: list[bool] = []
        trace: list[dict] = []
        verifications: list[Verification] = []
        review_text = review_excerpt(candidate)
        for vote_id in range(self.config.formal_verifier_calls_per_candidate):
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
                recovery=True,
                temperature=self.config.verifier_temperature,
                max_tokens=self.config.verifier_max_tokens,
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
