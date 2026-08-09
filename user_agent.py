"""增强版数学推理智能体 v2 —— 工具调用 + 反思纠错 + 智能聚合。

创新点（相对官方 baseline）：
1. 题型识别与领域路由：识别子领域，注入领域专家提示
2. 推理规划：解题前先生成思路摘要
3. 工具增强求解：SymPy 实际计算（求根/求导/积分/留数/极限），消灭算术错误
4. 反思纠错：验证器发现错误时反馈重试一轮
5. 答案归一化 + 数值比较：LaTeX→纯文本，72==72.0==72/1
6. Self-consistency：多候选答案一致优先
7. 启发式 trace：完整推理链支撑主观评分

接口约束（不可改）：
- 类名 ReasoningAgent，构造函数接受 client
- solve(problem, metadata) -> {"final_response": str, "trace": list}
- 不能硬编码 API key，client 由平台注入
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

from lagent.agents import Agent
from lagent.schema import AgentMessage

from llm_client import InternChatClient
from math_tools import run_tool_loop, TOOL_DEFINITIONS
from domain_prompts import get_domain_prompt


# ==================== 提示词设计 ====================

POLICY_PROMPT = """你是数学推理智能体。

【重要】解题时必须先写答案行，再写推导过程：
最终答案：XXX
（然后给出简要推导，不超过500字）

答案格式：
- 纯数字或a/b分数，不用LaTeX
- 多个解用英文逗号或换行分隔，如：2,3 或 2\n3
- 如果无法确定精确答案，给出最佳估计值

示例：
最终答案：72
"""

POLICY_NO_TOOL_PROMPT = """你是数学推理智能体。用纯推理解题。

【重要】必须先写答案行，再写推导：
最终答案：XXX
（然后简要推导，不超过500字）

答案格式：纯数字或a/b分数。
"""

VERIFIER_PROMPT = """你是一个数学答案验证器。请判断候选解答是否正确解决了题目。

判断维度：
1. 推理过程是否有逻辑错误
2. 计算是否准确
3. 最终答案是否正确

只输出以下两行之一（不要输出其他内容）：
VERDICT: A   （候选解答正确）
VERDICT: B   （候选解答错误）"""

PLANNER_PROMPT = """你是一个数学问题分析专家。请分析下面的数学题，输出：
1. 问题类型（如：抽象代数/复分析/测度积分/偏微分方程/运筹学/概率论/几何/拓扑/数论/组合 等）
2. 关键条件提取
3. 建议的求解策略（一句话）

格式：
类型：XXX
条件：XXX
策略：XXX"""

REFLECTION_PROMPT = """你之前的解答可能存在错误。请根据以下反馈重新解答。

原题：{problem}

你之前的解答：
{prev_answer}

验证反馈：{feedback}

请仔细检查，修正错误，重新给出解答。最终答案：XXX"""


# 领域专家提示
DOMAIN_HINTS = {
    "抽象代数": "关注群、环、域的结构，有限域的扩张次数与元素计数。可用 solve_equation 工具验证。",
    "复分析": "关注留数、柯西积分定理。可用 residue 工具直接计算留数。",
    "测度积分": "关注积分变换、反函数、Lebesgue 测度。可用 integrate/differentiate 工具验证。",
    "偏微分方程": "关注分离变量法、傅里叶变换、边界条件代入。",
    "实分析": "关注极限、连续性、级数收敛。可用 limit 工具计算极限。",
    "拓扑": "关注同伦、同调、基本群，不变量计算。",
    "运筹学": "关注线性规划、对偶、最优性条件。",
    "概率论": "关注全概率公式、贝叶斯、期望与方差。",
    "组合": "关注计数原理、生成函数、容斥原理。",
    "数论": "关注整除、同余、欧拉函数、中国剩余定理。",
    "几何": "关注坐标系建立、向量方法、面积/体积公式。",
    "线性代数": "关注矩阵秩、行列式、特征值、向量空间。",
}


@dataclass
class AgentConfig:
    """智能体配置（v5：保留v4安全配置+多解prompt支持）。"""
    # 候选生成（保持v4保守配置，v5多候选反而降低正确率）
    tool_candidates: int = 1           # 工具增强候选数
    plain_candidates: int = 1          # 纯推理候选数
    verifier_voting_times: int = 1     # 每个候选验证投票次数
    # 温度
    policy_temperature: float = 0.6    # 候选生成温度
    planner_temperature: float = 0.2   # 规划温度
    verifier_temperature: float = 0.0  # 验证温度
    reflection_temperature: float = 0.3 # 反思温度
    # token（平台锁4096，max_tokens传了也没用）
    max_tokens: int = 4096             # 平台强制4096，无法覆盖
    verifier_max_tokens: int = 1024    # 验证 token
    fallback_max_tokens: int = 512    # 截断兜底重试 token
    # thinking mode（关闭避免4096截断）
    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    planner_thinking_mode: bool = False
    # 功能开关
    enable_planner: bool = False
    enable_tools: bool = True
    enable_reflection: bool = False
    max_tool_rounds: int = 3


class ReasoningAgent:
    """增强版数学推理智能体 v2。

    架构：规划 → 工具增强候选 + 纯推理候选 → 验证投票 → 反思纠错 → Self-consistency 聚合
    """

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client
        self.policy_agent = Agent(llm=client, template=POLICY_PROMPT, name="policy_agent")
        self.plain_agent = Agent(llm=client, template=POLICY_NO_TOOL_PROMPT, name="plain_agent")
        self.verifier_agent = Agent(llm=client, template=VERIFIER_PROMPT, name="verifier_agent")
        self.planner_agent = (
            Agent(llm=client, template=PLANNER_PROMPT, name="planner_agent")
            if self.config.enable_planner else None
        )

    def solve(self, problem: str, metadata: Dict) -> Dict:
        """主求解流程。全局 try-except 防止返回空答案。"""
        idx = metadata.get("idx", 0)
        trace: List[Dict] = []

        try:
            return self._solve_impl(problem, idx, trace)
        except Exception as e:
            trace.append({"step": "global_error", "content": f"{type(e).__name__}: {str(e)[:300]}"})
            # 兜底：尝试快速重答
            fallback = self._quick_fallback(problem, idx, trace)
            return {
                "final_response": fallback or "未解出",
                "trace": trace,
            }

    def _solve_impl(self, problem: str, idx: int, trace: List[Dict]) -> Dict:
        """实际求解逻辑。"""
        # 阶段1：题型识别与规划（默认关闭省时）
        domain_name, domain_prompt, plan_info = self._plan(problem, idx, trace)
        # 无规划时仍尝试领域路由
        if not domain_prompt:
            domain_prompt = get_domain_prompt("")

        # 阶段2：多候选生成
        candidates, gen_trace = self._generate_candidates(problem, idx, domain_prompt, plan_info)
        trace.extend(gen_trace)

        # 截断兜底：候选为空或都没答案时快速重答
        if not candidates or all(not self._extract_answer(c) for c in candidates):
            trace.append({"step": "truncated_fallback", "content": "所有候选被截断或无答案，启动兜底"})
            fb = self._quick_fallback(problem, idx, trace)
            if fb:
                return {"final_response": fb, "trace": trace}

        # 阶段3：验证投票
        scored = []
        for cid, candidate in enumerate(candidates):
            confidence, verify_trace = self._verify_candidate(problem, candidate, idx, cid)
            answer = self._extract_answer(candidate)
            has_answer_bonus = 0.3 if answer else -0.5
            scored.append({
                "content": candidate,
                "confidence": confidence + has_answer_bonus,
                "answer": answer,
                "raw_confidence": confidence,
            })
            trace.extend(verify_trace)

        # 阶段4：反思纠错（默认关闭省时）
        if self.config.enable_reflection and scored:
            best_so_far = max(scored, key=lambda x: x["confidence"])
            if best_so_far["raw_confidence"] < 0.5 and best_so_far["answer"]:
                reflection_candidate, refl_trace = self._reflect_and_retry(
                    problem, best_so_far, idx, len(candidates)
                )
                if reflection_candidate:
                    refl_confidence, refl_verify = self._verify_candidate(
                        problem, reflection_candidate, idx, len(candidates)
                    )
                    refl_answer = self._extract_answer(reflection_candidate)
                    scored.append({
                        "content": reflection_candidate,
                        "confidence": refl_confidence + (0.3 if refl_answer else -0.5),
                        "answer": refl_answer,
                        "raw_confidence": refl_confidence,
                    })
                    trace.extend(refl_trace)
                    trace.extend(refl_verify)

        # 阶段5：Self-consistency 聚合
        final_answer = self._aggregate_answers(scored, trace)

        # 最终兜底：如果聚合结果为空，取第一个候选的末行
        if not final_answer and scored:
            final_answer = self._extract_answer(scored[0]["content"]) or "未解出"

        return {
            "final_response": final_answer or "未解出",
            "trace": trace,
        }

    def _quick_fallback(self, problem: str, idx: int, trace: List[Dict]) -> str:
        """截断/异常兜底：关thinking+短token+只要答案。"""
        try:
            msg = AgentMessage(
                sender="user",
                content=f"{problem}\n\n请直接给出最终答案，不要详细推导。格式：最终答案：XXX",
            )
            resp = self.plain_agent(
                msg, session_id=f"{idx}:fallback",
                temperature=0.0,
                max_tokens=self.config.fallback_max_tokens,
                thinking_mode=False,
            )
            answer = self._extract_answer(resp.content)
            trace.append({"step": "fallback_result", "content": answer[:100]})
            return answer or resp.content.strip()[:200]
        except Exception:
            return ""

    # ---------- 阶段1：规划 ----------
    def _plan(self, problem: str, idx: int, trace: List[Dict]) -> Tuple[str, str, str]:
        """题型识别 + 求解策略规划 + 领域专属prompt获取。"""
        if not self.config.enable_planner or self.planner_agent is None:
            return "", get_domain_prompt(""), ""
        try:
            msg = AgentMessage(sender="user", content=problem)
            resp = self.planner_agent(
                msg, session_id=f"{idx}:plan",
                temperature=self.config.planner_temperature,
                max_tokens=1024,
                thinking_mode=self.config.planner_thinking_mode,
            )
            plan_text = resp.content
            trace.append({"step": "plan", "content": plan_text[:500]})
            domain_name = self._extract_field(plan_text, "类型")
            domain_prompt = get_domain_prompt(domain_name)
            trace.append({"step": "domain_routing",
                          "content": f"识别领域: {domain_name} → 注入专属策略({len(domain_prompt)}字)"})
            return domain_name, domain_prompt, plan_text
        except Exception:
            return "", get_domain_prompt(""), ""

    # ---------- 阶段2：候选生成 ----------
    def _generate_candidates(self, problem: str, idx: int,
                             domain_prompt: str, plan_info: str) -> Tuple[List[str], List[Dict]]:
        candidates = []
        trace = []
        # 构造增强问题：领域专属prompt + 规划信息 + 原始题面
        problem_enhanced = problem
        if plan_info:
            problem_enhanced = f"【求解参考】\n{plan_info}\n\n【题目】\n{problem}"

        # 工具增强候选（用领域prompt作为system message）
        for i in range(self.config.tool_candidates):
            if self.config.enable_tools:
                cand, tool_trace = self._solve_with_tools(problem_enhanced, idx, i, domain_prompt)
                candidates.append(cand)
                trace.extend(tool_trace)
            else:
                cand = self._solve_plain(problem_enhanced, idx, f"tool_{i}", domain_prompt)
                candidates.append(cand)
                trace.append({"step": f"policy_tool_{i}", "content": cand[:1000]})

        # 纯推理候选（用领域prompt作为system message）
        for i in range(self.config.plain_candidates):
            cand = self._solve_plain(problem_enhanced, idx, f"plain_{i}", domain_prompt)
            candidates.append(cand)
            trace.append({"step": f"policy_plain_{i}", "content": cand[:1000]})

        return [c for c in candidates if c], trace

    def _solve_with_tools(self, problem: str, idx: int, cid: int,
                          domain_prompt: str = "") -> Tuple[str, List[Dict]]:
        """工具增强求解：调 client.chat 带 tools，执行工具调用循环。"""
        try:
            system_prompt = domain_prompt or POLICY_PROMPT
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{problem}\n\n请调用工具验证关键计算，然后给出解答。候选编号：{cid}"},
            ]
            response, tool_trace = run_tool_loop(
                self.client, messages,
                max_rounds=self.config.max_tool_rounds,
                thinking_mode=self.config.policy_thinking_mode,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
            )
            trace = [{"step": f"tool_solve_{cid}", "content": tool_trace}]
            trace.append({"step": f"policy_tool_{cid}", "content": response[:2000]})
            return response, trace
        except Exception as e:
            # 工具调用失败，退化纯推理
            trace = [{"step": f"tool_error_{cid}", "content": str(e)[:200]}]
            cand = self._solve_plain(problem, idx, f"fallback_{cid}", domain_prompt)
            return cand, trace

    def _solve_plain(self, problem: str, idx: int, tag: str,
                     domain_prompt: str = "") -> str:
        """纯推理求解（无工具），注入领域专属prompt。"""
        try:
            # 把领域prompt作为前缀注入问题
            prefix = domain_prompt if domain_prompt else POLICY_NO_TOOL_PROMPT
            user_message = AgentMessage(sender="user", content=f"{prefix}\n\n{problem}\n\n请给出完整解答。")
            response = self.plain_agent(
                user_message,
                session_id=f"{idx}:{tag}",
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
                thinking_mode=self.config.policy_thinking_mode,
            )
            return response.content
        except Exception:
            return ""

    # ---------- 阶段3：验证 ----------
    def _verify_candidate(self, problem: str, candidate: str,
                          idx: int, cid: int) -> Tuple[float, List[Dict]]:
        votes = []
        trace = []
        for vid in range(self.config.verifier_voting_times):
            user_message = AgentMessage(
                sender="user",
                content=(
                    f"题目：\n{problem}\n\n候选解答：\n{candidate[:3000]}\n\n"
                    "请判断候选解答是否正确。只输出一行：VERDICT: A 或 VERDICT: B。"
                ),
            )
            try:
                response = self.verifier_agent(
                    user_message, session_id=f"{idx}:verify:{cid}:{vid}",
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens,
                    thinking_mode=self.config.verifier_thinking_mode,
                )
                verdict = response.content
                votes.append(self._is_correct_vote(verdict))
                trace.append({"step": f"verify_{cid}_{vid}", "content": verdict[:200]})
            except Exception as e:
                votes.append(False)
                trace.append({"step": f"verify_error_{cid}_{vid}", "content": str(e)[:200]})
        confidence = sum(votes) / len(votes) if votes else 0.0
        return confidence, trace

    # ---------- 阶段4：反思纠错 ----------
    def _reflect_and_retry(self, problem: str, best: Dict, idx: int, cid: int) -> Tuple[str, List[Dict]]:
        """验证不通过时，把反馈喂给模型重试。"""
        trace = []
        feedback = "验证器认为该解答可能有误，请检查计算步骤和逻辑推理。"
        try:
            prompt = REFLECTION_PROMPT.format(
                problem=problem,
                prev_answer=best["content"][:2000],
                feedback=feedback,
            )
            user_message = AgentMessage(sender="user", content=prompt)
            response = self.policy_agent(
                user_message, session_id=f"{idx}:reflect:{cid}",
                temperature=self.config.reflection_temperature,
                max_tokens=self.config.max_tokens,
                thinking_mode=self.config.policy_thinking_mode,
            )
            trace.append({"step": f"reflect_{cid}", "content": response.content[:1000]})
            return response.content, trace
        except Exception as e:
            trace.append({"step": f"reflect_error_{cid}", "content": str(e)[:200]})
            return "", trace

    # ---------- 阶段5：答案聚合 ----------
    def _aggregate_answers(self, scored: List[Dict], trace: List[Dict]) -> str:
        """Self-consistency 聚合 + 数值比较 + 归一化。"""
        if not scored:
            return ""

        # 收集所有有答案的候选
        with_answer = [s for s in scored if s["answer"]]
        if not with_answer:
            best = max(scored, key=lambda x: x["confidence"])
            return self._normalize_answer(best["content"].strip()[:500])

        # 数值归一化后投票
        normalized = []
        for s in with_answer:
            norm = self._normalize_answer(s["answer"])
            s["normalized"] = norm
            s["numeric"] = self._try_numeric(norm)
            normalized.append(s)

        # 按数值相等分组投票
        answer_groups = {}
        for s in normalized:
            key = s["numeric"] if s["numeric"] is not None else s["normalized"]
            answer_groups.setdefault(key, []).append(s)

        # 找得票最高的组
        best_key = max(answer_groups.keys(),
                       key=lambda k: (len(answer_groups[k]),
                                      max(s["confidence"] for s in answer_groups[k])))
        best_group = answer_groups[best_key]
        votes = len(best_group)

        if votes >= 2:
            # Self-consistency：用归一化答案
            final = best_group[0]["normalized"]
            trace.append({"step": "self_consistency",
                          "content": f"答案 '{final}' 获得 {votes} 票一致（共 {len(normalized)} 个有答案候选）"})
            return final
        else:
            # 没有一致的，按验证分选最优
            best = max(normalized, key=lambda x: x["confidence"])
            trace.append({"step": "select_final",
                          "content": f"无一致答案，选验证分最高: confidence={best['confidence']:.3f}, 答案={best['normalized']}"})
            return best["normalized"]

    # ---------- 工具方法 ----------
    @staticmethod
    def _extract_answer(text: str) -> str:
        if not text:
            return ""
        m = re.search(r"最终答案\s*[:：]\s*(.+?)(?:\n|$)", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
        if m:
            return m.group(1).strip()
        m = re.search(r"答案(?:是|为)?\s*[:：]?\s*(.+?)(?:\n|。|$)", text)
        if m:
            return m.group(1).strip()
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        if lines:
            return lines[-1][:200]
        return ""

    @staticmethod
    def _normalize_answer(answer: str) -> str:
        if not answer:
            return ""
        s = answer.strip()
        s = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", s)
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\dfrac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\(?:mathbb|text|mathrm|mathcal)\{([^{}]*)\}", r"\1", s)
        s = s.replace("\\left", "").replace("\\right", "").replace("$", "")
        s = s.rstrip("。.，,；;").strip("\"'""''")
        return s.strip()

    @staticmethod
    def _try_numeric(s: str) -> float | None:
        """尝试将答案转为数值，用于数值相等比较（72 == 72.0 == 72/1）。"""
        try:
            if "/" in s:
                parts = s.split("/")
                if len(parts) == 2:
                    return float(parts[0]) / float(parts[1])
            return float(s)
        except (ValueError, ZeroDivisionError):
            return None

    @staticmethod
    def _extract_field(text: str, field: str) -> str:
        m = re.search(rf"{field}\s*[:：]\s*(.+?)(?:\n|$)", text)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _is_correct_vote(verdict: str) -> bool:
        verdict_matches = re.findall(r"\bVERDICT\s*[:：]\s*([AB])\s*[。.]?", verdict, flags=re.IGNORECASE)
        if verdict_matches:
            return verdict_matches[-1].upper() == "A"
        label_matches = re.findall(r"^\s*([AB])\s*[。.]?\s*$", verdict, flags=re.IGNORECASE | re.MULTILINE)
        if label_matches:
            return label_matches[-1].upper() == "A"
        words = re.findall(r"\b[A-Z]+\b", verdict.upper())
        if "INCORRECT" in words:
            return False
        return "CORRECT" in words
