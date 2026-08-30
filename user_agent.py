"""数学推理智能体的竞赛接口与求解流水线。

接口约束：solve(problem, metadata) -> {"final_response": str, "trace": list}
架构事实源：ARCHITECTURE.md
"""
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from agent_types import Candidate, ModelCallResult, Verification
from answer_equivalence import (
    build_answer,
    format_answer_for_output,
    normalize_answer,
    numeric_value,
)
from budget import BudgetExceeded, ExecutionBudget
from deterministic_verifier import verify_task_plan
from llm_client import InternChatClient
from math_tools import run_tool_loop
from domain_prompts import get_domain_prompt
from task_router import TaskAnalysis, analyze_task


_ACTIVE_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "active_problem_budget",
    default=None,
)


# ==================== 提示词 ====================

POLICY_PROMPT = """你是数学推理智能体。解题并给出推理过程。

输出顺序：
1. 第一行先写：最终答案：XXX
2. 解题思路
3. 关键推导步骤

最终答案行只写答案本体，不写“答案是”、解释或完整句子；若已有精确形式，不要只写小数近似值；能等价表示时优先使用 ASCII 记号（如 x^2、C1、Z），复杂公式可用 LaTeX。
即使推导很长，也必须先写第一行答案。只保留决定结论的推导，省略重复验算、背景定义和无关展开。
"""

POLICY_NO_TOOL_PROMPT = """你是数学推理智能体。用纯推理解题。

输出顺序：
1. 第一行先写：最终答案：XXX
2. 解题思路
3. 关键推导

最终答案行只写答案本体，不写“答案是”、解释或完整句子；若已有精确形式，不要只写小数近似值；能等价表示时优先使用 ASCII 记号（如 x^2、C1、Z），复杂公式可用 LaTeX。
即使推导很长，也必须先写第一行答案。只保留决定结论的推导，省略重复验算、背景定义和无关展开。
"""

VERIFIER_PROMPT = """你是数学答案验证器。请判断候选解答是否正确。

判断维度：1.推理逻辑 2.计算准确性 3.最终答案

只输出一行：VERDICT: A（正确）或 VERDICT: B（错误）。不要解释。"""

CRITIC_PROMPT = """你是数学解题批评者。请找出候选解答中的错误或可改进之处。

检查：1.逻辑漏洞 2.计算错误 3.边界情况 4.答案格式

如果有错误，用不超过 6 行指出首个决定性错误和正确做法，不要复述题目或完整解答。如果没有错误，只输出：NO ERROR"""

REFLECTION_PROMPT = """你之前的解答可能有误。请根据反馈重新解答。

原题：{problem}
之前的解答：{prev_answer}
批评反馈：{feedback}

请修正错误。第一行先写“最终答案：XXX”，再给出紧凑的完整推理；XXX 只包含答案本体，若已有精确形式，不要只写小数近似值。省略重复验算、背景定义和无关展开。"""


@dataclass
class AgentConfig:
    """当前竞赛流水线配置。"""
    # 候选生成：固定预算，全部使用同一策略温度。
    tool_candidates: int = 2
    plain_candidates: int = 1
    verifier_voting_times: int = 1
    # 温度
    policy_temperature: float = 0.6
    verifier_temperature: float = 0.0
    critic_temperature: float = 0.3
    reflection_temperature: float = 0.3
    # token
    max_tokens: int = 8192
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    calculation_reasoning_target_tokens: int = 1800
    proof_reasoning_target_tokens: int = 3500
    recovery_max_tokens: int = 2048
    max_recoveries_per_candidate: int = 1
    max_recovery_requests: int = 4
    # thinking mode（v13: False——thinking导致截断）
    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    critic_thinking_mode: bool = False
    # 功能开关
    enable_tools: bool = True
    enable_critic: bool = True
    enable_reflection: bool = True
    enable_fallback: bool = True
    enable_deterministic_verification: bool = True
    max_tool_rounds: int = 3
    tool_timeout_seconds: float = 5.0
    max_model_requests: int = 16
    max_total_tokens: int = 200_000
    max_tool_calls: int = 48
    problem_timeout_seconds: float = 600.0
    max_problem_chars: int = 20_000
    max_metadata_chars: int = 20_000

    def __post_init__(self) -> None:
        for name in (
            "max_tokens",
            "verifier_max_tokens",
            "critic_max_tokens",
            "fallback_max_tokens",
            "calculation_reasoning_target_tokens",
            "proof_reasoning_target_tokens",
            "recovery_max_tokens",
            "max_model_requests",
            "max_total_tokens",
            "max_tool_calls",
        ):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        for name in ("max_recoveries_per_candidate", "max_recovery_requests"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.max_recoveries_per_candidate > 1:
            raise ValueError("max_recoveries_per_candidate cannot exceed 1")


class ReasoningAgent:
    """领域路由、工具增强、验证、反思与聚合智能体。"""

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client

    def _chat_result(
        self,
        system_prompt: str,
        user_content: str,
        *,
        stage: str,
        candidate_id: int | None = None,
        recovery: bool = False,
        **kwargs: Any,
    ) -> ModelCallResult:
        """调用模型，并返回文本及当前调用的无敏感元数据。"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        budget = _ACTIVE_BUDGET.get()
        request_id = None
        if budget is not None:
            request_id = budget.consume_model_request(
                stage=stage,
                candidate_id=candidate_id,
                recovery=recovery,
            )
        resp = self.client.chat(messages=messages, **kwargs)
        metadata: Dict[str, Any] = {}
        if budget is not None and hasattr(self.client, "get_last_response_meta"):
            metadata = self.client.get_last_response_meta()
            metadata = metadata if isinstance(metadata, dict) else {}
            budget.record_response_meta(metadata, request_id)
        elif hasattr(self.client, "get_last_response_meta"):
            metadata = self.client.get_last_response_meta()
            metadata = metadata if isinstance(metadata, dict) else {}
        text = resp if isinstance(resp, str) else str(resp.get("content", ""))
        return ModelCallResult(
            text=text,
            stage=stage,
            finish_reason=str(metadata.get("finish_reason", "")),
            usage=metadata.get("usage", {}) if isinstance(metadata, dict) else {},
            candidate_id=candidate_id,
            request_id=request_id,
        )

    def _chat(self, system_prompt: str, user_content: str, **kwargs: Any) -> str:
        """兼容旧内部调用：仍只返回文本。"""
        stage = str(kwargs.pop("stage", "unknown"))
        candidate_id = kwargs.pop("candidate_id", None)
        recovery = bool(kwargs.pop("recovery", False))
        return self._chat_result(
            system_prompt,
            user_content,
            stage=stage,
            candidate_id=candidate_id,
            recovery=recovery,
            **kwargs,
        ).text

    def solve(self, problem: str, metadata: Dict) -> Dict:
        """主求解流程。全局 try-except 防空答案。"""
        trace: List[Dict] = []
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
        budget = ExecutionBudget(
            max_model_requests=self.config.max_model_requests,
            max_recovery_requests=self.config.max_recovery_requests,
            max_total_tokens=self.config.max_total_tokens,
            max_tool_calls=self.config.max_tool_calls,
            timeout_seconds=self.config.problem_timeout_seconds,
        )
        budget_token = _ACTIVE_BUDGET.set(budget)
        try:
            try:
                result = self._solve_impl(problem, trace)
            except BudgetExceeded as e:
                trace.append({"step": "budget_exceeded", "content": str(e)[:300]})
                result = {"final_response": "未解出", "trace": trace}
            except Exception as e:
                trace.append({
                    "step": "global_error",
                    "content": f"{type(e).__name__}: {str(e)[:300]}",
                })
                try:
                    fb = self._quick_fallback(problem, trace)
                    final_response = self._build_response("", fb) if fb else "未解出"
                    result = {"final_response": final_response, "trace": trace}
                except BudgetExceeded as budget_error:
                    trace.append({
                        "step": "budget_exceeded",
                        "content": str(budget_error)[:300],
                    })
                    result = {"final_response": "未解出", "trace": trace}
            self._contain_pending_truncations(budget)
            trace.append({"step": "budget_summary", "content": budget.snapshot()})
            return result
        finally:
            _ACTIVE_BUDGET.reset(budget_token)

    def _solve_impl(self, problem: str, trace: List[Dict]) -> Dict:
        # 阶段1：关键词检测领域
        domain_name = self._detect_domain(problem)
        domain_prompt = get_domain_prompt(domain_name)
        if domain_name:
            trace.append({"step": "domain_detect", "content": f"关键词识别: {domain_name}"})

        task_analysis = analyze_task(problem)
        trace.append({
            "step": "task_route",
            "content": {
                "task_types": list(task_analysis.task_types),
                "confidence": task_analysis.confidence,
                "deterministic_verifier": (
                    task_analysis.verification_plan.kind
                    if task_analysis.verification_plan is not None
                    else ""
                ),
                "reason": task_analysis.reason,
            },
        })

        # 阶段2：多候选生成。API 上限保持 8192，prompt 按题型约束目标长度。
        reasoning_target = self._reasoning_target_tokens(problem)
        trace.append({
            "step": "reasoning_budget",
            "content": {
                "kind": "proof" if self._is_proof_like(problem) else "calculation",
                "target_tokens": reasoning_target,
                "api_max_tokens": self.config.max_tokens,
            },
        })
        candidates, gen_trace, emergency_hints = self._generate_candidates(
            problem,
            domain_prompt,
            reasoning_target,
        )
        trace.extend(gen_trace)

        # 所有正常候选都不可用时，只允许一次整题紧急答案调用。
        if not candidates:
            trace.append({
                "step": "emergency_required",
                "content": {"reason": "no_eligible_candidate"},
            })
            if self.config.enable_fallback:
                answer = self._emergency_answer(problem, emergency_hints, trace)
                if answer:
                    return {
                        "final_response": self._build_response("", answer),
                        "trace": trace,
                    }
            return {"final_response": "未解出", "trace": trace}

        # 阶段3：验证投票
        scored: List[Candidate] = []
        for cid, result in enumerate(candidates):
            candidate_id = result.candidate_id if result.candidate_id is not None else cid
            confidence, vt, verifications = self._verify(
                problem,
                result.text,
                candidate_id,
                task_analysis=task_analysis,
            )
            answer = build_answer(self._extract_answer(result.text))
            strategy = "tool" if result.stage in {"policy_tool", "tool_final"} else "plain"
            scored.append(Candidate(
                content=result.text,
                strategy=strategy,
                confidence=confidence + (0.3 if answer.raw else -0.5),
                answer=answer,
                raw_confidence=confidence,
                verifications=verifications,
                metadata={
                    "source": "recovery" if result.stage == "recovery" else result.stage,
                    "candidate_id": candidate_id,
                    "request_id": result.request_id,
                    "truncated": False,
                },
            ))
            trace.extend(vt)

        # 阶段4：Critic + 反思（仅低置信度触发）
        if self.config.enable_critic and scored:
            best = max(scored, key=lambda item: item.confidence)
            if best.raw_confidence < 0.5 and best.answer.raw:
                criticism = self._critic(problem, best.content, trace)
                if criticism and "NO ERROR" not in criticism.upper():
                    reflection_cid = (
                        self.config.tool_candidates + self.config.plain_candidates
                    )
                    refined_result = self._reflect_result(
                        problem,
                        best.content,
                        criticism,
                        trace,
                        candidate_id=reflection_cid,
                    )
                    refined, hint = self._prepare_candidate(
                        problem,
                        refined_result,
                        reflection_cid,
                        trace,
                    )
                    if hint:
                        emergency_hints.append(hint)
                    if refined:
                        rc, rv, verifications = self._verify(
                            problem,
                            refined.text,
                            reflection_cid,
                            task_analysis=task_analysis,
                        )
                        ra = build_answer(self._extract_answer(refined.text))
                        scored.append(Candidate(
                            content=refined.text,
                            strategy="reflection",
                            confidence=rc + (0.3 if ra.raw else -0.5),
                            answer=ra,
                            raw_confidence=rc,
                            verifications=verifications,
                            metadata={
                                "temperature": self.config.reflection_temperature,
                                "source": (
                                    "recovery" if refined.stage == "recovery" else "reflection"
                                ),
                                "candidate_id": reflection_cid,
                                "request_id": refined.request_id,
                                "truncated": False,
                            },
                        ))
                        trace.extend(rv)

        # 阶段6：加权聚合
        final_answer, best_content = self._aggregate(scored, trace)
        if not final_answer:
            answer = self._emergency_answer(problem, emergency_hints, trace)
            if answer:
                return {
                    "final_response": self._build_response("", answer),
                    "trace": trace,
                }
            return {"final_response": "未解出", "trace": trace}
        final_response = self._build_response(best_content, final_answer)

        return {"final_response": final_response or final_answer or "未解出", "trace": trace}

    def _build_response(self, content: str, answer: str) -> str:
        formatted_answer = format_answer_for_output(answer)
        if not formatted_answer:
            return "未解出"
        formatted_answer = formatted_answer.splitlines()[0].strip()
        if not formatted_answer:
            return "未解出"
        if not content:
            return self._validated_response(f"最终答案：{formatted_answer}", formatted_answer)
        body_lines = [
            line
            for line in content.strip().splitlines()
            if not re.search(
                r"(?:最终答案\s*(?:是|为)?\s*[:：]?|答案\s*(?:是|为)\s*[:：]?|答案\s*[:：])",
                line,
            )
        ]
        body = "\n".join(body_lines).strip()
        if not body:
            return self._validated_response(f"最终答案：{formatted_answer}", formatted_answer)
        response = f"{body}\n最终答案：{formatted_answer}"
        return self._validated_response(response, formatted_answer)

    def _generate_candidates(
        self,
        problem: str,
        domain_prompt: str,
        reasoning_target: int,
    ) -> Tuple[List[ModelCallResult], List[Dict], List[str]]:
        """生成候选，并在截断时恢复一次；残缺文本永不进入候选列表。"""
        candidates: List[ModelCallResult] = []
        trace: List[Dict] = []
        emergency_hints: List[str] = []
        candidate_id = 0
        for i in range(self.config.tool_candidates):
            if self.config.enable_tools:
                result, tt = self._solve_tools_result(
                    problem,
                    candidate_id,
                    domain_prompt,
                    reasoning_target,
                )
            else:
                result = self._solve_plain_result(
                    problem,
                    domain_prompt,
                    reasoning_target,
                    candidate_id=candidate_id,
                )
                tt = self._candidate_trace(result, f"policy_tool_{i}")
            prepared, hint = self._prepare_candidate(problem, result, candidate_id, trace)
            if prepared:
                candidates.append(prepared)
            if hint:
                emergency_hints.append(hint)
            trace.extend(tt)
            candidate_id += 1
        for i in range(self.config.plain_candidates):
            result = self._solve_plain_result(
                problem,
                domain_prompt,
                reasoning_target,
                candidate_id=candidate_id,
            )
            prepared, hint = self._prepare_candidate(problem, result, candidate_id, trace)
            if prepared:
                candidates.append(prepared)
            if hint:
                emergency_hints.append(hint)
            trace.extend(self._candidate_trace(result, f"policy_plain_{i}"))
            candidate_id += 1
        return candidates, trace, emergency_hints

    def _solve_tools_result(
        self,
        problem: str,
        cid: int,
        domain_prompt: str,
        reasoning_target: int,
    ) -> Tuple[ModelCallResult, List[Dict]]:
        try:
            length_instruction = self._reasoning_instruction(reasoning_target)
            messages = [
                {"role": "system", "content": domain_prompt or POLICY_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"{problem}\n\n请调用工具验证关键计算。候选编号：{cid}。"
                        f"\n{length_instruction}"
                    ),
                },
            ]
            response, tt, result = run_tool_loop(
                self.client, messages,
                max_rounds=self.config.max_tool_rounds,
                thinking_mode=self.config.policy_thinking_mode,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
                tool_timeout_seconds=self.config.tool_timeout_seconds,
                budget=_ACTIVE_BUDGET.get(),
                candidate_id=cid,
                final_instruction=(
                    "工具轮次已结束。第一行必须写“最终答案：XXX”，再给出必要推导。"
                    + length_instruction
                ),
                return_call_result=True,
            )
            trace = [{"step": f"tool_solve_{cid}", "content": tt}]
            trace.extend(self._candidate_trace(result, f"policy_tool_{cid}"))
            return result, trace
        except BudgetExceeded:
            raise
        except Exception as e:
            trace = [{"step": f"tool_error_{cid}", "content": str(e)[:200]}]
            return self._solve_plain_result(
                problem,
                domain_prompt,
                reasoning_target,
                candidate_id=cid,
            ), trace

    def _solve_plain_result(
        self,
        problem: str,
        domain_prompt: str,
        reasoning_target: int,
        *,
        candidate_id: int | None = None,
    ) -> ModelCallResult:
        try:
            prefix = domain_prompt or POLICY_NO_TOOL_PROMPT
            return self._chat_result(
                prefix,
                f"{problem}\n\n请给出完整解答。\n{self._reasoning_instruction(reasoning_target)}",
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

    def _solve_plain(self, problem: str, domain_prompt: str) -> str:
        """兼容旧内部测试的纯文本包装。"""
        return self._solve_plain_result(
            problem,
            domain_prompt,
            self._reasoning_target_tokens(problem),
        ).text

    def _verify(
        self,
        problem: str,
        candidate: str,
        cid: int,
        *,
        task_analysis: TaskAnalysis | None = None,
    ) -> Tuple[float, List[Dict], List[Verification]]:
        votes: List[bool] = []
        trace, verifications = [], []
        task_analysis = task_analysis or analyze_task(problem)
        candidate_answer = self._extract_answer(candidate)
        plan = task_analysis.verification_plan
        if self.config.enable_deterministic_verification and plan and candidate_answer:
            budget = _ACTIVE_BUDGET.get()
            try:
                if budget is not None:
                    budget.consume_tool_call()
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
                "step": f"deterministic_verify_{cid}",
                "content": {
                    "source": evidence.source,
                    "status": evidence.status,
                    "detail": evidence.detail[:200],
                },
            })
        review_text = self._review_excerpt(candidate)
        for vid in range(self.config.verifier_voting_times):
            try:
                result = self._chat_result(VERIFIER_PROMPT,
                    f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n判断是否正确。只输出：VERDICT: A 或 VERDICT: B",
                    stage="verifier",
                    candidate_id=cid,
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens,
                    thinking_mode=self.config.verifier_thinking_mode)
                if result.truncated:
                    result = self._retry_truncated_verifier(problem, review_text, cid, result, trace)
                verdict = result.text
                parsed = self._parse_verdict(verdict) if not result.truncated else None
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
                    "step": f"verify_{cid}_{vid}",
                    "content": verdict[:200] if not result.truncated else "截断结果已隔离",
                })
            except BudgetExceeded:
                raise
            except Exception as e:
                verifications.append(Verification(
                    source="model",
                    status="unknown",
                    confidence=0.0,
                    detail=f"{type(e).__name__}: {str(e)[:160]}",
                ))
                trace.append({"step": f"verify_err_{cid}_{vid}", "content": str(e)[:200]})
        return (sum(votes) / len(votes) if votes else 0.5), trace, verifications

    def _critic(self, problem: str, candidate: str, trace: List[Dict]) -> str:
        try:
            review_text = self._review_excerpt(candidate)
            result = self._chat_result(CRITIC_PROMPT,
                f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n请找出错误或改进点。",
                stage="critic",
                temperature=self.config.critic_temperature,
                max_tokens=self.config.critic_max_tokens,
                thinking_mode=self.config.critic_thinking_mode)
            if result.truncated:
                self._mark_truncation(result, "quarantined", bool(self._extract_first_line_answer(result.text)))
                trace.append({"step": "critic_truncated", "content": {"action": "discard"}})
                return ""
            criticism = result.text
            trace.append({"step": "critic", "content": criticism[:500]})
            return criticism
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "critic_error", "content": str(e)[:200]})
            return ""

    def _reflect_result(
        self,
        problem: str,
        prev: str,
        feedback: str,
        trace: List[Dict],
        *,
        candidate_id: int,
    ) -> ModelCallResult:
        try:
            prompt = REFLECTION_PROMPT.format(
                problem=problem,
                prev_answer=self._review_excerpt(prev, limit=2000),
                feedback=feedback[:500],
            )
            prompt += "\n" + self._reasoning_instruction(self._reasoning_target_tokens(problem))
            result = self._chat_result(
                POLICY_PROMPT,
                prompt,
                stage="reflection",
                candidate_id=candidate_id,
                temperature=self.config.reflection_temperature,
                max_tokens=self.config.max_tokens,
                thinking_mode=self.config.policy_thinking_mode,
            )
            trace.extend(self._candidate_trace(result, "reflection"))
            return result
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "reflect_error", "content": str(e)[:200]})
            return ModelCallResult(
                text="",
                stage="reflection",
                finish_reason=f"error:{type(e).__name__}",
                candidate_id=candidate_id,
            )

    def _reflect(self, problem: str, prev: str, feedback: str, trace: List[Dict]) -> str:
        """兼容旧内部调用的纯文本包装。"""
        return self._reflect_result(
            problem,
            prev,
            feedback,
            trace,
            candidate_id=-1,
        ).text

    @staticmethod
    def _candidate_trace(result: ModelCallResult, step: str) -> List[Dict]:
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

    def _prepare_candidate(
        self,
        problem: str,
        result: ModelCallResult,
        candidate_id: int,
        trace: List[Dict],
    ) -> Tuple[ModelCallResult | None, str]:
        """Accept a complete candidate or recover a truncated one exactly once."""
        if not result.truncated:
            if self._extract_answer(result.text):
                return result, ""
            trace.append({
                "step": "candidate_rejected",
                "content": {
                    "candidate_id": candidate_id,
                    "stage": result.stage,
                    "reason": "missing_explicit_answer",
                },
            })
            return None, ""

        original_answer = self._extract_first_line_answer(result.text)
        budget = _ACTIVE_BUDGET.get()
        recovery_limit = max(0, self.config.max_recovery_requests - 1)
        can_recover = (
            self.config.max_recoveries_per_candidate > 0
            and budget is not None
            and budget.recovery_requests < recovery_limit
        )
        event = {
            "candidate_id": candidate_id,
            "stage": result.stage,
            "original_answer_present": bool(original_answer),
            "recovery_attempted": can_recover,
        }
        if not can_recover:
            self._mark_truncation(result, "quarantined", bool(original_answer))
            event["recovery_result"] = "quarantined"
            trace.append({"step": "truncation_recovery", "content": event})
            return None, original_answer

        if original_answer:
            recovery_prompt = (
                f"原题：\n{problem}\n\n截断回复第一行给出的答案是：{original_answer}\n\n"
                "请独立核验这个答案；如有错请纠正。第一行只写“最终答案：XXX”，"
                "随后只给决定结论的核验，目标不超过 800 输出 token。"
            )
        else:
            recovery_prompt = (
                f"原题：\n{problem}\n\n上一次解答被截断且没有可用答案。"
                "请重新短解，第一行只写“最终答案：XXX”，随后只保留决定结论的步骤，"
                "省略背景和重复验算。"
            )
        try:
            recovered = self._chat_result(
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
            self._mark_truncation(result, "quarantined", bool(original_answer))
            event["recovery_result"] = "budget_exhausted"
            trace.append({"step": "truncation_recovery", "content": event})
            return None, original_answer

        recovered_answer = self._extract_first_line_answer(recovered.text)
        if not recovered.truncated and recovered_answer:
            self._mark_truncation(result, "recovered", bool(original_answer))
            event["recovery_result"] = "success"
            trace.append({"step": "truncation_recovery", "content": event})
            return recovered, original_answer

        if recovered.truncated:
            self._mark_truncation(
                recovered,
                "quarantined",
                bool(recovered_answer),
            )
        self._mark_truncation(result, "recovery_failed", bool(original_answer))
        event["recovery_result"] = (
            "truncated_again" if recovered.truncated else "missing_explicit_answer"
        )
        trace.append({"step": "truncation_recovery", "content": event})
        return None, recovered_answer or original_answer

    def _retry_truncated_verifier(
        self,
        problem: str,
        review_text: str,
        candidate_id: int,
        original: ModelCallResult,
        trace: List[Dict],
    ) -> ModelCallResult:
        """Retry a truncated verifier once; unresolved output remains unknown."""
        try:
            retried = self._chat_result(
                VERIFIER_PROMPT,
                f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n"
                "上次验证输出被截断。只输出一行 VERDICT: A 或 VERDICT: B。",
                stage="verifier",
                candidate_id=candidate_id,
                temperature=self.config.verifier_temperature,
                max_tokens=self.config.verifier_max_tokens,
                thinking_mode=self.config.verifier_thinking_mode,
            )
        except BudgetExceeded:
            self._mark_truncation(original, "quarantined", False)
            trace.append({
                "step": "verifier_recovery",
                "content": {"candidate_id": candidate_id, "result": "budget_exhausted"},
            })
            return original

        parsed = None if retried.truncated else self._parse_verdict(retried.text)
        if parsed is not None:
            self._mark_truncation(original, "recovered", False)
            status = "success"
        else:
            self._mark_truncation(original, "recovery_failed", False)
            status = "truncated_again" if retried.truncated else "unknown"
        if retried.truncated:
            self._mark_truncation(retried, "quarantined", False)
        trace.append({
            "step": "verifier_recovery",
            "content": {"candidate_id": candidate_id, "result": status},
        })
        return retried

    def _emergency_answer(
        self,
        problem: str,
        answer_hints: List[str],
        trace: List[Dict],
    ) -> str:
        """Make one short whole-problem answer call while quarantining its reasoning."""
        budget = _ACTIVE_BUDGET.get()
        if budget is None or self.config.max_recovery_requests <= 0:
            return ""
        unique_hints = []
        for hint in answer_hints:
            normalized = format_answer_for_output(hint)
            if normalized and normalized not in unique_hints:
                unique_hints.append(normalized[:200])
        hint_text = (
            "\n可供独立检查的截断首行答案：" + "；".join(unique_hints[:4])
            if unique_hints else ""
        )
        try:
            result = self._chat_result(
                POLICY_NO_TOOL_PROMPT,
                f"{problem}{hint_text}\n\n所有完整候选均不可用。请独立作答。"
                "第一行且只需一行输出“最终答案：XXX”，XXX 只写答案本体。",
                stage="emergency",
                recovery=True,
                temperature=0.0,
                max_tokens=self.config.fallback_max_tokens,
                thinking_mode=False,
            )
        except BudgetExceeded as exc:
            trace.append({"step": "emergency_unavailable", "content": str(exc)[:200]})
            return ""
        answer = self._extract_first_line_answer(result.text)
        if result.truncated:
            if answer:
                self._mark_truncation(result, "answer_salvaged", True)
                source = "emergency_truncated_answer_only"
            else:
                self._mark_truncation(result, "quarantined", False)
                trace.append({
                    "step": "emergency_result",
                    "content": {"valid": False, "truncated": True},
                })
                return ""
        elif answer:
            source = "emergency"
        else:
            trace.append({
                "step": "emergency_result",
                "content": {"valid": False, "truncated": False},
            })
            return ""
        if budget is not None:
            budget.set_final_answer_source(source)
        trace.append({
            "step": "final_answer_source",
            "content": {"source": source, "reasoning_included": False},
        })
        return answer

    @staticmethod
    def _validated_response(response: str, answer: str) -> str:
        matches = re.findall(r"^\s*最终答案\s*[:：]\s*(.*?)\s*$", response, re.MULTILINE)
        lines = [line for line in response.splitlines() if line.strip()]
        valid = (
            len(matches) == 1
            and bool(matches[0].strip())
            and bool(lines)
            and re.fullmatch(r"\s*最终答案\s*[:：]\s*.+?\s*", lines[-1]) is not None
        )
        return response if valid else f"最终答案：{answer}"

    @staticmethod
    def _is_proof_like(problem: str) -> bool:
        normalized = problem.casefold()
        markers = (
            "证明", "推导", "分类讨论", "讨论所有", "充要条件", "必要性", "充分性",
            "prove", "show that", "derive", "classify", "if and only if",
        )
        return any(marker in normalized for marker in markers)

    def _reasoning_target_tokens(self, problem: str) -> int:
        return (
            self.config.proof_reasoning_target_tokens
            if self._is_proof_like(problem)
            else self.config.calculation_reasoning_target_tokens
        )

    @staticmethod
    def _reasoning_instruction(target_tokens: int) -> str:
        return (
            f"将推理目标控制在 {target_tokens} 输出 token 以内；只保留决定结论的步骤，"
            "省略重复验算、背景定义和无关展开。第一行必须先给最终答案。"
        )

    @staticmethod
    def _extract_first_line_answer(text: str) -> str:
        for line in (text or "").splitlines():
            if not line.strip():
                continue
            match = re.fullmatch(r"\s*最终答案\s*[:：]\s*(.+?)\s*", line)
            return match.group(1).strip() if match else ""
        return ""

    @staticmethod
    def _parse_verdict(verdict: str) -> bool | None:
        matches = re.findall(r"\bVERDICT\s*[:：]\s*([AB])\b", verdict, re.IGNORECASE)
        if matches:
            return matches[-1].upper() == "A"
        matches = re.findall(r"^\s*([AB])\s*$", verdict, re.IGNORECASE | re.MULTILINE)
        if matches:
            return matches[-1].upper() == "A"
        return None

    @staticmethod
    def _mark_truncation(
        result: ModelCallResult,
        status: str,
        original_answer_present: bool,
    ) -> None:
        budget = _ACTIVE_BUDGET.get()
        if budget is not None:
            budget.mark_truncation_handled(
                result.request_id,
                status=status,
                original_answer_present=original_answer_present,
            )

    @staticmethod
    def _contain_pending_truncations(budget: ExecutionBudget) -> None:
        for event in budget.truncation_events:
            if event.get("recovery_status") == "pending":
                budget.mark_truncation_handled(
                    event.get("request_id"),
                    status="quarantined",
                    original_answer_present=bool(event.get("original_answer_present")),
                )

    def _aggregate(self, scored: List[Candidate], trace: List[Dict]) -> Tuple[str, str]:
        """Prefer consistent deterministic passes, otherwise retain majority fallback."""
        if not scored:
            return "", ""
        with_ans = [
            candidate
            for candidate in scored
            if candidate.answer.raw and not candidate.metadata.get("truncated", False)
        ]
        if not with_ans:
            return "", ""
        deterministic_passes = [
            candidate
            for candidate in with_ans
            if any(
                evidence.source.startswith("deterministic:")
                and evidence.status == "pass"
                for evidence in candidate.verifications
            )
        ]
        if deterministic_passes:
            passed_keys = {candidate.answer.canonical for candidate in deterministic_passes}
            if len(passed_keys) == 1:
                selected = max(deterministic_passes, key=lambda item: item.confidence)
                trace.append({
                    "step": "deterministic_selection",
                    "content": {
                        "status": "selected",
                        "candidate_ids": [
                            candidate.metadata.get("candidate_id")
                            for candidate in deterministic_passes
                        ],
                        "evidence_sources": sorted({
                            evidence.source
                            for candidate in deterministic_passes
                            for evidence in candidate.verifications
                            if evidence.source.startswith("deterministic:")
                            and evidence.status == "pass"
                        }),
                    },
                })
                self._record_final_source(selected, trace)
                return selected.answer.normalized, selected.content
            trace.append({
                "step": "deterministic_selection",
                "content": {
                    "status": "conflict_fallback",
                    "candidate_ids": [
                        candidate.metadata.get("candidate_id")
                        for candidate in deterministic_passes
                    ],
                },
            })
        groups = {}
        for candidate in with_ans:
            groups.setdefault(candidate.answer.canonical, []).append(candidate)
        best_key = max(
            groups,
            key=lambda key: (
                len(groups[key]),
                max(candidate.confidence for candidate in groups[key]),
            ),
        )
        bg = groups[best_key]
        if len(bg) >= 2:
            trace.append({
                "step": "self_consistency",
                "content": f"答案 '{bg[0].answer.normalized}' 获得 {len(bg)} 票一致",
            })
            selected = max(bg, key=lambda item: item.confidence)
            self._record_final_source(selected, trace)
            return bg[0].answer.normalized, selected.content
        best = max(with_ans, key=lambda item: item.confidence)
        trace.append({
            "step": "select_final",
            "content": f"选最高分: {best.answer.normalized}",
        })
        self._record_final_source(best, trace)
        return best.answer.normalized, best.content

    @staticmethod
    def _record_final_source(candidate: Candidate, trace: List[Dict]) -> None:
        source = str(candidate.metadata.get("source") or candidate.strategy)
        budget = _ACTIVE_BUDGET.get()
        if budget is not None:
            budget.set_final_answer_source(source)
        trace.append({
            "step": "final_answer_source",
            "content": {
                "source": source,
                "candidate_id": candidate.metadata.get("candidate_id"),
                "reasoning_included": True,
            },
        })

    # 关键词→领域映射（v11：扩充至每领域15-20个关键词）
    _DOMAIN_KEYWORDS = {
        "抽象代数": ["群", "环", "域", "理想", "有限域", "伽罗瓦", "正规子群", "商群", "同态", "循环群",
                     "F_p", "F_q", "阶", "生成元", "拉格朗日", "共轭", "陪集", "自同构", "多项式环", "既约"],
        "数论": ["同余", "素数", "互素", "欧拉函数", "费马", "威尔逊", "中国剩余", "CRT", "模", "整除",
                 "φ", "gcd", "lcm", "因子", "质数", "最大公约数", "最小公倍数", "丢番图", "二次剩余", "原根"],
        "线性代数": ["矩阵", "行列式", "特征值", "特征向量", "秩", "线性空间", "向量空间", "特征多项式", "正交", "对角化",
                     "det", "tr", "逆矩阵", "转置", "线性无关", "基", "维数", "零空间", "奇异值", "Jordan"],
        "实分析": ["级数", "收敛", "勒贝格", "一致收敛", "ε-δ", "夹逼", "柯西序列", "完备",
                   "极限", "lim", "连续", "可导", "可积", "单调", "有界", "开集", "闭集", "稠密", "测度零"],
        "复分析": ["留数", "柯西", "解析函数", "极点", "整函数", "洛朗", "泰勒展开", "复变", "全纯",
                   "Res", "辐角", "虚部", "实部", "共轭复数", "解析延拓", "保角映射", "刘维尔", "最大模"],
        "微积分": ["导数", "积分", "极限", "偏导", "全微分", "链式法则", "分部积分", "换元", "反函数",
                   "不定积分", "定积分", "二重积分", "三重积分", "曲面积分", "曲线积分", "梯度", "散度", "旋度", "牛顿莱布尼茨"],
        "微分方程": ["常微分", "ODE", "齐次方程", "特解", "通解", "初值问题", "边界条件",
                     "微分方程", "dy", "y'", "y''", "特征方程", "积分因子", "变量分离", "伯努利", "皮卡"],
        "偏微分方程": ["偏微分", "PDE", "分离变量", "热传导", "波动方程", "拉普拉斯", "傅里叶级数", "边界条件",
                     "泊松方程", "椭圆型", "抛物型", "双曲型", "格林函数", "本征值", "本征函数", "齐次边界"],
        "泛函分析": ["Banach", "Hilbert", "赋范", "内积空间", "有界算子", "谱", "压缩映射", "不动点",
                     "完备化", "正交补", "Riesz", "开映射", "闭图像", "一致有界", "弱收敛", "紧算子"],
        "测度积分": ["测度", "Lebesgue", "可测", "σ代数", "反函数积分", "绝对连续", "Radon",
                     "积分变换", "反函数", "F(x)", "∫", "dx", "勒贝格积分", "简单函数", "控制收敛", "Fatou"],
        "几何": ["三角形", "圆", "面积", "体积", "角度", "切线", "相似", "全等", "正弦定理", "余弦定理",
                 "距离", "坐标", "向量", "法向量", "内切圆", "外接圆", "中线", "高线", "角平分线", "Heron"],
        "微分几何": ["曲率", "测地线", "第一基本形式", "第二基本形式", "Frenet", "挠率", "高斯曲率",
                     "平均曲率", "主曲率", "法曲率", "切向量", "法向量", "活动标架", "Gauss-Bonnet", "联络"],
        "拓扑": ["基本群", "同伦", "同调", "拓扑空间", "连通", "紧致", "开集", "闭集", "欧拉示性数",
                 "π₁", "H_n", "覆叠空间", "单连通", "道路连通", "商拓扑", "粘合", "Betti数", "流形"],
        "代数几何": ["仿射簇", "射影", "概形", "Bezout", "齐次坐标", "代数曲线", "除子",
                     "层", "上同调", "Riemann-Roch", "奇异点", "亏格", "线性等价", "非常丰", "有理映射"],
        "运筹学": ["线性规划", "对偶", "最优", "目标函数", "约束", "可行域", "KKT", "单纯形",
                   "最优化", "max", "min", "s.t.", "整数规划", "分支定界", "互补松弛", "影子价格", "运输问题"],
        "概率论": ["概率", "期望", "方差", "分布", "贝叶斯", "马尔可夫", "随机变量", "独立",
                   "E[X]", "D[X]", "概率密度", "分布函数", "条件概率", "全概率", "协方差", "相关系数", "大数定律", "中心极限"],
        "组合": ["排列", "组合", "容斥", "生成函数", "Catalan", "二项式", "计数",
                 "C(n", "P(n", "n!", "阶乘", "错排", "斯特林数", "划分", "鸽巢原理", "递推关系"],
        "离散数学": ["图论", "树", "顶点", "边", "哈密顿", "欧拉回路", "二分图", "递推", "布尔",
                     "图", "网络", "路径", "连通图", "度数", "邻接", "着色", "匹配", "割集", "前缀码"],
    }

    def _detect_domain(self, problem: str) -> str:
        """关键词匹配检测数学子领域，不花API调用。"""
        normalized_problem = problem.casefold()
        scores = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw.casefold() in normalized_problem)
            if score > 0:
                scores[domain] = score
        if scores:
            return max(scores, key=scores.get)
        return ""

    @staticmethod
    def _review_excerpt(text: str, limit: int = 3000) -> str:
        """保留候选开头与结尾，避免验证截断掉末尾最终答案。"""
        if len(text) <= limit:
            return text
        head = limit // 2
        tail = limit - head
        return f"{text[:head]}\n...[中间内容已截断]...\n{text[-tail:]}"

    def _quick_fallback(self, problem: str, trace: List[Dict]) -> str:
        try:
            resp = self._chat(POLICY_NO_TOOL_PROMPT,
                f"{problem}\n\n请直接给出最终答案，不要详细推导。单独一行按“最终答案：XXX”输出，XXX 只写答案本体。",
                temperature=0.0, max_tokens=self.config.fallback_max_tokens, thinking_mode=False)
            ans = self._extract_answer(resp)
            trace.append({"step": "fallback_result", "content": ans[:100]})
            if ans:
                return ans
            bare = resp.strip()
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

    @staticmethod
    def _extract_answer(text: str) -> str:
        """Extract only an explicit answer marker; never guess from a truncated tail."""
        if not text:
            return ""
        m = re.search(r"最终答案\s*[:：]\s*(.+?)(?:\n|$)", text)
        if m: return m.group(1).strip()
        m = re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
        if m: return m.group(1).strip()
        m = re.search(
            r"(?:候选)?答案(?:\s*(?:是|为)\s*|\s*[:：]\s*)"
            r"(.+?)(?:\n|。|$)",
            text,
        )
        if m: return m.group(1).strip()
        return ""

    @staticmethod
    def _normalize(answer: str) -> str:
        """Compatibility wrapper around the shared conservative normalizer."""
        return normalize_answer(answer)

    @staticmethod
    def _numeric(s: str) -> float | None:
        """Compatibility wrapper returning a float for older callers."""
        value = numeric_value(s)
        return float(value) if value is not None else None

    @staticmethod
    def _is_correct(verdict: str) -> bool:
        return ReasoningAgent._parse_verdict(verdict) is True
