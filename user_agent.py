"""数学推理智能体的竞赛接口与求解流水线。

接口约束：solve(problem, metadata) -> {"final_response": str, "trace": list}
架构事实源：ARCHITECTURE.md
"""
import json
import ast
from fractions import Fraction
import math
import re
import importlib.util
import sys
import types
from pathlib import Path
from uuid import uuid4
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# The source closure is fixed; neither cwd/sys.path nor preloaded bare modules
# determine its ownership. A fresh private namespace never replaces foreign state.
_FORMAL_SOURCE_FILES = ("agent_types.py", "budget.py", "domain_prompts.py", "answer_equivalence.py", "xh202627_corpus.py")
MAX_OUTPUT_TOKENS = 8192  # User-confirmed official single-request bound (2026-09-06).


def _load_formal_dependencies():
    root = Path(__file__).resolve().parent
    namespace = "xh202627_runtime_" + uuid4().hex
    while namespace in sys.modules:
        namespace = "xh202627_runtime_" + uuid4().hex
    package = types.ModuleType(namespace)
    package.__path__ = []
    sys.modules[namespace] = package
    modules = {}
    try:
        for filename in _FORMAL_SOURCE_FILES:
            stem = Path(filename).stem
            spec = importlib.util.spec_from_file_location(f"{namespace}.{stem}", root / filename)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            modules[stem] = module
        return modules
    except Exception:
        for name in list(sys.modules):
            if name == namespace or name.startswith(namespace + "."):
                del sys.modules[name]
        raise


_dependencies = _load_formal_dependencies()
Candidate = _dependencies["agent_types"].Candidate
Verification = _dependencies["agent_types"].Verification
build_answer = _dependencies["answer_equivalence"].build_answer
format_answer_for_output = _dependencies["answer_equivalence"].format_answer_for_output
normalize_answer = _dependencies["answer_equivalence"].normalize_answer
numeric_value = _dependencies["answer_equivalence"].numeric_value
BudgetExceeded = _dependencies["budget"].BudgetExceeded
ExecutionBudget = _dependencies["budget"].ExecutionBudget
get_domain_prompt = _dependencies["domain_prompts"].get_domain_prompt
text_only_domain_prompt = _dependencies["domain_prompts"].text_only_domain_prompt
detect_math_domain = _dependencies["domain_prompts"].detect_domain
load_public_corpus = _dependencies["xh202627_corpus"].load_corpus


_ACTIVE_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "active_problem_budget",
    default=None,
)

# R1-3 公开 trace 脱敏：原始内容统一省略，出口只保留白名单字段。
_TRACE_CLIP_LIMIT = 300


def _clip_for_trace(content, limit: int = _TRACE_CLIP_LIMIT) -> str:
    """公开事件不保留题面、模型、工具或异常原文；长度裁切不是脱敏。"""
    return "[内容已省略]"


def _clip_trace_item(item: Dict) -> Dict:
    """对嵌套 trace 项（如工具循环记录）应用统一脱敏。"""
    if not isinstance(item, dict):
        return {"step": "item", "content": _clip_for_trace(item)}
    return {"step": item.get("step", ""), "content": _clip_for_trace(item.get("content", ""))}


_PUBLIC_STEP = re.compile(
    r"(?:input_error|global_error|budget_exceeded|budget_summary|domain_detect|"
    r"truncated_fallback|generation_budget_exhausted|verify_budget_exhausted|reflect_budget_exhausted|"
    r"critic|critic_error|reflection|reflect_error|fallback_result|"
    r"self_consistency|select_final|deterministic_pass|deterministic_fail|deterministic_unknown|response_truncated|"
    r"(?:policy_plain|policy_tool|tool_solve|tool_error|truncated|truncated_isolated)_\d+|"
    r"(?:verify|verify_err|verify_unknown)_\d+_\d+)\Z"
)


def _public_trace(trace):
    """统一出口白名单：静态阶段标识 + 有界数值预算，不序列化不可信内容。"""
    result = []
    for item in trace[:256]:
        if type(item) is not dict:
            continue
        step = item.get("step")
        if type(step) is not str or not _PUBLIC_STEP.fullmatch(step):
            continue
        content = "[内容已省略]"
        if step == "budget_summary" and type(item.get("content")) is dict:
            raw = item["content"]
            numeric_keys = ("model_requests", "prompt_tokens", "completion_tokens",
                            "total_tokens", "tool_calls", "elapsed_ms")
            def numeric(value):
                return value if type(value) in (int, float) and 0 <= value <= 10**15 else 0
            content = {key: numeric(raw.get(key)) for key in numeric_keys}
            limits = raw.get("limits")
            if type(limits) is dict:
                content["limits"] = {key: numeric(limits.get(key)) for key in (
                    "model_requests", "total_tokens", "tool_calls", "timeout_seconds"
                )}
        result.append({"step": step, "content": content})
    return result


class _ModelText(str):
    """单次响应携带可选截断证据，不读 client 最近响应状态。"""
    def __new__(cls, text, finish_reason=None):
        value = super().__new__(cls, text)
        value.finish_reason = finish_reason
        return value


_FINAL_LABEL = r"(?:最终答案(?:是|为)?|答案(?:是|为)?)"
_FINAL_PREFIX = r"(?:^[ \t]*(?:#{1,6}[ \t]+)?(?:[0-9]{1,3}[.)、][ \t]+)?|(?<=[。.!?])[ \t]*)"
_FINAL_MARKER = re.compile(
    _FINAL_PREFIX + rf"(?:\*\*{_FINAL_LABEL}\*\*[ \t]*[:：]?|"
    rf"\*\*{_FINAL_LABEL}[ \t]*[:：]\*\*|__{_FINAL_LABEL}__[ \t]*[:：]?|"
    rf"__{_FINAL_LABEL}[ \t]*[:：]__|{_FINAL_LABEL}[ \t]*[:：]|{_FINAL_LABEL}[ \t]*$)"
    r"[ \t]*(?P<body>.*)$"
)
_FINAL_INTENT = re.compile(_FINAL_PREFIX + rf"(?:\*\*|__)?{_FINAL_LABEL}(?=[ \t:：*_]|$)")
_ANSWER_NUMBER = re.compile(r"^([0-9]{1,3})[.)、][ \t]+(.+)$")
_PRESENTATION_ONLY = re.compile(
    r"(?:Or maybe separate lines\? It says single line\.(?: So we can put them in one line\.)?|"
    r"Let's produce the final (?:answer|output)\.)"
)


def _response_text(response, metadata=None):
    reasons = [metadata.get("finish_reason")] if type(metadata) is dict else []
    if type(response) is dict:
        reasons.append(response.get("finish_reason"))
        response = response.get("content")
    reasons = [reason for reason in reasons if type(reason) is str and reason]
    # Either source can supply incompleteness; a conflicting stop never cancels it.
    reason = next((value for value in reasons if value != "stop"), reasons[0] if reasons else None)
    if response is None and reason == "length":
        response = ""
    if not isinstance(response, str):
        raise ValueError("invalid response type")
    # A bounded output contract prevents malformed clients from growing review/trace state.
    if len(response) > 100_000:
        return _ModelText(response[:100_000], "length")
    return _ModelText(response, reason if type(reason) is str else None)


# ==================== 提示词 ====================

POLICY_PROMPT = """你是数学推理智能体。解题并给出推理过程。

格式：
1. 解题思路
2. 关键推导步骤
3. 最终答案：XXX

最终答案行只写答案本体，不写“答案是”、解释或完整句子；若已有精确形式，不要只写小数近似值；能等价表示时优先使用 ASCII 记号（如 x^2、C1、Z），复杂公式可用 LaTeX。
"""

POLICY_NO_TOOL_PROMPT = """你是数学推理智能体。用纯推理解题。

格式：
1. 解题思路
2. 关键推导
3. 最终答案：XXX

最终答案行只写答案本体，不写“答案是”、解释或完整句子；若已有精确形式，不要只写小数近似值；能等价表示时优先使用 ASCII 记号（如 x^2、C1、Z），复杂公式可用 LaTeX。
"""

CONCISE_RECOVERY_PROMPT = """你是数学推理智能体。用纯推理完成补答。
只输出一行“最终答案：XXX”，不要输出解题思路、推导步骤或解释。
XXX 只写答案本体，不写“答案是”或完整句子；若已有精确形式，不要只写小数近似值；能等价表示时优先使用 ASCII 记号（如 x^2、C1、Z），复杂公式可用 LaTeX。
"""

VERIFIER_PROMPT = """你是数学答案验证器。请判断候选解答是否正确。

判断维度：1.推理逻辑 2.计算准确性 3.最终答案

只输出：VERDICT: A（正确）或 VERDICT: B（错误）"""

REASONED_VERIFIER_PROMPT = """你是数学答案验证器。先独立核算，再判断候选答案。
不要因为推导流畅或形式熟悉就判对。选取能决定对错的关键计算：积分对原函数求导；
方程把解代回并检查是否漏解；不等式核对区间端点与符号；级数核对通项及边界；
带参数问题先代入题目给定参数。反例足以判错，几个数值吻合不能证明恒等式。
只输出两行，不重复候选全文：
CHECK: 不超过200字的实际核算式或明确反例；无法核实时说明未确定之处
VERDICT: A 或 B 或 UNKNOWN
A表示已核实正确，B表示发现具体错误，UNKNOWN表示不能确认。最后一行只写一个结论。"""

CRITIC_PROMPT = """你是数学解题批评者。请找出候选解答中的错误或可改进之处。

检查：1.逻辑漏洞 2.计算错误 3.边界情况 4.答案格式

如果有错误，指出具体位置和正确做法。如果没有错误，输出：NO ERROR"""

REFLECTION_PROMPT = """你之前的解答可能有误。请根据反馈重新解答。

原题：{problem}
之前的解答：{prev_answer}
批评反馈：{feedback}

请修正错误，给出完整推理。最后单独一行写“最终答案：XXX”，XXX 只包含答案本体；若已有精确形式，不要只写小数近似值。"""


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
    # token（遵循 CHANGE-001 单变量纪律：与基线一致，仅改思维链开关）
    max_tokens: int = 8192
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    # 保留已核验的显式 False 协议；历史兼容字段不改变 _chat 的固定值。
    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    critic_thinking_mode: bool = False
    # 功能开关
    enable_tools: bool = True
    enable_critic: bool = True
    enable_reflection: bool = True
    enable_fallback: bool = True
    max_tool_rounds: int = 3
    tool_timeout_seconds: float = 5.0
    max_model_requests: int = 16
    max_total_tokens: int = 200_000
    max_tool_calls: int = 48
    problem_timeout_seconds: float = 600.0
    max_problem_chars: int = 20_000
    max_metadata_chars: int = 20_000


class ReasoningAgent:
    """领域路由、工具增强、验证、反思与聚合智能体。"""

    def __init__(self, client: Any, config: AgentConfig | None = None, *args,
                 local_adapter: Any = None, local_policy=None, **kwargs) -> None:
        """宽构造器（R1-2）：``local_adapter`` 为显式本地适配器（CLIENT-002）。

        适配器由本地入口（main.py/demo.py）显式传入，提供
        ``complete()`` 与 ``run_tools(...)``；正式平台不传，
        所有请求走四参数公开协议（含 thinking_mode=False），运行时不做任何能力探测。
        """
        self.config = config if type(config) is AgentConfig else AgentConfig()
        self.client = client
        self.local_adapter = local_adapter
        self.local_policy = local_policy if type(local_policy) is Q1Policy else deployment_policy()

    def _chat(self, system_prompt: str, user_content: str,
              temperature: float, max_tokens: int) -> str:
        """仅使用四参数公开协议（CLIENT-001），显式传 thinking_mode=False。"""
        if type(max_tokens) is not int or not 1 <= max_tokens <= MAX_OUTPUT_TOKENS:
            raise ValueError("invalid output token limit")
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        budget = _ACTIVE_BUDGET.get()
        if budget is not None:
            budget.consume_model_request()
        if self.local_adapter is not None:
            # 显式本地适配器路径（CLIENT-002）：response 与 metadata 绑定返回，
            # 内部经请求专属 meta_sink 记录 usage 供本地预算记账。
            completed = self.local_adapter.complete(
                messages=messages, temperature=temperature, max_tokens=max_tokens,
                thinking_mode=False,
            )
            if budget is not None:
                budget.record_response_meta(completed["metadata"])
            return _response_text(completed["response"], completed["metadata"])
        else:
            resp = self.client.chat(
                messages=messages, temperature=temperature, max_tokens=max_tokens,
                thinking_mode=False,
            )
        return _response_text(resp)

    def solve(self, problem: str, metadata: Dict) -> Dict:
        """覆盖预检至输出的公共失败边界；不可预期异常不触发额外模型调用。"""
        try:
            self._validate_config()
            result = self._solve_guarded(problem, metadata)
            final = result["final_response"]
            if type(final) is not str or not final.strip():
                raise ValueError("invalid final response")
            if final != "未解出" and (
                final.count("最终答案：") != 1
                or not final.splitlines()[-1].startswith("最终答案：")
                or not self._extract_answer(final)
            ):
                raise ValueError("invalid final answer")
            return {"final_response": final, "trace": _public_trace(result["trace"])}
        except Exception:
            return {"final_response": "未解出", "trace": [
                {"step": "global_error", "content": "[内容已省略]"}
            ]}

    def _validate_config(self):
        if any(type(value) is not bool for value in vars(self.local_policy).values()):
            raise ValueError("invalid experiment policy")
        defaults = AgentConfig()
        for name, default in vars(defaults).items():
            value = getattr(self.config, name)
            if type(default) is bool:
                valid = type(value) is bool
            elif type(default) is int:
                minimum = 0 if name in ("tool_candidates", "plain_candidates") else 1
                maximum = MAX_OUTPUT_TOKENS if name in (
                    "max_tokens", "verifier_max_tokens", "critic_max_tokens", "fallback_max_tokens"
                ) else 10**9
                valid = type(value) is int and minimum <= value <= maximum
            else:
                valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
                if "timeout" in name:
                    valid = valid and value > 0
            if not valid:
                raise ValueError("invalid config")
        if self.config.tool_candidates + self.config.plain_candidates == 0:
            raise ValueError("no candidates configured")

    def _solve_guarded(self, problem: str, metadata: Dict) -> Dict:
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
        except (TypeError, ValueError, RecursionError):
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
            max_total_tokens=self.config.max_total_tokens,
            max_tool_calls=self.config.max_tool_calls,
            timeout_seconds=self.config.problem_timeout_seconds,
        )
        budget_token = _ACTIVE_BUDGET.set(budget)
        try:
            try:
                result = self._solve_impl(problem, trace)
            except BudgetExceeded as e:
                trace.append({"step": "budget_exceeded", "content": _clip_for_trace(str(e))})
                result = {"final_response": "未解出", "trace": trace}
            except Exception as e:
                trace.append({
                    "step": "global_error",
                    "content": _clip_for_trace(f"{type(e).__name__}: {str(e)}"),
                })
                result = {"final_response": "未解出", "trace": trace}
            trace.append({"step": "budget_summary", "content": budget.snapshot()})
            return result
        finally:
            _ACTIVE_BUDGET.reset(budget_token)

    def _solve_impl(self, problem: str, trace: List[Dict]) -> Dict:
        # 阶段1：关键词检测领域
        domain_name = self._detect_domain(problem)
        domain_prompt = get_domain_prompt(domain_name)
        if self.local_policy.compact_routing:
            domain_prompt = POLICY_NO_TOOL_PROMPT + "\n" + _ROUTE_HINTS.get(domain_name, "核对所求对象、定义域和边界条件。")
        if domain_name:
            trace.append({"step": "domain_detect", "content": f"关键词识别: {domain_name}"})

        # 阶段2：多候选生成（全部温度0.6，v13配置）
        candidates, gen_trace = self._generate_candidates(problem, domain_prompt)
        trace.extend(gen_trace)

        # 截断兜底（R1-5：疑似截断的候选视为无答案）
        if not candidates or all(
            self._is_likely_truncated(c) or not self._extract_answer(c)
            for c in candidates
        ):
            trace.append({"step": "truncated_fallback", "content": "所有候选被截断"})
            if self.config.enable_fallback:
                fb = self._quick_fallback(problem, trace)
                if fb:
                    if self.local_policy.deterministic or self.local_policy.bounded_math:
                        if self._task_check(problem, str(fb)) == "fail":
                            trace.append({"step": "deterministic_fail", "content": "[内容已省略]"})
                            return {"final_response": "未解出", "trace": trace}
                    return {"final_response": self._build_response("", fb), "trace": trace}
            return {"final_response": "未解出", "trace": trace}

        # 阶段3：验证投票
        scored: List[Candidate] = []
        try:
            for cid, candidate in enumerate(candidates):
                answer = self._answer_for_aggregation(candidate, cid, trace)
                if answer.raw:
                    confidence, vt, verifications = self._verify(problem, candidate, cid)
                else:
                    confidence, vt, verifications = 0.0, [], []
                strategy = (
                    "tool"
                    if self.config.enable_tools and cid < self.config.tool_candidates
                    else "plain"
                )
                scored.append(Candidate(
                    content=candidate,
                    strategy=strategy,
                    confidence=confidence + (0.3 if answer.raw else -0.5),
                    answer=answer,
                    raw_confidence=confidence,
                    verifications=verifications,
                ))
                trace.extend(vt)
        except BudgetExceeded as e:
            # R1-4 生命周期兜底：验证阶段预算耗尽时保留已有候选，
            # 剩余候选以无票状态进入聚合（聚合本身不消耗预算）。
            trace.append({"step": "verify_budget_exhausted", "content": _clip_for_trace(str(e))})
            for cid, candidate in enumerate(candidates[len(scored):], start=len(scored)):
                answer = self._answer_for_aggregation(candidate, cid, trace)
                strategy = (
                    "tool"
                    if self.config.enable_tools and len(scored) < self.config.tool_candidates
                    else "plain"
                )
                scored.append(Candidate(
                    content=candidate,
                    strategy=strategy,
                    confidence=(0.3 if answer.raw else -0.5),
                    answer=answer,
                    raw_confidence=0.0,
                    metadata={"verification_skipped": "budget"},
                ))

        # 阶段4：Critic + 反思（仅低置信度触发）
        try:
            if self.config.enable_critic and scored:
                best = max(scored, key=lambda item: item.confidence)
                has_failure = any(v.status == "fail" for v in best.verifications)
                if best.raw_confidence < 0.5 and best.answer.raw and has_failure:
                    criticism = self._critic(problem, best.content, trace)
                    if criticism and "NO ERROR" not in criticism.upper() and self.config.enable_reflection:
                        refined = self._reflect(problem, best.content, criticism, trace)
                        ra = self._answer_for_aggregation(refined, len(candidates), trace)
                        if ra.raw:
                            rc, rv, verifications = self._verify(
                                problem, refined, len(candidates)
                            )
                            scored.append(Candidate(
                                content=refined,
                                strategy="reflection",
                                confidence=rc + (0.3 if ra.raw else -0.5),
                                answer=ra,
                                raw_confidence=rc,
                                verifications=verifications,
                                metadata={"temperature": self.config.reflection_temperature},
                            ))
                            trace.extend(rv)
        except BudgetExceeded as e:
            # R1-4：反思阶段预算耗尽时跳过反思，直接聚合已有候选
            trace.append({"step": "reflect_budget_exhausted", "content": _clip_for_trace(str(e))})

        # 阶段6：加权聚合
        if self.local_policy.deterministic or self.local_policy.bounded_math:
            before_exact = scored
            scored = self._apply_exact_evidence(problem, scored, trace)
            if (not scored and self.local_policy.evidence_selection and self.config.enable_reflection
                    and any(item.answer.raw for item in before_exact)):
                # Every eligible answer has a whole-task mathematical refutation.
                # Spend at most one bounded correction, never recycle a refuted answer.
                previous = max((item for item in before_exact if item.answer.raw),
                               key=lambda item: item.confidence)
                try:
                    refined = self._reflect(problem, previous.content,
                        "独立精确计算已证明候选最终答案不满足原题。请从原题重新计算，"
                        "逐项检查系数与符号；若为不定积分，对最终原函数求导并化简，"
                        "确认恰好等于被积函数且保留积分常数。不要仅重复原结论。", trace)
                    answer = self._answer_for_aggregation(refined, len(candidates) + 1, trace)
                    if answer.raw:
                        repaired = Candidate(content=refined, strategy="reflection", answer=answer,
                            confidence=0.3, raw_confidence=0.0, verifications=[])
                        scored = self._apply_exact_evidence(problem, [repaired], trace)
                except BudgetExceeded:
                    trace.append({"step": "reflect_budget_exhausted", "content": "[内容已省略]"})
        final_answer, best_content = self._aggregate(scored, trace)
        if not final_answer:
            return {"final_response": "未解出", "trace": trace}
        final_response = self._build_response(best_content, final_answer)

        return {"final_response": final_response or final_answer or "未解出", "trace": trace}

    def _build_response(self, content: str, answer: str) -> str:
        if not self._valid_answer_body(answer):
            return "未解出"
        formatted_answer = format_answer_for_output(answer)
        if not formatted_answer:
            return "未解出"
        if not content:
            return f"最终答案：{formatted_answer}"
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
            return f"最终答案：{formatted_answer}"
        return f"{body}\n最终答案：{formatted_answer}"

    def _generate_candidates(self, problem: str, domain_prompt: str) -> Tuple[List[str], List[Dict]]:
        """v17：回退v13——全部温度0.6，简单候选生成。"""
        candidates, trace = [], []
        try:
            for i in range(self.config.tool_candidates):
                if self.config.enable_tools:
                    cand, tt = self._solve_tools(problem, i, domain_prompt)
                else:
                    cand = self._solve_plain(problem, domain_prompt)
                    tt = [{"step": f"policy_tool_{i}", "content": _clip_for_trace(cand)}]
                candidates.append(cand)
                trace.extend(tt)
            for i in range(self.config.plain_candidates):
                if self.local_policy.diverse_candidates:
                    cand = self._chat(self._plain_generation_prompt(domain_prompt),
                        f"{self._generation_problem(problem, reference=i == 0)}\n\n请用独立方法复核后给出完整解答。",
                        temperature=min(1.0, self.config.policy_temperature + 0.2),
                        max_tokens=self.config.max_tokens)
                else:
                    if self.local_policy.corpus_retrieval and i == 0:
                        cand = self._solve_plain(problem, domain_prompt, reference=True)
                    else:
                        cand = self._solve_plain(problem, domain_prompt)
                if self.local_policy.recover_plain and self.config.enable_fallback and not self._extract_answer(cand):
                    trace.append({"step": f"truncated_{i}", "content": "[内容已省略]"})
                    recovered = self._quick_fallback(problem, trace)
                    cand = self._candidate_from_recovery(recovered) or cand
                candidates.append(cand)
                trace.append({"step": f"policy_plain_{i}", "content": _clip_for_trace(cand)})
        except BudgetExceeded:
            # Keep completed work. The shared qualification/aggregation path still
            # rejects incomplete candidates, and the exhausted budget forbids more calls.
            trace.append({"step": "generation_budget_exhausted", "content": "[内容已省略]"})
        return [c for c in candidates if c], trace

    def _solve_tools(self, problem: str, cid: int, domain_prompt: str) -> Tuple[str, List[Dict]]:
        try:
            messages = [
                {"role": "system", "content": domain_prompt or POLICY_PROMPT},
                {"role": "user", "content": f"{self._generation_problem(problem)}\n\n请调用工具验证关键计算。候选编号：{cid}"},
            ]
            if self.local_adapter is None:
                if self.local_policy.tool_aware_prompts:
                    messages = [
                        {"role": "system", "content": self._plain_generation_prompt(domain_prompt)},
                        {"role": "user", "content": f"{self._generation_problem(problem)}\n\n请用数学推导复核关键计算，直接给出完整解答。候选编号：{cid}"},
                    ]
                # The public text-only path has no dependency on local tools/client.
                response = self._chat(messages[0]["content"], messages[1]["content"],
                    temperature=self.config.policy_temperature, max_tokens=self.config.max_tokens)
                tt = []
            else:
                text, tt, metadata = self.local_adapter.run_tools(
                    messages=messages, max_rounds=self.config.max_tool_rounds,
                    temperature=self.config.policy_temperature, max_tokens=self.config.max_tokens,
                    tool_timeout_seconds=self.config.tool_timeout_seconds,
                    budget=_ACTIVE_BUDGET.get(),
                )
                response = _response_text(text, metadata)
            if self.config.enable_fallback and self._is_likely_truncated(response):
                trace = [{"step": f"tool_solve_{cid}", "content": [_clip_trace_item(item) for item in tt]}]
                trace.append({"step": f"truncated_{cid}", "content": "截断兜底"})
                fb = self._quick_fallback(problem, trace)
                if fb:
                    response = self._candidate_from_recovery(fb)
                trace.append({"step": f"policy_tool_{cid}", "content": _clip_for_trace(response)})
                return response, trace
            trace = [{"step": f"tool_solve_{cid}", "content": [_clip_trace_item(item) for item in tt]}]
            trace.append({"step": f"policy_tool_{cid}", "content": _clip_for_trace(response)})
            return response, trace
        except BudgetExceeded:
            raise
        except Exception:
            # Transport/contract failures do not authorize a blind retry as a plain candidate.
            raise

    def _plain_generation_prompt(self, domain_prompt: str) -> str:
        prompt = domain_prompt or POLICY_NO_TOOL_PROMPT
        return text_only_domain_prompt(prompt) if self.local_policy.tool_aware_prompts else prompt

    def _generation_problem(self, problem: str, *, reference: bool = False) -> str:
        text = problem
        if self.local_policy.condition_checks:
            text += ("\n\n解题检查：先确认所求对象、数域、参数范围、定义域和边界；"
                     "不要补造题目未给的条件。涉及全部解、积分常数、绝对值、重数时逐项核对。"
                     "在最终答案中保留必要条件，并检查结论与推导一致；给出完整解答。")
        if reference and self.local_policy.corpus_retrieval:
            try:
                # Per-call read-only resource; no cross-question state or hidden inputs.
                text += load_public_corpus().context(problem)
            except (OSError, ValueError, TypeError, KeyError):
                # An unavailable/corrupted optional corpus cannot prevent normal solving.
                pass
        return text

    def _solve_plain(self, problem: str, domain_prompt: str, *, reference: bool = False) -> str:
        try:
            prefix = self._plain_generation_prompt(domain_prompt)
            return self._chat(prefix, f"{self._generation_problem(problem, reference=reference)}\n\n请给出完整解答。",
                              temperature=self.config.policy_temperature,
                              max_tokens=self.config.max_tokens)
        except BudgetExceeded:
            raise
        except Exception:
            raise

    def _verify(
        self,
        problem: str,
        candidate: str,
        cid: int,
    ) -> Tuple[float, List[Dict], List[Verification]]:
        votes, trace, verifications = [], [], []
        review_text = self._review_excerpt(candidate)
        for vid in range(self.config.verifier_voting_times):
            try:
                instruction = ("判断是否正确。先输出一行 CHECK: 实际核算，再单独输出 VERDICT: A / B / UNKNOWN 中一个结论。"
                               if self.local_policy.reasoned_verifier else "判断是否正确。只输出：VERDICT: A 或 VERDICT: B")
                verdict = self._chat(REASONED_VERIFIER_PROMPT if self.local_policy.reasoned_verifier else VERIFIER_PROMPT,
                    f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n{instruction}",
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens)
                status = (self._reasoned_verdict_status(verdict) if self.local_policy.reasoned_verifier
                          else self._verdict_status(verdict, allow_short_labels=not self.local_policy.calibrated_verifier))
                if self._response_cutoff(verdict) or status == "unknown":
                    if self._response_cutoff(verdict):
                        trace.append({"step": "response_truncated", "content": "[内容已省略]"})
                    verifications.append(Verification(source="model", status="unknown",
                        confidence=0.0, detail="incomplete response"))
                    trace.append({"step": f"verify_unknown_{cid}_{vid}", "content": "incomplete"})
                    continue
                passed = status == "pass"
                votes.append(passed)
                verifications.append(Verification(
                    source="model",
                    status="pass" if passed else "fail",
                    confidence=1.0 if passed else 0.0,
                    detail=verdict[:200],
                ))
                trace.append({"step": f"verify_{cid}_{vid}", "content": _clip_for_trace(verdict)})
            except BudgetExceeded:
                raise
            except Exception:
                raise
        return (sum(votes) / len(votes) if votes else 0.0), trace, verifications

    def _critic(self, problem: str, candidate: str, trace: List[Dict]) -> str:
        try:
            review_text = self._review_excerpt(candidate)
            criticism = self._chat(CRITIC_PROMPT,
                f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n请找出错误或改进点。",
                temperature=self.config.critic_temperature,
                max_tokens=self.config.critic_max_tokens)
            if self._response_cutoff(criticism) or len(criticism) >= 3000:
                return ""
            trace.append({"step": "critic", "content": _clip_for_trace(criticism)})
            return criticism
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "critic_error", "content": _clip_for_trace(str(e))})
            return ""

    def _reflect(self, problem: str, prev: str, feedback: str, trace: List[Dict]) -> str:
        try:
            prompt = REFLECTION_PROMPT.format(
                problem=problem,
                prev_answer=self._review_excerpt(prev, limit=2000),
                feedback=feedback[:500],
            )
            resp = self._chat(POLICY_PROMPT, prompt,
                              temperature=self.config.reflection_temperature,
                              max_tokens=self.config.max_tokens)
            trace.append({"step": "reflection", "content": _clip_for_trace(resp)})
            return resp
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "reflect_error", "content": _clip_for_trace(str(e))})
            return ""

    def _aggregate(self, scored: List[Candidate], trace: List[Dict]) -> Tuple[str, str]:
        """v17：回退v13——简单多数投票。"""
        if not scored:
            return "", ""
        with_ans = [candidate for candidate in scored if candidate.answer.raw]
        if not with_ans:
            return "", ""
        if self.local_policy.evidence_selection:
            # A repeated answer rejected by every completed verifier must not
            # defeat a different answer with positive evidence merely by count.
            # Unknown-only candidates remain eligible; model votes are not proofs.
            def model_supported(candidate):
                return any(v.source == "model" and v.status == "pass"
                           for v in candidate.verifications)

            def model_rejected(candidate):
                votes = [v.status for v in candidate.verifications
                         if v.source == "model" and v.status in ("pass", "fail")]
                return bool(votes) and all(v == "fail" for v in votes)

            if any(model_supported(candidate) for candidate in with_ans):
                evidence_groups = {}
                for candidate in with_ans:
                    evidence_groups.setdefault(candidate.answer.canonical, []).append(candidate)
                rejected_keys = {key for key, group in evidence_groups.items()
                                 if all(model_rejected(candidate) for candidate in group)}
                with_ans = [candidate for candidate in with_ans
                            if candidate.answer.canonical not in rejected_keys]
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
            return bg[0].answer.normalized, selected.content
        best = max(with_ans, key=lambda item: item.confidence)
        trace.append({
            "step": "select_final",
            "content": f"选最高分: {best.answer.normalized}",
        })
        return best.answer.normalized, best.content

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
        """Bounded bilingual mathematical routing; no model request."""
        return detect_math_domain(problem, self._DOMAIN_KEYWORDS)

    @staticmethod
    def _review_excerpt(text: str, limit: int = 3000) -> str:
        """保留候选开头与结尾，避免验证截断掉末尾最终答案。"""
        if len(text) <= limit:
            return text
        head = limit // 2
        tail = limit - head
        return f"{text[:head]}\n...[中间内容已截断]...\n{text[-tail:]}"

    def _is_likely_truncated(self, text: str) -> bool:
        """缺少完整答案或明确截断的响应不具备候选资格。"""
        return bool(text) and (self._response_cutoff(text) or not self._extract_answer(text))

    @staticmethod
    def _response_cutoff(text):
        return isinstance(text, _ModelText) and text.finish_reason not in (None, "", "stop")

    def _answer_for_aggregation(self, candidate: str, cid: int, trace: List[Dict]):
        """R1-5：疑似截断的候选不提供可聚合答案，残句不得进入聚合。"""
        if self._is_likely_truncated(candidate):
            trace.append({
                "step": f"truncated_isolated_{cid}",
                "content": "长响应缺少答案标记，已隔离残句",
            })
            return build_answer("")
        return build_answer(self._extract_answer(candidate))

    def _quick_fallback(self, problem: str, trace: List[Dict]) -> str:
        try:
            system_prompt = CONCISE_RECOVERY_PROMPT if self.local_policy.concise_recovery else POLICY_NO_TOOL_PROMPT
            resp = self._chat(system_prompt,
                f"{problem}\n\n请直接给出最终答案，不要详细推导。单独一行按“最终答案：XXX”输出，XXX 只写答案本体。",
                temperature=0.0, max_tokens=self.config.fallback_max_tokens)
            ans = self._extract_answer(resp)
            trace.append({"step": "fallback_result", "content": _clip_for_trace(ans)})
            if self._response_cutoff(resp) or not ans:
                return ""
            return _ModelText(ans, resp.finish_reason if isinstance(resp, _ModelText) else None)
        except BudgetExceeded:
            raise
        except Exception:
            return ""

    @staticmethod
    def _candidate_from_recovery(answer):
        """Restore the validated answer marker without inventing completion evidence."""
        if ReasoningAgent._response_cutoff(answer) or not ReasoningAgent._valid_answer_body(answer):
            return ""
        reason = answer.finish_reason if isinstance(answer, _ModelText) else None
        return _ModelText("最终答案：" + str(answer), reason)

    @staticmethod
    def _extract_answer(text: str) -> str:
        """Read one bounded explicit answer block; never salvage an earlier incomplete result."""
        if (not isinstance(text, str) or not text or len(text) > 100_000
                or ReasoningAgent._response_cutoff(text)):
            return ""
        lines = text.splitlines()
        markers, visible, fence = [], [], None
        for index, line in enumerate(lines):
            boundary = re.fullmatch(r"[ \t]*(`{3,32}|~{3,32})([A-Za-z0-9_+-]{0,32})[ \t]*", line)
            if boundary:
                delimiter, language = boundary.groups()
                if fence is None:
                    fence = delimiter
                elif not language and delimiter[0] == fence[0] and len(delimiter) >= len(fence):
                    fence = None
                continue
            if fence is None:
                visible.append(line)
                for intent in _FINAL_INTENT.finditer(line):
                    markers.append((index, _FINAL_MARKER.match(line, intent.start())))
        if markers:
            index, marker = markers[-1]
            if marker is None:
                return ""
            return ReasoningAgent._answer_block(marker.group("body"), lines[index+1:],
                closing_tag=any(line.strip() == "<final_answer>" for line in lines[:index]))
        boxed = re.findall(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", "\n".join(visible))
        if boxed:
            answer = boxed[-1].strip()
        elif re.fullmatch(r"[+\-]?\d+(?:\.\d+)?(?:/\d+)?", text.strip()):
            answer = text.strip()
        else:
            return ""
        return answer if ReasoningAgent._valid_answer_body(answer) else ""

    @staticmethod
    def _answer_block(first, remainder, *, closing_tag=False):
        """Support flat numbered parts or individually labelled equations, not arbitrary prose."""
        parts = [first.strip()] if first.strip() else []
        size = len(first.strip())
        separated = False
        for offset, line in enumerate(remainder):
            if re.match(r"^[ \t]*#{1,6}[ \t]+\S", line):
                break
            value = line.strip()
            if closing_tag and value == "</final_answer>":
                break
            if not value:
                separated = True
                continue
            # Preserve the existing single-line contract when a later paragraph
            # comments on presentation. Numbered/equation continuations still join.
            if (separated and len(parts) == 1 and first.strip() and not _ANSWER_NUMBER.match(first.strip())
                    and all(_PRESENTATION_ONLY.fullmatch(tail.strip()) for tail in remainder[offset:] if tail.strip())):
                break
            size += len(value) + 2
            if size > 2048 or len(parts) >= 128:
                return ""
            parts.append(value)
            separated = False
        if parts and parts[0] in (r"\[", "$$"):
            closing = r"\]" if parts[0] == r"\[" else "$$"
            if closing not in parts[1:]:
                return ""
            answer = " ".join(parts)
            return answer if ReasoningAgent._valid_answer_body(answer) else ""
        if not parts or any(not ReasoningAgent._valid_answer_body(part) for part in parts):
            return ""
        if len(parts) > 1:
            numbered = [_ANSWER_NUMBER.fullmatch(part) for part in parts]
            if numbered[0]:
                if any(not match or int(match.group(1)) != number
                       or not ReasoningAgent._valid_answer_body(match.group(2))
                       for number, match in enumerate(numbered, 1)):
                    return ""
            elif not all(re.match(r"^(?:\$|\\\()?[^\s=]{1,100}[ \t]*=", part) for part in parts):
                return ""
        answer = "; ".join(parts)
        return answer if ReasoningAgent._valid_answer_body(answer) else ""

    @staticmethod
    def _valid_answer_body(answer):
        if not isinstance(answer, str) or not answer.strip() or len(answer) > 2048:
            return False
        value = answer.strip()
        # The established formatter accepts mixed inline wrappers such as \(x$.
        # Display blocks have explicit boundaries and must still close in order.
        math_groups = 0
        for token in re.findall(r"(?<!\\)\\([\[\]])", value):
            math_groups += 1 if token == "[" else -1
            if math_groups < 0:
                return False
        if math_groups or value.count("$$") % 2:
            return False
        if value in ("未解出", r"\[", r"\]", r"\(", r"\)", "$", "$$", "**", "__") or re.search(
            r"因此|所以|还需要|尚未|未完成|推导|详细步骤|答案是|答案为|"
            r"(?:we (?:need|must)|therefore|unfinished)|[=+*/^\\,，:：]$", value, re.I
        ):
            return False
        # Reject unfinished TeX/groups while allowing mathematical interval notation.
        depth = 0
        for char in value:
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth < 0:
                    return False
        return depth == 0

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
    def _verdict_status(verdict, *, allow_short_labels=False):
        if not isinstance(verdict, str) or ReasoningAgent._response_cutoff(verdict):
            return "unknown"
        match = re.fullmatch(r"\s*VERDICT\s*[:：]\s*([AB])\s*", verdict, re.I)
        if match:
            return "pass" if match[1].upper() == "A" else "fail"
        if allow_short_labels:
            label = verdict.strip().upper()
            if label in ("A", "CORRECT"):
                return "pass"
            if label in ("B", "INCORRECT"):
                return "fail"
        return "unknown"

    @staticmethod
    def _reasoned_verdict_status(verdict):
        if not isinstance(verdict, str) or ReasoningAgent._response_cutoff(verdict) or len(verdict) > 1200:
            return "unknown"
        # Parse complete lines so whitespace cannot join a broken label or
        # silently accept a three-line/empty evidence response.
        # Blank separators are presentation only; broken nonempty labels are
        # still separate lines and cannot be joined into a valid verdict.
        lines = [line for line in verdict.strip().splitlines() if line.strip()]
        if len(lines) not in (1, 2):
            return "unknown"
        if len(lines) == 2:
            check = re.fullmatch(r"CHECK[ \t]*[:：][ \t]*([^\r\n]{1,1000})", lines[0], re.I)
            if not check or not check[1].strip() or re.search(r"\bVERDICT\b", check[1], re.I):
                return "unknown"
        match = re.fullmatch(r"[ \t]*VERDICT[ \t]*[:：][ \t]*(A|B|UNKNOWN)[ \t]*", lines[-1], re.I)
        return {"A": "pass", "B": "fail", "UNKNOWN": "unknown"}[match[1].upper()] if match else "unknown"

    def _apply_exact_evidence(self, problem, candidates, trace):
        passed, remaining = [], []
        for candidate in candidates:
            if not candidate.answer.raw:
                continue
            status = self._task_check(problem, candidate.answer.raw)
            trace.append({"step": "deterministic_" + status, "content": "[内容已省略]"})
            candidate.verifications.append(Verification("deterministic:complete_problem", status,
                1.0 if status == "pass" else 0.0, "bounded exact arithmetic"))
            if status == "pass":
                passed.append(candidate)
            elif status == "unknown":
                remaining.append(candidate)
        # A complete exact problem proof outranks model votes. Unparsed tasks never change order.
        return passed if passed else remaining

    def _task_check(self, problem, answer):
        if self.local_policy.bounded_math:
            return _bounded_task_check(problem, answer)
        return _complete_task_check(problem, answer)

    @staticmethod
    def _is_correct(verdict: str) -> bool:
        m = re.findall(r"\bVERDICT\s*[:：]\s*([AB])", verdict, re.IGNORECASE)
        if m: return m[-1].upper() == "A"
        m = re.findall(r"^\s*([AB])\s*$", verdict, re.IGNORECASE | re.MULTILINE)
        if m: return m[-1].upper() == "A"
        words = re.findall(r"\b[A-Z]+\b", verdict.upper())
        return "CORRECT" in words and "INCORRECT" not in words


@dataclass(frozen=True)
class Q1Policy:
    """Explicit all-off experiment configuration; deployment has a named preset."""
    recover_plain: bool = False
    deterministic: bool = False
    compact_routing: bool = False
    calibrated_verifier: bool = False
    diverse_candidates: bool = False
    tool_aware_prompts: bool = False
    concise_recovery: bool = False
    corpus_retrieval: bool = False
    bounded_math: bool = False
    condition_checks: bool = False
    evidence_selection: bool = False
    reasoned_verifier: bool = False


def deployment_policy() -> Q1Policy:
    """2026-09-10 combined candidate, used by the ordinary injected entrypoint.

    Keep Q1Policy() all-off so existing explicitly frozen experiments never
    silently change when deployment is promoted. No environment/metadata toggle.
    """
    return Q1Policy(concise_recovery=True, bounded_math=True, evidence_selection=True,
                    reasoned_verifier=True)


_ROUTE_HINTS = {
    "数学分析": "先确认极限或收敛的定义与适用条件，再核对端点。",
    "线性代数": "核对矩阵维度；特征值须包含重数，解空间须给全。",
    "概率论": "明确样本空间与独立性，检查归一化和参数范围。",
    "数论": "区分整数与实数范围，核对整除、模数及全部解。",
    "组合": "明确计数对象，检查重复计数和遗漏。",
}


def _exact_answer_value(text):
    if type(text) is not str or len(text) > 256:
        return None
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:/\d+)?", text.strip()):
        return None
    try:
        return Fraction(text.strip())
    except (ValueError, ZeroDivisionError):
        return None


def _exact_problem_value(problem):
    """Only full, bounded arithmetic/binomial/mod-power tasks. No semantic guesses."""
    if type(problem) is not str or len(problem) > 300:
        return None
    text = problem.strip().rstrip("。？?")
    modular = re.fullmatch(r"求整数\s*([+-]?\d{1,9})\s*\^\s*(\d{1,6})\s*除以\s*(\d{1,9})\s*的余数", text)
    if modular:
        base, exponent, modulus = map(int, modular.groups())
        return Fraction(pow(base, exponent, modulus)) if modulus > 0 else None
    combo = re.fullmatch(r"(?:计算|求)\s*C\((\d{1,4}),\s*(\d{1,4})\)", text)
    if combo:
        n, k = map(int, combo.groups())
        return Fraction(math.comb(n, k)) if 0 <= k <= n <= 1000 else None
    match = re.fullmatch(r"(?:计算|求值|Calculate|Evaluate)\s*[:：]?\s*([0-9+*/(). ^\-]+)", text, re.I)
    if not match or len(match[1]) > 128:
        return None
    try:
        tree = ast.parse(match[1].strip().replace("^", "**"), mode="eval")
        if sum(1 for _ in ast.walk(tree)) > 64:
            return None
        def evaluate(node):
            if isinstance(node, ast.Constant) and type(node.value) is int:
                value = Fraction(node.value)
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            elif isinstance(node, ast.BinOp):
                left, right = evaluate(node.left), evaluate(node.right)
                if isinstance(node.op, ast.Add):
                    value = left + right
                elif isinstance(node.op, ast.Sub):
                    value = left - right
                elif isinstance(node.op, ast.Mult):
                    value = left * right
                elif isinstance(node.op, ast.Div):
                    value = left / right
                elif isinstance(node.op, ast.Pow) and right.denominator == 1 and 0 <= right <= 100:
                    value = left ** int(right)
                else:
                    raise ValueError("unsupported arithmetic")
            else:
                raise ValueError("unsupported syntax")
            if max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096:
                raise ValueError("arithmetic size exceeded")
            return value
        return evaluate(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def _bounded_polynomial(text):
    """Rational polynomials only; fixed degree, AST, text and coefficient bounds."""
    if type(text) is not str or len(text) > 128 or not re.fullmatch(r"[x0-9+*/(). ^\s-]+", text):
        raise ValueError("polynomial size")
    tree = ast.parse(text.strip().replace("^", "**"), mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 64:
        raise ValueError("polynomial nodes")
    def checked(poly):
        if max(poly, default=0) > 12 or any(max(v.numerator.bit_length(), v.denominator.bit_length()) > 1024 for v in poly.values()):
            raise ValueError("polynomial resources")
        return {k: v for k,v in poly.items() if v}
    def multiply(left, right):
        result = {}
        for a,b in left.items():
            for c,d in right.items():
                result[a+c] = result.get(a+c, Fraction(0)) + b*d
        return checked(result)
    def visit(node):
        if isinstance(node, ast.Name) and node.id == "x":
            return {1: Fraction(1)}
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return checked({0: Fraction(node.value)})
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return {k: v*(-1 if isinstance(node.op, ast.USub) else 1) for k,v in visit(node.operand).items()}
        if not isinstance(node, ast.BinOp):
            raise ValueError("polynomial grammar")
        left, right = visit(node.left), visit(node.right)
        if isinstance(node.op, (ast.Add, ast.Sub)):
            result = dict(left)
            for k,v in right.items():
                result[k] = result.get(k, Fraction(0)) + v*(-1 if isinstance(node.op, ast.Sub) else 1)
            return checked(result)
        if isinstance(node.op, ast.Mult):
            return multiply(left, right)
        if isinstance(node.op, ast.Div) and set(right) == {0}:
            return checked({k: v/right[0] for k,v in left.items()})
        if isinstance(node.op, ast.Pow) and set(right).issubset({0}):
            exponent = right.get(0, Fraction(0))
            if exponent.denominator != 1 or not 0 <= exponent <= 12:
                raise ValueError("polynomial exponent")
            result = {0: Fraction(1)}
            for _ in range(int(exponent)):
                result = multiply(result, left)
            return result
        raise ValueError("polynomial operator")
    return checked(visit(tree.body))


def _complete_task_check(problem, answer):
    if type(problem) is not str or type(answer) is not str or max(len(problem), len(answer)) > 300:
        return "unknown"
    expected, actual = _exact_problem_value(problem), _exact_answer_value(answer)
    if expected is not None and actual is not None:
        return "pass" if expected == actual else "fail"
    text = problem.strip().rstrip("。？?")
    derivative = re.fullmatch(r"求函数\s*f\(x\)\s*=\s*(.+?)\s*的导数", text)
    integral = re.fullmatch(r"计算\s*(.+?)\s*关于\s*x\s*的不定积分", text)
    determinant = re.fullmatch(r"计算矩阵\s*(\[\[.*\]\])\s*的行列式", text)
    try:
        if derivative:
            original = _bounded_polynomial(derivative[1])
            expected_poly = {k-1: v*k for k,v in original.items() if k}
            return "pass" if expected_poly == _bounded_polynomial(answer) else "fail"
        if integral:
            # Require an explicit free integration constant; never prove a partial family.
            match = re.fullmatch(r"(.+?)\s*[+]\s*C", answer.strip())
            if not match:
                return "unknown"
            original = _bounded_polynomial(match[1])
            derivative_poly = {k-1: v*k for k,v in original.items() if k}
            return "pass" if derivative_poly == _bounded_polynomial(integral[1]) else "fail"
        if determinant and actual is not None:
            matrix = json.loads(determinant[1])
            if len(matrix) not in (2, 3) or any(type(row) is not list or len(row) != len(matrix) for row in matrix):
                return "unknown"
            if any(type(v) is not int or abs(v) > 1_000_000 for row in matrix for v in row):
                return "unknown"
            if len(matrix) == 2:
                expected = matrix[0][0]*matrix[1][1] - matrix[0][1]*matrix[1][0]
            else:
                a,b,c = matrix
                expected = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
            return "pass" if actual == expected else "fail"
    except (ValueError, SyntaxError, TypeError, ZeroDivisionError, RecursionError, OverflowError):
        return "unknown"
    return "unknown"


def _math_body(text):
    """Remove only whole-expression math delimiters; never remove conditions."""
    if type(text) is not str or not 0 < len(text) <= 1200:
        raise ValueError("math text bounds")
    text = text.strip()
    for left, right in ((r"\[", r"\]"), (r"\(", r"\)"), ("$$", "$$"), ("$", "$")):
        if text.startswith(left) and text.endswith(right) and len(text) > len(left) + len(right):
            text = text[len(left):-len(right)].strip()
            break
    return text


def _rational_literal(value):
    if type(value) is int and abs(value) <= 1_000_000_000:
        return Fraction(value)
    if type(value) is not str:
        raise ValueError("exact numeric type")
    value = _math_body(value)
    value = re.sub(r"\\frac\{([+-]?\d+)\}\{([+-]?\d+)\}", r"\1/\2", value)
    if len(value) > 40 or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?(?:/[+-]?\d+)?", value):
        raise ValueError("exact numeric syntax")
    # Fraction accepts decimal OR ratio, not a ratio with a decimal numerator.
    if "/" in value:
        numerator, denominator = value.split("/")
        result = Fraction(numerator) / Fraction(denominator)
    else:
        result = Fraction(value)
    if abs(result) > 1_000_000_000:
        raise ValueError("exact numeric magnitude")
    return result


def _polynomial_body(text):
    text = _math_body(text)
    text = re.sub(r"\\frac\{([^{}]+)\}\{([+-]?\d+)\}", r"((\1)/(\2))", text)
    text = re.sub(r"\^\{(\d+)\}", r"^\1", text)
    text = text.replace(r"\cdot", "*")
    text = re.sub(r"(?<=[0-9)])\s*(?=x)", "*", text)
    text = re.sub(r"(?<=[0-9x)])\s*(?=\()", "*", text)
    return _bounded_polynomial(text)


def _bounded_determinant(text):
    text = _math_body(text)
    if text.startswith("[["):
        matrix = json.loads(text)
    else:
        match = re.fullmatch(r"\\begin\{([pbv]?matrix)\}(.*?)\\end\{\1\}", text, re.S)
        if not match:
            raise ValueError("matrix grammar")
        matrix = [row.split("&") for row in re.split(r"\\\\", match[2])]
    if (type(matrix) is not list or not 1 <= len(matrix) <= 6
            or any(type(row) is not list or len(row) != len(matrix) for row in matrix)):
        raise ValueError("matrix dimensions")
    rows = [[_rational_literal(value) for value in row] for row in matrix]
    result = Fraction(1)
    for col in range(len(rows)):
        pivot = next((i for i in range(col, len(rows)) if rows[i][col]), None)
        if pivot is None:
            return Fraction(0)
        if pivot != col:
            rows[pivot], rows[col] = rows[col], rows[pivot]
            result = -result
        divisor = rows[col][col]
        result *= divisor
        for i in range(col + 1, len(rows)):
            factor = rows[i][col] / divisor
            rows[i] = [a - factor*b for a, b in zip(rows[i], rows[col])]
    return result


def _bounded_task_check(problem, answer):
    """C1: whole-task, bounded rational proofs only; no free-form tool claims."""
    if type(problem) is not str or type(answer) is not str or max(len(problem), len(answer)) > 1200:
        return "unknown"
    calculus = _calculus_task_check(problem, answer)
    if calculus != "unknown":
        return calculus
    try:
        text = problem.strip().rstrip("。？?.")
        derivative = re.fullmatch(r"(?:求函数\s*f\(x\)\s*=\s*(.+?)\s*的导数|Differentiate\s+(?:f\(x\)\s*=\s*)?(.+?)(?:\s+with respect to x)?)", text, re.I)
        integral = re.fullmatch(r"(?:计算\s*(.+?)\s*关于\s*x\s*的不定积分|Find the indefinite integral of\s+(.+?)(?:\s+with respect to x)?)", text, re.I)
        matrix = re.fullmatch(r"(?:计算|求)(?:矩阵)?\s*(.+?)\s*的行列式", text)
        if matrix is None:
            matrix = re.fullmatch(r"(?:Compute|Calculate|Find)\s+the determinant of\s+(?:the matrix\s+)?(.+)", text, re.I)
        if matrix:
            return "pass" if _bounded_determinant(matrix[1]) == _rational_literal(answer) else "fail"
        if derivative:
            original = _polynomial_body(next(x for x in derivative.groups() if x))
            expected = {k-1: k*v for k, v in original.items() if k}
            return "pass" if _polynomial_body(answer) == expected else "fail"
        if integral:
            candidate = _math_body(answer)
            match = re.fullmatch(r"(.+?)\s*\+\s*C", candidate)
            if not match:
                return "unknown"
            original = _polynomial_body(match[1])
            derivative_poly = {k-1: k*v for k, v in original.items() if k}
            expected = _polynomial_body(next(x for x in integral.groups() if x))
            return "pass" if derivative_poly == expected else "fail"
        # Extend public notations for two whole-task finite computations.
        combo = re.fullmatch(r"(?:计算|求|Compute|Calculate)\s*(?:C\((\d+),\s*(\d+)\)|\\binom\{(\d+)\}\{(\d+)\})", text, re.I)
        modular = re.fullmatch(r"(?:计算|求|Compute|Calculate)\s*([+-]?\d+)\s*\^\s*(\d+)\s*(?:mod|模)\s*(\d+)", text, re.I)
        if combo:
            n, k = [int(x) for x in combo.groups() if x is not None]
            if not 0 <= k <= n <= 1000:
                return "unknown"
            return "pass" if Fraction(math.comb(n, k)) == _rational_literal(answer) else "fail"
        if modular:
            base, exponent, modulus = map(int, modular.groups())
            if abs(base) > 10**9 or not 0 <= exponent <= 10**6 or not 1 <= modulus <= 10**9:
                return "unknown"
            return "pass" if Fraction(pow(base, exponent, modulus)) == _rational_literal(answer) else "fail"
        return _complete_task_check(problem, answer)
    except (ValueError, TypeError, ZeroDivisionError, SyntaxError, OverflowError, RecursionError):
        return "unknown"


class _CalcAlgebra:
    """Bounded exact Q(x, sqrt(P)); P is positive quadratic or nonsquare constant.

    A polynomial is a coefficient tuple, a rational function a pair of them,
    and a field element a pair of rational functions a + b*sqrt(P). No input
    is executed. Algebra and Sturm sign proofs share one fixed operation cap.
    """

    def __init__(self):
        self.operations = 0
        self.radical = None
        self.zero = ((), (Fraction(1),))
        self.one = ((Fraction(1),), (Fraction(1),))

    def tick(self, count=1):
        self.operations += count
        if self.operations > 20000:
            raise ValueError("calculus operation bound")

    def poly(self, coefficients):
        self.tick()
        values = list(coefficients)
        while values and not values[-1]:
            values.pop()
        if len(values) > 33 or any(max(v.numerator.bit_length(), v.denominator.bit_length()) > 1024 for v in values):
            raise ValueError("calculus polynomial bound")
        return tuple(values)

    def addp(self, a, b):
        return self.poly([(a[i] if i < len(a) else Fraction(0)) + (b[i] if i < len(b) else Fraction(0)) for i in range(max(len(a), len(b)))])

    def negp(self, a):
        return tuple(-v for v in a)

    def mulp(self, a, b):
        if not a or not b:
            return ()
        if len(a) + len(b) > 34:
            raise ValueError("calculus degree bound")
        self.tick(len(a) * len(b))
        out = [Fraction(0)] * (len(a) + len(b) - 1)
        for i, u in enumerate(a):
            for j, v in enumerate(b):
                out[i+j] += u*v
                if max(out[i+j].numerator.bit_length(), out[i+j].denominator.bit_length()) > 1024:
                    raise ValueError("calculus coefficient bound")
        return self.poly(out)

    def divp(self, a, b):
        if not b:
            raise ValueError("calculus zero divisor")
        quotient = [Fraction(0)] * max(0, len(a)-len(b)+1)
        while a and len(a) >= len(b):
            self.tick()
            degree, scale = len(a)-len(b), a[-1]/b[-1]
            quotient[degree] = scale
            a = self.addp(a, self.poly([Fraction(0)]*degree + [-scale*v for v in b]))
        return self.poly(quotient), a

    def rational(self, numerator, denominator=None):
        denominator = self.one[1] if denominator is None else denominator
        if not denominator:
            raise ValueError("calculus zero rational denominator")
        if not numerator:
            return self.zero
        a, b = numerator, denominator
        while b:
            _, remainder = self.divp(a, b)
            a, b = b, remainder
        numerator, _ = self.divp(numerator, a)
        denominator, _ = self.divp(denominator, a)
        scale = denominator[-1]
        return self.poly([v/scale for v in numerator]), self.poly([v/scale for v in denominator])

    def addr(self, a, b):
        if not a[0]:
            return b
        if not b[0]:
            return a
        return self.rational(self.addp(self.mulp(a[0], b[1]), self.mulp(b[0], a[1])), self.mulp(a[1], b[1]))

    def negr(self, a):
        return self.negp(a[0]), a[1]

    def mulr(self, a, b):
        return self.rational(self.mulp(a[0], b[0]), self.mulp(a[1], b[1]))

    def divr(self, a, b):
        return self.rational(self.mulp(a[0], b[1]), self.mulp(a[1], b[0]))

    def constant(self, number):
        return self.rational(self.poly([Fraction(number)])), self.zero

    def add(self, a, b):
        return self.addr(a[0], b[0]), self.addr(a[1], b[1])

    def neg(self, a):
        return self.negr(a[0]), self.negr(a[1])

    def multiply(self, a, b):
        base = self.mulr(a[0], b[0])
        if a[1][0] and b[1][0]:
            base = self.addr(base, self.mulr(self.mulr(a[1], b[1]), self.rational(self.radical)))
        return base, self.addr(self.mulr(a[0], b[1]), self.mulr(a[1], b[0]))

    def divide(self, a, b):
        if not b[1][0]:
            return self.divr(a[0], b[0]), self.divr(a[1], b[0])
        norm = self.addr(self.mulr(b[0], b[0]), self.negr(self.mulr(self.mulr(b[1], b[1]), self.rational(self.radical))))
        conjugate_product = self.multiply(a, (b[0], self.negr(b[1])))
        return self.divr(conjugate_product[0], norm), self.divr(conjugate_product[1], norm)

    def power(self, value, exponent):
        if abs(exponent) > 6:
            raise ValueError("calculus exponent bound")
        out = self.constant(1)
        for _ in range(abs(exponent)):
            out = self.multiply(out, value)
        return self.divide(self.constant(1), out) if exponent < 0 else out

    def signp(self, polynomial):
        """Strict sign on ALL real x, established by Sturm's exact root count."""
        if not polynomial:
            return 0
        if len(polynomial) == 1:
            return 1 if polynomial[0] > 0 else -1
        if (len(polynomial)-1) % 2:
            return 0
        chain = [polynomial, self.poly([i*v for i, v in enumerate(polynomial) if i])]
        while chain[-1]:
            _, remainder = self.divp(chain[-2], chain[-1])
            if not remainder:
                break
            chain.append(self.negp(remainder))
        def changes(direction):
            signs = [(1 if p[-1] > 0 else -1) * (direction ** (len(p)-1)) for p in chain]
            return sum(a != b for a, b in zip(signs, signs[1:]))
        if changes(-1) != changes(1):
            return 0
        return 1 if polynomial[-1] > 0 else -1

    def signr(self, value):
        return self.signp(value[0]) * self.signp(value[1])

    def sign(self, value):
        a, b = value
        sa, sb = self.signr(a), self.signr(b)
        if not b[0]:
            return sa
        if not a[0]:
            return sb
        if sa and sa == sb:
            return sa
        norm = self.addr(self.mulr(a, a), self.negr(self.mulr(self.mulr(b, b), self.rational(self.radical))))
        sn = self.signr(norm)
        return sa if sn > 0 and sa else sb if sn < 0 and sb else 0

    def root(self, value):
        a, b = value
        if b[0] or a[1] != self.one[1] or len(a[0]) > 3 or self.signp(a[0]) != 1:
            raise ValueError("calculus root domain")
        polynomial, scale = a[0], Fraction(1)
        if len(polynomial) == 1:
            number = polynomial[0]
            if number.numerator > 1000000 or number.denominator > 1000000:
                raise ValueError("calculus radical size")
            # Rationalize the denominator, then remove square factors. Each
            # factorization has at most 1000 trial divisions per input integer.
            square, free = 1, 1
            for integer in (number.numerator, number.denominator):
                factor = 2
                while factor*factor <= integer:
                    self.tick()
                    count = 0
                    while integer % factor == 0:
                        integer //= factor
                        count += 1
                    square *= factor ** (count//2)
                    free *= factor ** (count % 2)
                    factor += 1
                free *= integer
            scale = Fraction(square, number.denominator)
            if free == 1:
                return self.constant(scale)
            polynomial = (Fraction(free),)
        if self.radical is None:
            self.radical = polynomial
        elif self.radical != polynomial:
            raise ValueError("calculus second radical")
        return self.zero, self.rational((scale,))

    def iszero(self, value):
        return value is not None and not value[0][0] and not value[1][0]

    def differentiate(self, tree):
        """Dual evaluation; transcendental values stay opaque, never guessed."""
        zero, one = self.constant(0), self.constant(1)
        def visit(node):
            self.tick()
            if isinstance(node, ast.Constant) and type(node.value) is int and abs(node.value) <= 1000000:
                return self.constant(node.value), zero
            if isinstance(node, ast.Name) and node.id == "x":
                return (self.rational((Fraction(0), Fraction(1))), self.zero), one
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
                value, derivative = visit(node.operand)
                return (self.neg(value) if value is not None else None, self.neg(derivative)) if isinstance(node.op, ast.USub) else (value, derivative)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and len(node.args) == 1 and not node.keywords:
                value, derivative = visit(node.args[0])
                if value is None:
                    raise ValueError("calculus nested transcendental")
                name = node.func.id
                if name == "sqrt":
                    root = self.root(value)
                    return root, self.divide(derivative, self.multiply(self.constant(2), root))
                if name in ("ln", "log", "logabs"):
                    sign = self.sign(value)
                    if sign != 1 and not (name == "logabs" and sign == -1):
                        raise ValueError("calculus logarithm domain")
                    return None, self.divide(derivative, value)
                if name == "atan":
                    return None, self.divide(derivative, self.add(one, self.multiply(value, value)))
                raise ValueError("calculus function")
            if not isinstance(node, ast.BinOp):
                raise ValueError("calculus syntax")
            left, dl = visit(node.left)
            right, dr = visit(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                if isinstance(node.op, ast.Sub):
                    right = self.neg(right) if right is not None else None
                    dr = self.neg(dr)
                return self.add(left, right) if left is not None and right is not None else None, self.add(dl, dr)
            if isinstance(node.op, ast.Mult):
                # Constant multiples of ln/atan differentiate without ever
                # assigning an algebraic value to those functions.
                if (left is None and not self.iszero(dr)) or (right is None and not self.iszero(dl)):
                    raise ValueError("calculus transcendental product")
                derivative = self.add(zero if self.iszero(dl) else self.multiply(dl, right), zero if self.iszero(dr) else self.multiply(left, dr))
                return self.multiply(left, right) if left is not None and right is not None else None, derivative
            if isinstance(node.op, ast.Div):
                if right is None or not self.sign(right) or (left is None and not self.iszero(dr)):
                    raise ValueError("calculus denominator domain")
                derivative = self.divide(self.add(self.multiply(dl, right), zero if self.iszero(dr) else self.neg(self.multiply(left, dr))), self.multiply(right, right))
                return self.divide(left, right) if left is not None else None, derivative
            if isinstance(node.op, ast.Pow):
                if left is None or right is None or not self.iszero(dr) or right[1][0] or len(right[0][0]) > 1 or right[0][1] != self.one[1]:
                    raise ValueError("calculus power syntax")
                exponent = right[0][0][0] if right[0][0] else Fraction(0)
                if exponent.denominator != 1 or abs(exponent) > 6 or (exponent <= 0 and not self.sign(left)):
                    raise ValueError("calculus power bound or domain")
                n = int(exponent)
                return self.power(left, n), zero if n == 0 else self.multiply(self.multiply(self.constant(n), self.power(left, n-1)), dl)
            raise ValueError("calculus operator")
        return visit(tree)


def _calculus_expression(text):
    """Translate only an explicit, bounded elementary grammar to inert AST."""
    text = _math_body(text).replace(r"\left", "").replace(r"\right", "").replace("−", "-")
    text = re.sub(r"√(\d{1,7})(?![\w.])", r"sqrt(\1)", text)
    text = text.replace("√(", "sqrt(")
    text = re.sub(r"\\[,;! ]", " ", text).replace(r"\cdot", "*").replace(r"\times", "*")
    text = text.replace(r"\arctan", "atan").replace("arctan", "atan")
    text = re.sub(r"\\(ln|log|sqrt)\b", r"\1", text)
    tokens = re.findall(r"\\(?:dfrac|tfrac|frac)|[A-Za-z]+|[0-9]+|\*\*|[+*/^(){}|\-]|\S", text)
    if len(tokens) > 256:
        raise ValueError("calculus token bound")
    index = 0
    def group(depth=0, closing=None):
        nonlocal index
        if depth > 16:
            raise ValueError("calculus nesting")
        out = []
        while index < len(tokens):
            token = tokens[index]
            if token == closing:
                index += 1
                return out
            index += 1
            if token in ("(", "{"):
                atom = ["("] + group(depth+1, ")" if token == "(" else "}") + [")"]
            elif token in (r"\frac", r"\dfrac", r"\tfrac"):
                pieces = []
                for _ in range(2):
                    if index >= len(tokens) or tokens[index] != "{":
                        raise ValueError("calculus fraction groups")
                    index += 1
                    pieces.append(group(depth+1, "}"))
                atom = ["(", "("] + pieces[0] + [")", "/", "("] + pieces[1] + [")", ")"]
            elif token in ("ln", "log") and index < len(tokens) and tokens[index] == "|":
                index += 1
                atom = ["logabs", "("] + group(depth+1, "|") + [")"]
            elif token in ("x", "sqrt", "ln", "log", "atan") or re.fullmatch(r"\d{1,7}", token):
                atom = [token]
            elif token in ("+", "-", "*", "/", "^", "**"):
                atom = ["**" if token == "^" else token]
            else:
                raise ValueError("calculus token")
            if out and out[-1].isdigit() and atom[0].isdigit():
                raise ValueError("calculus adjacent numeric literals")
            if out and (out[-1] == ")" or out[-1] == "x" or out[-1].isdigit()) and (atom[0] == "(" or atom[0] in ("x", "sqrt", "ln", "log", "atan", "logabs") or atom[0].isdigit()):
                out.append("*")
            out.extend(atom)
        if closing is not None:
            raise ValueError("calculus unclosed group")
        return out
    source = " ".join(group())
    if len(source) > 3000:
        raise ValueError("calculus expanded size")
    # Common TeX arctan\frac{...}{...} is one function argument. Bare
    # function application to x is deliberately not guessed.
    tree = ast.parse(source, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 192:
        raise ValueError("calculus AST bound")
    return tree.body


def _calculus_task_check(problem, answer):
    """Whole single real indefinite integrals; exact proofs, otherwise unknown."""
    if type(problem) is not str or type(answer) is not str or max(len(problem), len(answer)) > 1200:
        return "unknown"
    try:
        text = problem.strip().rstrip("。？?.")
        # Bind the complete explicit integer parameter block, never discard
        # trailing conditions or silently reuse values from another question.
        split = re.split(r"\s+where\s+", text, flags=re.I)
        if len(split) > 2:
            return "unknown"
        if len(split) == 2:
            text, assignments = split
            assignments = re.sub(r",?\s+and\s+", ",", assignments, flags=re.I)
            pieces = assignments.split(",")
            if not 1 <= len(pieces) <= 6:
                return "unknown"
            bindings = {}
            for piece in pieces:
                assignment = _math_body(piece)
                binding = re.fullmatch(r"([A-Za-z])\s*=\s*([+-]?\d{1,6})", assignment)
                if not binding or binding[1] in ("x", "C") or binding[1] in bindings:
                    return "unknown"
                bindings[binding[1]] = int(binding[2])
            for name, number in bindings.items():
                text, count = re.subn(r"(?<![A-Za-z\\])"+re.escape(name)+r"(?![A-Za-z])", "("+str(number)+")", text)
                if not count:
                    return "unknown"
        direct = re.fullmatch(r"(?:计算\s*(.+?)\s*关于\s*x\s*的不定积分|Find the indefinite integral of\s+(.+?)(?:\s+with respect to x)?)", text, re.I | re.S)
        if direct:
            integrand = next(value for value in direct.groups() if value is not None)
        else:
            match = re.fullmatch(r"(?:Calculate|Compute|Evaluate|Find)\s+(?:the\s+)?(?:indefinite\s+)?integral\s*[:：]?\s*(.+)|(?:计算|求)(?:下列|下面的)?(?:不定)?积分\s*[:：]?\s*(.+)", text, re.I | re.S)
            if not match:
                return "unknown"
            formula = _math_body(next(value for value in match.groups() if value is not None))
            formula = re.sub(r"\\[,;! ]", " ", formula)
            integral = re.fullmatch(r"\\int\s+(.+?)\s*(?:d\s*x|\\mathrm\{d\}\s*x)", formula, re.S)
            if not integral:
                return "unknown"
            integrand = integral[1]
        body = _math_body(answer)
        primitive = re.fullmatch(r"(.+?)\s*\+\s*C", body)
        if not primitive:
            return "unknown"
        algebra = _CalcAlgebra()
        expected, _ = algebra.differentiate(_calculus_expression(integrand))
        if expected is None:
            return "unknown"
        _, derivative = algebra.differentiate(_calculus_expression(primitive[1]))
        # sqrt(P) is irreducible over Q(x) by construction; both reduced
        # coefficients vanish iff this algebraic function vanishes identically.
        return "pass" if algebra.iszero(algebra.add(derivative, algebra.neg(expected))) else "fail"
    except (ValueError, TypeError, ZeroDivisionError, SyntaxError, OverflowError, RecursionError):
        return "unknown"
