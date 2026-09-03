"""High-level per-problem orchestration built from focused pipeline components."""

from __future__ import annotations

from agent_config import AgentConfig
from agent_types import Candidate, ModelCallResult
from answer_equivalence import build_answer
from candidate_evaluation import CandidateEvaluator
from candidate_generation import CandidateGenerator, is_proof_like, reasoning_target_tokens
from candidate_selection import select_candidate
from context import SolveContext
from domain_prompts import get_domain_prompt
from domain_router import detect_domain
from response_processing import build_response, extract_answer


class SolveOrchestrator:
    """Run the single conservative generation, verification, and selection path."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.generator = CandidateGenerator(config)
        self.evaluator = CandidateEvaluator(config)

    def solve(self, context: SolveContext) -> dict:
        domain_name = detect_domain(context.problem)
        domain_prompt = get_domain_prompt(domain_name)
        if domain_name:
            context.trace.append({
                "step": "domain_detect",
                "content": f"关键词识别: {domain_name}",
            })

        target_tokens = reasoning_target_tokens(context.problem, self.config)
        context.trace.append({
            "step": "reasoning_budget",
            "content": {
                "kind": "proof" if is_proof_like(context.problem) else "calculation",
                "target_tokens": target_tokens,
                "api_max_tokens": self.config.max_tokens,
            },
        })
        batch = self.generator.generate(context, domain_prompt, target_tokens)
        context.trace.extend(batch.trace)

        if not batch.candidates:
            context.trace.append({
                "step": "emergency_required",
                "content": {"reason": "no_eligible_candidate"},
            })
            return self._emergency_or_unsolved(
                context,
                batch.emergency_hints,
                allow_emergency=self.config.enable_fallback,
            )

        scored = [
            self._score_result(
                context,
                result,
                fallback_candidate_id=index,
            )
            for index, result in enumerate(batch.candidates)
        ]

        final_answer, best_content = select_candidate(
            scored,
            context.trace,
            budget=context.budget,
        )
        if not final_answer:
            return self._emergency_or_unsolved(
                context,
                batch.emergency_hints,
                allow_emergency=True,
            )
        final_response = build_response(best_content, final_answer)
        return {
            "final_response": final_response or final_answer or "未解出",
            "trace": context.trace,
        }

    def _score_result(
        self,
        context: SolveContext,
        result: ModelCallResult,
        *,
        fallback_candidate_id: int = 0,
        strategy: str | None = None,
        extra_metadata: dict | None = None,
    ) -> Candidate:
        candidate_id = (
            result.candidate_id
            if result.candidate_id is not None
            else fallback_candidate_id
        )
        confidence, verification_trace, verifications = self.evaluator.verify(
            context,
            result.text,
            candidate_id,
        )
        context.trace.extend(verification_trace)
        answer = build_answer(extract_answer(result.text))
        metadata = {
            "source": "recovery" if result.stage == "recovery" else result.stage,
            "candidate_id": candidate_id,
            "request_id": result.request_id,
            "truncated": False,
        }
        if extra_metadata:
            metadata.update(extra_metadata)
        return Candidate(
            content=result.text,
            strategy=(
                strategy
                if strategy is not None
                else "plain"
            ),
            confidence=confidence + (0.3 if answer.raw else -0.5),
            answer=answer,
            raw_confidence=confidence,
            verifications=verifications,
            metadata=metadata,
        )

    def _emergency_or_unsolved(
        self,
        context: SolveContext,
        emergency_hints: list[str],
        *,
        allow_emergency: bool,
    ) -> dict:
        if allow_emergency:
            answer = self.generator.emergency_answer(context, emergency_hints)
            if answer:
                return {
                    "final_response": build_response("", answer),
                    "trace": context.trace,
                }
        return {"final_response": "未解出", "trace": context.trace}
