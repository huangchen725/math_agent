"""Competition-facing reasoning agent lifecycle.

The fixed solving stages live in focused pipeline modules. This module owns
input validation, per-call context creation, top-level error containment, and
private compatibility delegates retained for the existing offline test suite.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from .agent_config import AgentConfig
from .agent_prompts import (
    CRITIC_PROMPT,
    POLICY_NO_TOOL_PROMPT,
    POLICY_PROMPT,
    REFLECTION_PROMPT,
    VERIFIER_PROMPT,
)
from .agent_types import Candidate, ModelCallResult, Verification
from .answer_equivalence import normalize_answer, numeric_value
from .budget import BudgetExceeded, ExecutionBudget
from .candidate_generation import (
    is_proof_like,
    model_result_trace,
    reasoning_instruction,
    reasoning_target_tokens,
)
from .candidate_selection import record_final_source, select_candidate
from .context import SolveContext
from .domain_router import DOMAIN_KEYWORDS, detect_domain
from .llm_client import InternChatClient
from .model_calls import call_model_result, call_model_text
from .model_gateway import ModelGateway
from .response_processing import (
    build_response,
    extract_answer,
    extract_first_line_answer,
    parse_verdict,
    review_excerpt,
    validate_response,
)
from .solver import SolveOrchestrator
from .task_router import TaskAnalysis
from .truncation import contain_pending_truncations, mark_truncation


class ReasoningAgent:
    """Validate inputs and run one isolated, explicitly-scoped solve."""

    _DOMAIN_KEYWORDS = DOMAIN_KEYWORDS

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client
        self._orchestrator = SolveOrchestrator(self.config)

    def solve(self, problem: str, metadata: Dict) -> Dict:
        """Preserve the competition contract and contain all pipeline failures."""
        input_error = self._validate_input(problem, metadata)
        if input_error is not None:
            return input_error

        trace: List[Dict] = []
        budget = ExecutionBudget(
            max_model_requests=self.config.max_model_requests,
            max_recovery_requests=self.config.max_recovery_requests,
            max_total_tokens=self.config.max_total_tokens,
            max_tool_calls=self.config.max_tool_calls,
            timeout_seconds=self.config.problem_timeout_seconds,
        )
        context = SolveContext(
            problem=problem,
            metadata=dict(metadata),
            trace=trace,
            budget=budget,
            gateway=ModelGateway(self.client, budget),
        )
        try:
            result = self._solve_impl(context)
        except BudgetExceeded as exc:
            trace.append({"step": "budget_exceeded", "content": str(exc)[:300]})
            result = {"final_response": "未解出", "trace": trace}
        except Exception as exc:
            trace.append({
                "step": "global_error",
                "content": f"{type(exc).__name__}: {str(exc)[:300]}",
            })
            try:
                fallback = self._quick_fallback(context)
                final_response = build_response("", fallback) if fallback else "未解出"
                result = {"final_response": final_response, "trace": trace}
            except BudgetExceeded as budget_error:
                trace.append({
                    "step": "budget_exceeded",
                    "content": str(budget_error)[:300],
                })
                result = {"final_response": "未解出", "trace": trace}

        contain_pending_truncations(budget)
        trace.append({"step": "budget_summary", "content": budget.snapshot()})
        return result

    def _validate_input(self, problem: object, metadata: object) -> dict | None:
        if not isinstance(problem, str) or not problem.strip():
            return {
                "final_response": "未解出",
                "trace": [{"step": "input_error", "content": "problem 必须是非空字符串"}],
            }
        if len(problem) > self.config.max_problem_chars:
            return {
                "final_response": "未解出",
                "trace": [{
                    "step": "input_error",
                    "content": f"problem 超过 {self.config.max_problem_chars} 字符限制",
                }],
            }
        if not isinstance(metadata, dict):
            return {
                "final_response": "未解出",
                "trace": [{"step": "input_error", "content": "metadata 必须是字典"}],
            }
        try:
            serialized_metadata = json.dumps(
                metadata,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError):
            return {
                "final_response": "未解出",
                "trace": [{"step": "input_error", "content": "metadata 必须可序列化为 JSON"}],
            }
        if len(serialized_metadata) > self.config.max_metadata_chars:
            return {
                "final_response": "未解出",
                "trace": [{
                    "step": "input_error",
                    "content": f"metadata 超过 {self.config.max_metadata_chars} 字符限制",
                }],
            }
        return None

    def _solve_impl(self, context: SolveContext) -> Dict:
        return self._orchestrator.solve(context)

    # Compatibility delegates. Runtime stage implementations remain in the
    # focused modules above and do not read state from the Agent instance.
    def _chat_result(
        self,
        context: SolveContext,
        system_prompt: str,
        user_content: str,
        *,
        stage: str,
        candidate_id: int | None = None,
        recovery: bool = False,
        **kwargs: Any,
    ) -> ModelCallResult:
        return call_model_result(
            context,
            system_prompt,
            user_content,
            stage=stage,
            candidate_id=candidate_id,
            recovery=recovery,
            **kwargs,
        )

    def _chat(
        self,
        context: SolveContext,
        system_prompt: str,
        user_content: str,
        **kwargs: Any,
    ) -> str:
        return call_model_text(context, system_prompt, user_content, **kwargs)

    def _generate_candidates(
        self,
        context: SolveContext,
        domain_prompt: str,
        target_tokens: int,
    ) -> tuple[list[ModelCallResult], list[dict], list[str]]:
        batch = self._orchestrator.generator.generate(context, domain_prompt, target_tokens)
        return batch.candidates, batch.trace, batch.emergency_hints

    def _solve_tools_result(
        self,
        context: SolveContext,
        candidate_id: int,
        domain_prompt: str,
        target_tokens: int,
    ) -> tuple[ModelCallResult, list[dict]]:
        return self._orchestrator.generator.solve_tools_result(
            context,
            candidate_id,
            domain_prompt,
            target_tokens,
        )

    def _solve_plain_result(
        self,
        context: SolveContext,
        domain_prompt: str,
        target_tokens: int,
        *,
        candidate_id: int | None = None,
    ) -> ModelCallResult:
        return self._orchestrator.generator.solve_plain_result(
            context,
            domain_prompt,
            target_tokens,
            candidate_id=candidate_id,
        )

    def _solve_plain(self, context: SolveContext, domain_prompt: str) -> str:
        return self._solve_plain_result(
            context,
            domain_prompt,
            reasoning_target_tokens(context.problem, self.config),
        ).text

    def _verify(
        self,
        context: SolveContext,
        candidate: str,
        candidate_id: int,
        *,
        task_analysis: TaskAnalysis | None = None,
    ) -> tuple[float, list[dict], list[Verification]]:
        return self._orchestrator.evaluator.verify(
            context,
            candidate,
            candidate_id,
            task_analysis=task_analysis,
        )

    def _critic(self, context: SolveContext, candidate: str) -> str:
        return self._orchestrator.evaluator.critic(context, candidate)

    def _reflect_result(
        self,
        context: SolveContext,
        previous: str,
        feedback: str,
        *,
        candidate_id: int,
    ) -> ModelCallResult:
        return self._orchestrator.evaluator.reflect_result(
            context,
            previous,
            feedback,
            candidate_id=candidate_id,
        )

    def _reflect(self, context: SolveContext, previous: str, feedback: str) -> str:
        return self._reflect_result(
            context,
            previous,
            feedback,
            candidate_id=-1,
        ).text

    def _prepare_candidate(
        self,
        context: SolveContext,
        result: ModelCallResult,
        candidate_id: int,
    ) -> tuple[ModelCallResult | None, str]:
        return self._orchestrator.generator.prepare_candidate(context, result, candidate_id)

    def _retry_truncated_verifier(
        self,
        context: SolveContext,
        review_text: str,
        candidate_id: int,
        original: ModelCallResult,
    ) -> ModelCallResult:
        return self._orchestrator.evaluator.retry_truncated_verifier(
            context,
            review_text,
            candidate_id,
            original,
        )

    def _emergency_answer(self, context: SolveContext, answer_hints: list[str]) -> str:
        return self._orchestrator.generator.emergency_answer(context, answer_hints)

    def _quick_fallback(self, context: SolveContext) -> str:
        return self._orchestrator.generator.quick_fallback(context)

    def _aggregate(
        self,
        scored: list[Candidate],
        trace: list[dict],
        *,
        budget: ExecutionBudget | None = None,
    ) -> tuple[str, str]:
        return select_candidate(scored, trace, budget=budget)

    @staticmethod
    def _record_final_source(
        candidate: Candidate,
        trace: list[dict],
        budget: ExecutionBudget | None = None,
    ) -> None:
        record_final_source(candidate, trace, budget)

    @staticmethod
    def _build_response(content: str, answer: str) -> str:
        return build_response(content, answer)

    @staticmethod
    def _validated_response(response: str, answer: str) -> str:
        return validate_response(response, answer)

    @staticmethod
    def _candidate_trace(result: ModelCallResult, step: str) -> list[dict]:
        return model_result_trace(result, step)

    @staticmethod
    def _is_proof_like(problem: str) -> bool:
        return is_proof_like(problem)

    def _reasoning_target_tokens(self, problem: str) -> int:
        return reasoning_target_tokens(problem, self.config)

    @staticmethod
    def _reasoning_instruction(target_tokens: int) -> str:
        return reasoning_instruction(target_tokens)

    @staticmethod
    def _extract_first_line_answer(text: str) -> str:
        return extract_first_line_answer(text)

    @staticmethod
    def _parse_verdict(verdict: str) -> bool | None:
        return parse_verdict(verdict)

    @staticmethod
    def _mark_truncation(
        context: SolveContext,
        result: ModelCallResult,
        status: str,
        original_answer_present: bool,
    ) -> None:
        mark_truncation(context, result, status, original_answer_present)

    @staticmethod
    def _contain_pending_truncations(budget: ExecutionBudget) -> None:
        contain_pending_truncations(budget)

    @staticmethod
    def _detect_domain(problem: str) -> str:
        return detect_domain(problem)

    @staticmethod
    def _review_excerpt(text: str, limit: int = 3000) -> str:
        return review_excerpt(text, limit)

    @staticmethod
    def _extract_answer(text: str) -> str:
        return extract_answer(text)

    @staticmethod
    def _normalize(answer: str) -> str:
        return normalize_answer(answer)

    @staticmethod
    def _numeric(value: str) -> float | None:
        number = numeric_value(value)
        return float(number) if number is not None else None

    @staticmethod
    def _is_correct(verdict: str) -> bool:
        return parse_verdict(verdict) is True


__all__ = [
    "AgentConfig",
    "CRITIC_PROMPT",
    "POLICY_NO_TOOL_PROMPT",
    "POLICY_PROMPT",
    "REFLECTION_PROMPT",
    "ReasoningAgent",
    "VERIFIER_PROMPT",
]
