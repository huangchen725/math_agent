"""Candidate generation, truncation recovery, and emergency answer handling."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .agent_config import AgentConfig
from .agent_prompts import POLICY_NO_TOOL_PROMPT, POLICY_PROMPT
from .agent_types import ModelCallResult
from .answer_equivalence import format_answer_for_output
from .budget import BudgetExceeded
from .context import SolveContext
from .model_calls import call_model_result, call_model_text
from .response_processing import extract_answer, extract_first_line_answer
from .tool_loop import run_tool_loop
from .truncation import mark_truncation


@dataclass
class GenerationBatch:
    """Complete candidates plus quarantined-answer hints and trace events."""

    candidates: list[ModelCallResult]
    trace: list[dict]
    emergency_hints: list[str]


def is_proof_like(problem: str) -> bool:
    normalized = problem.casefold()
    markers = (
        "证明", "推导", "分类讨论", "讨论所有", "充要条件", "必要性", "充分性",
        "prove", "show that", "derive", "classify", "if and only if",
    )
    return any(marker in normalized for marker in markers)


def reasoning_target_tokens(problem: str, config: AgentConfig) -> int:
    return (
        config.proof_reasoning_target_tokens
        if is_proof_like(problem)
        else config.calculation_reasoning_target_tokens
    )


def reasoning_instruction(target_tokens: int) -> str:
    return (
        f"将推理目标控制在 {target_tokens} 输出 token 以内；只保留决定结论的步骤，"
        "省略重复验算、背景定义和无关展开。第一行必须先给最终答案。"
    )


def model_result_trace(result: ModelCallResult, step: str) -> list[dict]:
    if result.truncated:
        return [{
            "step": step,
            "content": {
                "stage": result.stage,
                "candidate_id": result.candidate_id,
                "finish_reason": result.finish_reason,
                "response_quarantined": True,
            },
        }]
    return [{"step": step, "content": result.text[:1000]}]


class CandidateGenerator:
    """Generate candidates and ensure truncated text cannot enter aggregation."""

    def __init__(self, config: AgentConfig) -> None:
        self.config = config

    def generate(
        self,
        context: SolveContext,
        domain_prompt: str,
        reasoning_target: int,
    ) -> GenerationBatch:
        candidates: list[ModelCallResult] = []
        trace: list[dict] = []
        emergency_hints: list[str] = []
        candidate_id = 0

        for index in range(self.config.tool_candidates):
            if self.config.enable_tools:
                result, tool_trace = self.solve_tools_result(
                    context,
                    candidate_id,
                    domain_prompt,
                    reasoning_target,
                )
            else:
                result = self.solve_plain_result(
                    context,
                    domain_prompt,
                    reasoning_target,
                    candidate_id=candidate_id,
                )
                tool_trace = model_result_trace(result, f"policy_tool_{index}")
            prepared, hint = self.prepare_candidate(context, result, candidate_id)
            if prepared:
                candidates.append(prepared)
            if hint:
                emergency_hints.append(hint)
            trace.extend(tool_trace)
            candidate_id += 1

        for index in range(self.config.plain_candidates):
            result = self.solve_plain_result(
                context,
                domain_prompt,
                reasoning_target,
                candidate_id=candidate_id,
            )
            prepared, hint = self.prepare_candidate(context, result, candidate_id)
            if prepared:
                candidates.append(prepared)
            if hint:
                emergency_hints.append(hint)
            trace.extend(model_result_trace(result, f"policy_plain_{index}"))
            candidate_id += 1

        return GenerationBatch(candidates, trace, emergency_hints)

    def solve_tools_result(
        self,
        context: SolveContext,
        candidate_id: int,
        domain_prompt: str,
        target_tokens: int,
    ) -> tuple[ModelCallResult, list[dict]]:
        try:
            length_instruction = reasoning_instruction(target_tokens)
            messages = [
                {"role": "system", "content": domain_prompt or POLICY_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"{context.problem}\n\n请调用工具验证关键计算。候选编号：{candidate_id}。"
                        f"\n{length_instruction}"
                    ),
                },
            ]
            _, tool_trace, result = run_tool_loop(
                context.gateway,
                messages,
                max_rounds=self.config.max_tool_rounds,
                thinking_mode=self.config.policy_thinking_mode,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
                tool_timeout_seconds=self.config.tool_timeout_seconds,
                candidate_id=candidate_id,
                final_instruction=(
                    "工具轮次已结束。第一行必须写“最终答案：XXX”，再给出必要推导。"
                    + length_instruction
                ),
                return_call_result=True,
            )
            trace = [{"step": f"tool_solve_{candidate_id}", "content": tool_trace}]
            trace.extend(model_result_trace(result, f"policy_tool_{candidate_id}"))
            return result, trace
        except BudgetExceeded:
            raise
        except Exception as exc:
            trace = [{"step": f"tool_error_{candidate_id}", "content": str(exc)[:200]}]
            fallback = self.solve_plain_result(
                context,
                domain_prompt,
                target_tokens,
                candidate_id=candidate_id,
            )
            return fallback, trace

    def solve_plain_result(
        self,
        context: SolveContext,
        domain_prompt: str,
        target_tokens: int,
        *,
        candidate_id: int | None = None,
    ) -> ModelCallResult:
        try:
            return call_model_result(
                context,
                domain_prompt or POLICY_NO_TOOL_PROMPT,
                f"{context.problem}\n\n请给出完整解答。\n{reasoning_instruction(target_tokens)}",
                stage="policy_plain",
                candidate_id=candidate_id,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
                thinking_mode=self.config.policy_thinking_mode,
            )
        except BudgetExceeded:
            raise
        except Exception as exc:
            return ModelCallResult(
                text="",
                stage="policy_plain",
                finish_reason=f"error:{type(exc).__name__}",
                candidate_id=candidate_id,
            )

    def prepare_candidate(
        self,
        context: SolveContext,
        result: ModelCallResult,
        candidate_id: int,
    ) -> tuple[ModelCallResult | None, str]:
        """Accept a complete candidate or recover a truncated one exactly once."""
        if not result.truncated:
            if extract_answer(result.text):
                return result, ""
            context.trace.append({
                "step": "candidate_rejected",
                "content": {
                    "candidate_id": candidate_id,
                    "stage": result.stage,
                    "reason": "missing_explicit_answer",
                },
            })
            return None, ""

        original_answer = extract_first_line_answer(result.text)
        recovery_limit = max(0, self.config.max_recovery_requests - 1)
        can_recover = (
            self.config.max_recoveries_per_candidate > 0
            and context.budget.recovery_requests < recovery_limit
        )
        event = {
            "candidate_id": candidate_id,
            "stage": result.stage,
            "original_answer_present": bool(original_answer),
            "recovery_attempted": can_recover,
        }
        if not can_recover:
            mark_truncation(context, result, "quarantined", bool(original_answer))
            event["recovery_result"] = "quarantined"
            context.trace.append({"step": "truncation_recovery", "content": event})
            return None, original_answer

        if original_answer:
            recovery_prompt = (
                f"原题：\n{context.problem}\n\n截断回复第一行给出的答案是：{original_answer}\n\n"
                "请独立核验这个答案；如有错请纠正。第一行只写“最终答案：XXX”，"
                "随后只给决定结论的核验，目标不超过 800 输出 token。"
            )
        else:
            recovery_prompt = (
                f"原题：\n{context.problem}\n\n上一次解答被截断且没有可用答案。"
                "请重新短解，第一行只写“最终答案：XXX”，随后只保留决定结论的步骤，"
                "省略背景和重复验算。"
            )
        try:
            recovered = call_model_result(
                context,
                POLICY_NO_TOOL_PROMPT,
                recovery_prompt,
                stage="recovery",
                candidate_id=candidate_id,
                recovery=True,
                temperature=0.0,
                max_tokens=self.config.recovery_max_tokens,
                thinking_mode=False,
            )
        except BudgetExceeded:
            mark_truncation(context, result, "quarantined", bool(original_answer))
            event["recovery_result"] = "budget_exhausted"
            context.trace.append({"step": "truncation_recovery", "content": event})
            return None, original_answer

        recovered_answer = extract_first_line_answer(recovered.text)
        if not recovered.truncated and recovered_answer:
            mark_truncation(context, result, "recovered", bool(original_answer))
            event["recovery_result"] = "success"
            context.trace.append({"step": "truncation_recovery", "content": event})
            return recovered, original_answer

        if recovered.truncated:
            mark_truncation(context, recovered, "quarantined", bool(recovered_answer))
        mark_truncation(context, result, "recovery_failed", bool(original_answer))
        event["recovery_result"] = (
            "truncated_again" if recovered.truncated else "missing_explicit_answer"
        )
        context.trace.append({"step": "truncation_recovery", "content": event})
        return None, recovered_answer or original_answer

    def emergency_answer(self, context: SolveContext, answer_hints: list[str]) -> str:
        """Make one short whole-problem answer call and quarantine its reasoning."""
        if self.config.max_recovery_requests <= 0:
            return ""
        unique_hints: list[str] = []
        for hint in answer_hints:
            normalized = format_answer_for_output(hint)
            if normalized and normalized not in unique_hints:
                unique_hints.append(normalized[:200])
        hint_text = (
            "\n可供独立检查的截断首行答案：" + "；".join(unique_hints[:4])
            if unique_hints else ""
        )
        try:
            result = call_model_result(
                context,
                POLICY_NO_TOOL_PROMPT,
                f"{context.problem}{hint_text}\n\n所有完整候选均不可用。请独立作答。"
                "第一行且只需一行输出“最终答案：XXX”，XXX 只写答案本体。",
                stage="emergency",
                recovery=True,
                temperature=0.0,
                max_tokens=self.config.fallback_max_tokens,
                thinking_mode=False,
            )
        except BudgetExceeded as exc:
            context.trace.append({"step": "emergency_unavailable", "content": str(exc)[:200]})
            return ""

        answer = extract_first_line_answer(result.text)
        if result.truncated:
            if answer:
                mark_truncation(context, result, "answer_salvaged", True)
                source = "emergency_truncated_answer_only"
            else:
                mark_truncation(context, result, "quarantined", False)
                context.trace.append({
                    "step": "emergency_result",
                    "content": {"valid": False, "truncated": True},
                })
                return ""
        elif answer:
            source = "emergency"
        else:
            context.trace.append({
                "step": "emergency_result",
                "content": {"valid": False, "truncated": False},
            })
            return ""

        context.budget.set_final_answer_source(source)
        context.trace.append({
            "step": "final_answer_source",
            "content": {"source": source, "reasoning_included": False},
        })
        return answer

    def quick_fallback(self, context: SolveContext) -> str:
        """Best-effort answer used only after an unexpected pipeline exception."""
        try:
            response = call_model_text(
                context,
                POLICY_NO_TOOL_PROMPT,
                f"{context.problem}\n\n请直接给出最终答案，不要详细推导。"
                "单独一行按“最终答案：XXX”输出，XXX 只写答案本体。",
                temperature=0.0,
                max_tokens=self.config.fallback_max_tokens,
                thinking_mode=False,
            )
            answer = extract_answer(response)
            context.trace.append({"step": "fallback_result", "content": answer[:100]})
            if answer:
                return answer
            bare = response.strip()
            if (
                "\n" not in bare
                and 0 < len(bare) <= 200
                and not re.search(r"[。！？]|因此|无法|需要|计算|推理|解答", bare)
            ):
                return bare
            return ""
        except BudgetExceeded:
            raise
        except Exception:
            return ""
