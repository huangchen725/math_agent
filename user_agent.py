"""数学推理智能体的竞赛接口与求解流水线。

接口约束：solve(problem, metadata) -> {"final_response": str, "trace": list}
架构事实源：ARCHITECTURE.md
"""
import json
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from agent_types import Candidate, Verification
from answer_equivalence import (
    build_answer,
    format_answer_for_output,
    normalize_answer,
    numeric_value,
)
from budget import BudgetExceeded, ExecutionBudget
from math_tools import run_tool_loop
from domain_prompts import get_domain_prompt


_ACTIVE_BUDGET: ContextVar[ExecutionBudget | None] = ContextVar(
    "active_problem_budget",
    default=None,
)


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

VERIFIER_PROMPT = """你是数学答案验证器。请判断候选解答是否正确。

判断维度：1.推理逻辑 2.计算准确性 3.最终答案

只输出：VERDICT: A（正确）或 VERDICT: B（错误）"""

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
    # token
    max_tokens: int = 8192
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    # thinking mode（v13: False——thinking导致截断；R1-1 三参数投影后不再发送）
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

    def __init__(self, client: Any, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client

    def _chat(self, system_prompt: str, user_content: str,
              temperature: float, max_tokens: int) -> str:
        """调用 client.chat，返回文本。仅使用三参数公开协议（CLIENT-001）。"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        budget = _ACTIVE_BUDGET.get()
        if budget is not None:
            budget.consume_model_request()
        resp = self.client.chat(
            messages=messages, temperature=temperature, max_tokens=max_tokens
        )
        return resp if isinstance(resp, str) else str(resp.get("content", ""))

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

        # 阶段2：多候选生成（全部温度0.6，v13配置）
        candidates, gen_trace = self._generate_candidates(problem, domain_prompt)
        trace.extend(gen_trace)

        # 截断兜底
        if not candidates or all(not self._extract_answer(c) for c in candidates):
            trace.append({"step": "truncated_fallback", "content": "所有候选被截断"})
            if self.config.enable_fallback:
                fb = self._quick_fallback(problem, trace)
                if fb:
                    return {"final_response": self._build_response("", fb), "trace": trace}

        # 阶段3：验证投票
        scored: List[Candidate] = []
        for cid, candidate in enumerate(candidates):
            confidence, vt, verifications = self._verify(problem, candidate, cid)
            answer = build_answer(self._extract_answer(candidate))
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

        # 阶段4：Critic + 反思（仅低置信度触发）
        if self.config.enable_critic and scored:
            best = max(scored, key=lambda item: item.confidence)
            if best.raw_confidence < 0.5 and best.answer.raw:
                criticism = self._critic(problem, best.content, trace)
                if criticism and "NO ERROR" not in criticism.upper():
                    refined = self._reflect(problem, best.content, criticism, trace)
                    if refined:
                        rc, rv, verifications = self._verify(
                            problem, refined, len(candidates)
                        )
                        ra = build_answer(self._extract_answer(refined))
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

        # 阶段6：加权聚合
        final_answer, best_content = self._aggregate(scored, trace)
        if not final_answer and scored:
            final_answer = self._extract_answer(scored[0].content) or "未解出"
        if not best_content and scored:
            best_content = scored[0].content
        final_response = self._build_response(best_content, final_answer)

        return {"final_response": final_response or final_answer or "未解出", "trace": trace}

    def _build_response(self, content: str, answer: str) -> str:
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
        for i in range(self.config.tool_candidates):
            if self.config.enable_tools:
                cand, tt = self._solve_tools(problem, i, domain_prompt)
            else:
                cand = self._solve_plain(problem, domain_prompt)
                tt = [{"step": f"policy_tool_{i}", "content": cand[:1000]}]
            candidates.append(cand)
            trace.extend(tt)
        for i in range(self.config.plain_candidates):
            cand = self._solve_plain(problem, domain_prompt)
            candidates.append(cand)
            trace.append({"step": f"policy_plain_{i}", "content": cand[:1000]})
        return [c for c in candidates if c], trace

    def _solve_tools(self, problem: str, cid: int, domain_prompt: str) -> Tuple[str, List[Dict]]:
        try:
            messages = [
                {"role": "system", "content": domain_prompt or POLICY_PROMPT},
                {"role": "user", "content": f"{problem}\n\n请调用工具验证关键计算。候选编号：{cid}"},
            ]
            response, tt = run_tool_loop(
                self.client, messages,
                max_rounds=self.config.max_tool_rounds,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
                tool_timeout_seconds=self.config.tool_timeout_seconds,
                budget=_ACTIVE_BUDGET.get(),
            )
            if self.config.enable_fallback and "最终答案" not in response and len(response) > 3000:
                trace = [{"step": f"tool_solve_{cid}", "content": tt}]
                trace.append({"step": f"truncated_{cid}", "content": "截断兜底"})
                fb = self._quick_fallback(problem, trace)
                if fb:
                    response = fb
                trace.append({"step": f"policy_tool_{cid}", "content": response[:2000]})
                return response, trace
            trace = [{"step": f"tool_solve_{cid}", "content": tt}]
            trace.append({"step": f"policy_tool_{cid}", "content": response[:2000]})
            return response, trace
        except BudgetExceeded:
            raise
        except Exception as e:
            trace = [{"step": f"tool_error_{cid}", "content": str(e)[:200]}]
            return self._solve_plain(problem, domain_prompt), trace

    def _solve_plain(self, problem: str, domain_prompt: str) -> str:
        try:
            prefix = domain_prompt or POLICY_NO_TOOL_PROMPT
            return self._chat(prefix, f"{problem}\n\n请给出完整解答。",
                              temperature=self.config.policy_temperature,
                              max_tokens=self.config.max_tokens)
        except BudgetExceeded:
            raise
        except Exception:
            return ""

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
                verdict = self._chat(VERIFIER_PROMPT,
                    f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n判断是否正确。只输出：VERDICT: A 或 VERDICT: B",
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens)
                passed = self._is_correct(verdict)
                votes.append(passed)
                verifications.append(Verification(
                    source="model",
                    status="pass" if passed else "fail",
                    confidence=1.0 if passed else 0.0,
                    detail=verdict[:200],
                ))
                trace.append({"step": f"verify_{cid}_{vid}", "content": verdict[:200]})
            except BudgetExceeded:
                raise
            except Exception as e:
                votes.append(False)
                verifications.append(Verification(
                    source="model",
                    status="unknown",
                    confidence=0.0,
                    detail=f"{type(e).__name__}: {str(e)[:160]}",
                ))
                trace.append({"step": f"verify_err_{cid}_{vid}", "content": str(e)[:200]})
        return (sum(votes) / len(votes) if votes else 0.0), trace, verifications

    def _critic(self, problem: str, candidate: str, trace: List[Dict]) -> str:
        try:
            review_text = self._review_excerpt(candidate)
            criticism = self._chat(CRITIC_PROMPT,
                f"题目：\n{problem}\n\n候选解答：\n{review_text}\n\n请找出错误或改进点。",
                temperature=self.config.critic_temperature,
                max_tokens=self.config.critic_max_tokens)
            trace.append({"step": "critic", "content": criticism[:500]})
            return criticism
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "critic_error", "content": str(e)[:200]})
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
            trace.append({"step": "reflection", "content": resp[:1000]})
            return resp
        except BudgetExceeded:
            raise
        except Exception as e:
            trace.append({"step": "reflect_error", "content": str(e)[:200]})
            return ""

    def _aggregate(self, scored: List[Candidate], trace: List[Dict]) -> Tuple[str, str]:
        """v17：回退v13——简单多数投票。"""
        if not scored:
            return "", ""
        with_ans = [candidate for candidate in scored if candidate.answer.raw]
        if not with_ans:
            best = max(scored, key=lambda item: item.confidence)
            return self._normalize(best.content.strip()[:500]), best.content
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
                temperature=0.0, max_tokens=self.config.fallback_max_tokens)
            ans = self._extract_answer(resp)
            trace.append({"step": "fallback_result", "content": ans[:100]})
            return ans or resp.strip()[:200]
        except BudgetExceeded:
            raise
        except Exception:
            return ""

    @staticmethod
    def _extract_answer(text: str) -> str:
        """v12稳定版——简单可靠。"""
        if not text:
            return ""
        m = re.search(r"最终答案\s*[:：]\s*(.+?)(?:\n|$)", text)
        if m: return m.group(1).strip()
        m = re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
        if m: return m.group(1).strip()
        m = re.search(r"答案(?:是|为)?\s*[:：]?\s*(.+?)(?:\n|。|$)", text)
        if m: return m.group(1).strip()
        lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
        return lines[-1][:200] if lines else ""

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
        m = re.findall(r"\bVERDICT\s*[:：]\s*([AB])", verdict, re.IGNORECASE)
        if m: return m[-1].upper() == "A"
        m = re.findall(r"^\s*([AB])\s*$", verdict, re.IGNORECASE | re.MULTILINE)
        if m: return m[-1].upper() == "A"
        words = re.findall(r"\b[A-Z]+\b", verdict.upper())
        return "CORRECT" in words and "INCORRECT" not in words
