"""增强版数学推理智能体 v6 —— 多智能体协同 + 推理过程 + 截断兜底。

v6 核心改动（相对 v5）：
1. 不依赖 lagent，直接用 InternChatClient（更稳定）
2. final_response 包含完整推理过程（不只是答案）
3. 多智能体协同：Solver → Verifier → Critic → Refiner
4. 截断检测 + 兜底重试
5. 候选数增到 3（2 工具 + 1 纯推理）
6. 领域 prompt 含关键定理 + few-shot 示例

接口约束：solve(problem, metadata) -> {"final_response": str, "trace": list}
"""
import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Tuple

from llm_client import InternChatClient
from math_tools import run_tool_loop, TOOL_DEFINITIONS
from domain_prompts import get_domain_prompt


# ==================== 提示词 ====================

POLICY_PROMPT = """你是数学推理智能体。解题并给出推理过程。

格式：
1. 解题思路
2. 关键推导步骤
3. 最终答案：XXX

答案：纯数字或a/b分数。多解用逗号分隔。
"""

POLICY_NO_TOOL_PROMPT = """你是数学推理智能体。用纯推理解题。

格式：
1. 解题思路
2. 关键推导
3. 最终答案：XXX

答案：纯数字或a/b分数。
"""

VERIFIER_PROMPT = """你是数学答案验证器。请判断候选解答是否正确。

判断维度：1.推理逻辑 2.计算准确性 3.最终答案

只输出：VERDICT: A（正确）或 VERDICT: B（错误）"""

CRITIC_PROMPT = """你是数学解题批评者。请找出候选解答中的错误或可改进之处。

检查：1.逻辑漏洞 2.计算错误 3.边界情况 4.答案格式

如果有错误，指出具体位置和正确做法。如果没有错误，输出：NO ERROR"""

PLANNER_PROMPT = """你是数学问题分析专家。请分析题目，输出：
类型：XXX
条件：XXX
策略：XXX"""

REFLECTION_PROMPT = """你之前的解答可能有误。请根据反馈重新解答。

原题：{problem}
之前的解答：{prev_answer}
批评反馈：{feedback}

请修正错误，给出完整推理和最终答案。"""


@dataclass
class AgentConfig:
    """智能体配置（v8：回退v6+Critic始终触发）。"""
    tool_candidates: int = 2           # 回退到v6的2候选
    plain_candidates: int = 1           # 回退到v6的1纯推理
    verifier_voting_times: int = 1
    policy_temperature: float = 0.6
    planner_temperature: float = 0.2
    verifier_temperature: float = 0.0
    critic_temperature: float = 0.3
    reflection_temperature: float = 0.3
    max_tokens: int = 4096
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    planner_thinking_mode: bool = False
    critic_thinking_mode: bool = False
    enable_planner: bool = False
    enable_tools: bool = True
    enable_critic: bool = True
    enable_reflection: bool = True
    max_tool_rounds: int = 3
    enable_fallback: bool = True
    critic_always: bool = True


class ReasoningAgent:
    """增强版数学推理智能体 v6。"""

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client

    def _chat(self, system_prompt: str, user_content: str, **kwargs) -> str:
        """调用 client.chat，返回文本。"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_content})
        resp = self.client.chat(messages=messages, **kwargs)
        return resp if isinstance(resp, str) else str(resp.get("content", ""))

    def solve(self, problem: str, metadata: Dict) -> Dict:
        """主求解流程。全局 try-except 防空答案。"""
        idx = metadata.get("idx", 0)
        trace: List[Dict] = []
        try:
            return self._solve_impl(problem, idx, trace)
        except Exception as e:
            trace.append({"step": "global_error", "content": f"{type(e).__name__}: {str(e)[:300]}"})
            fb = self._quick_fallback(problem, trace)
            return {"final_response": fb or "未解出", "trace": trace}

    def _solve_impl(self, problem: str, idx: int, trace: List[Dict]) -> Dict:
        # 阶段1：关键词检测领域（不花API调用）
        domain_name = self._detect_domain(problem)
        domain_prompt = get_domain_prompt(domain_name)
        if domain_name:
            trace.append({"step": "domain_detect", "content": f"关键词识别: {domain_name}"})

        # 阶段2：多候选生成
        candidates, gen_trace = self._generate_candidates(problem, idx, domain_prompt)
        trace.extend(gen_trace)

        # 截断兜底
        if not candidates or all(not self._extract_answer(c) for c in candidates):
            trace.append({"step": "truncated_fallback", "content": "所有候选被截断"})
            if self.config.enable_fallback:
                fb = self._quick_fallback(problem, trace)
                if fb:
                    return {"final_response": fb, "trace": trace}

        # 阶段3：验证投票
        scored = []
        for cid, candidate in enumerate(candidates):
            confidence, vt = self._verify(problem, candidate, idx, cid)
            answer = self._extract_answer(candidate)
            scored.append({
                "content": candidate, "confidence": confidence + (0.3 if answer else -0.5),
                "answer": answer, "raw_confidence": confidence,
            })
            trace.extend(vt)

        # 阶段4：Critic + 反思（v10：回退到仅低置信度触发，省API+减截断）
        if self.config.enable_critic and scored:
            best = max(scored, key=lambda x: x["confidence"])
            if best["raw_confidence"] < 0.5 and best["answer"]:
                criticism = self._critic(problem, best["content"], trace)
                if criticism and "NO ERROR" not in criticism.upper():
                    refined = self._reflect(problem, best["content"], criticism, trace)
                    if refined:
                        rc, rv = self._verify(problem, refined, idx, len(candidates))
                        ra = self._extract_answer(refined)
                        scored.append({
                            "content": refined, "confidence": rc + (0.3 if ra else -0.5),
                            "answer": ra, "raw_confidence": rc,
                        })
                        trace.extend(rv)

        # 阶段5：聚合
        final_answer = self._aggregate(scored, trace)
        if not final_answer and scored:
            final_answer = self._extract_answer(scored[0]["content"]) or "未解出"

        # v6：final_response 包含推理过程
        best_content = max(scored, key=lambda x: x["confidence"])["content"] if scored else ""
        final_response = self._build_response(best_content, final_answer)

        return {"final_response": final_response or final_answer or "未解出", "trace": trace}

    def _build_response(self, content: str, answer: str) -> str:
        if not content:
            return answer or "未解出"
        if "最终答案" in content:
            return content.strip()
        return f"{content.strip()}\n最终答案：{answer}"

    def _generate_candidates(self, problem: str, idx: int, domain_prompt: str) -> Tuple[List[str], List[Dict]]:
        candidates, trace = [], []
        for i in range(self.config.tool_candidates):
            if self.config.enable_tools:
                cand, tt = self._solve_tools(problem, idx, i, domain_prompt)
                candidates.append(cand)
                trace.extend(tt)
            else:
                cand = self._solve_plain(problem, domain_prompt)
                candidates.append(cand)
                trace.append({"step": f"policy_tool_{i}", "content": cand[:1000]})
        for i in range(self.config.plain_candidates):
            cand = self._solve_plain(problem, domain_prompt)
            candidates.append(cand)
            trace.append({"step": f"policy_plain_{i}", "content": cand[:1000]})
        return [c for c in candidates if c], trace

    def _solve_tools(self, problem: str, idx: int, cid: int, domain_prompt: str) -> Tuple[str, List[Dict]]:
        try:
            messages = [
                {"role": "system", "content": domain_prompt or POLICY_PROMPT},
                {"role": "user", "content": f"{problem}\n\n请调用工具验证关键计算。候选编号：{cid}"},
            ]
            response, tt = run_tool_loop(
                self.client, messages,
                max_rounds=self.config.max_tool_rounds,
                thinking_mode=self.config.policy_thinking_mode,
                temperature=self.config.policy_temperature,
                max_tokens=self.config.max_tokens,
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
        except Exception as e:
            trace = [{"step": f"tool_error_{cid}", "content": str(e)[:200]}]
            return self._solve_plain(problem, domain_prompt), trace

    def _solve_plain(self, problem: str, domain_prompt: str) -> str:
        try:
            prefix = domain_prompt or POLICY_NO_TOOL_PROMPT
            return self._chat(prefix, f"{problem}\n\n请给出完整解答。",
                              temperature=self.config.policy_temperature,
                              max_tokens=self.config.max_tokens,
                              thinking_mode=self.config.policy_thinking_mode)
        except Exception:
            return ""

    def _verify(self, problem: str, candidate: str, idx: int, cid: int) -> Tuple[float, List[Dict]]:
        votes, trace = [], []
        for vid in range(self.config.verifier_voting_times):
            try:
                verdict = self._chat(VERIFIER_PROMPT,
                    f"题目：\n{problem}\n\n候选解答：\n{candidate[:3000]}\n\n判断是否正确。只输出：VERDICT: A 或 VERDICT: B",
                    temperature=self.config.verifier_temperature,
                    max_tokens=self.config.verifier_max_tokens,
                    thinking_mode=self.config.verifier_thinking_mode)
                votes.append(self._is_correct(verdict))
                trace.append({"step": f"verify_{cid}_{vid}", "content": verdict[:200]})
            except Exception as e:
                votes.append(False)
                trace.append({"step": f"verify_err_{cid}_{vid}", "content": str(e)[:200]})
        return (sum(votes) / len(votes) if votes else 0.0), trace

    def _critic(self, problem: str, candidate: str, trace: List[Dict]) -> str:
        try:
            criticism = self._chat(CRITIC_PROMPT,
                f"题目：\n{problem}\n\n候选解答：\n{candidate[:3000]}\n\n请找出错误或改进点。",
                temperature=self.config.critic_temperature,
                max_tokens=self.config.critic_max_tokens,
                thinking_mode=self.config.critic_thinking_mode)
            trace.append({"step": "critic", "content": criticism[:500]})
            return criticism
        except Exception as e:
            trace.append({"step": "critic_error", "content": str(e)[:200]})
            return ""

    def _reflect(self, problem: str, prev: str, feedback: str, trace: List[Dict]) -> str:
        try:
            prompt = REFLECTION_PROMPT.format(problem=problem, prev_answer=prev[:2000], feedback=feedback[:500])
            resp = self._chat(POLICY_PROMPT, prompt,
                              temperature=self.config.reflection_temperature,
                              max_tokens=self.config.max_tokens,
                              thinking_mode=self.config.policy_thinking_mode)
            trace.append({"step": "reflection", "content": resp[:1000]})
            return resp
        except Exception as e:
            trace.append({"step": "reflect_error", "content": str(e)[:200]})
            return ""

    def _aggregate(self, scored: List[Dict], trace: List[Dict]) -> str:
        if not scored:
            return ""
        with_ans = [s for s in scored if s["answer"]]
        if not with_ans:
            best = max(scored, key=lambda x: x["confidence"])
            return self._normalize(best["content"].strip()[:500])
        for s in with_ans:
            s["norm"] = self._normalize(s["answer"])
            s["num"] = self._numeric(s["norm"])
        groups = {}
        for s in with_ans:
            key = s["num"] if s["num"] is not None else s["norm"]
            groups.setdefault(key, []).append(s)
        best_key = max(groups, key=lambda k: (len(groups[k]), max(s["confidence"] for s in groups[k])))
        bg = groups[best_key]
        if len(bg) >= 2:
            trace.append({"step": "self_consistency", "content": f"答案 '{bg[0]['norm']}' 获得 {len(bg)} 票"})
            return bg[0]["norm"]
        best = max(with_ans, key=lambda x: x["confidence"])
        trace.append({"step": "select_final", "content": f"选最高分: {best['norm']}"})
        return best["norm"]

    # 关键词→领域映射（不花API调用，秒判领域）
    _DOMAIN_KEYWORDS = {
        "抽象代数": ["群", "环", "域", "理想", "有限域", "伽罗瓦", "正规子群", "商群", "同态", "循环群"],
        "数论": ["同余", "素数", "互素", "欧拉函数", "费马", "威尔逊", "中国剩余", "CRT", "模", "整除"],
        "线性代数": ["矩阵", "行列式", "特征值", "特征向量", "秩", "线性空间", "向量空间", "特征多项式", "正交", "对角化"],
        "实分析": ["级数", "收敛", "勒贝格", "一致收敛", "ε-δ", "夹逼", "柯西序列", "完备"],
        "复分析": ["留数", "柯西", "解析函数", "极点", "整函数", "洛朗", "泰勒展开", "复变", "全纯"],
        "微积分": ["导数", "积分", "极限", "偏导", "全微分", "链式法则", "分部积分", "换元", "反函数"],
        "微分方程": ["常微分", "ODE", "齐次方程", "特解", "通解", "初值问题", "边界条件"],
        "偏微分方程": ["偏微分", "PDE", "分离变量", "热传导", "波动方程", "拉普拉斯", "傅里叶级数", "边界条件"],
        "泛函分析": ["Banach", "Hilbert", "赋范", "内积空间", "有界算子", "谱", "压缩映射", "不动点"],
        "测度积分": ["测度", "Lebesgue", "可测", "σ代数", "反函数积分", "绝对连续", "Radon"],
        "几何": ["三角形", "圆", "面积", "体积", "角度", "切线", "相似", "全等", "正弦定理", "余弦定理"],
        "微分几何": ["曲率", "测地线", "第一基本形式", "第二基本形式", "Frenet", "挠率", "高斯曲率"],
        "拓扑": ["基本群", "同伦", "同调", "拓扑空间", "连通", "紧致", "开集", "闭集", "欧拉示性数"],
        "代数几何": ["仿射簇", "射影", "概形", "Bezout", "齐次坐标", "代数曲线", "除子"],
        "运筹学": ["线性规划", "对偶", "最优", "目标函数", "约束", "可行域", "KKT", "单纯形"],
        "概率论": ["概率", "期望", "方差", "分布", "贝叶斯", "马尔可夫", "随机变量", "独立"],
        "组合": ["排列", "组合", "容斥", "生成函数", "Catalan", "二项式", "计数"],
        "离散数学": ["图论", "树", "顶点", "边", "哈密顿", "欧拉回路", "二分图", "递推", "布尔"],
    }

    def _detect_domain(self, problem: str) -> str:
        """关键词匹配检测数学子领域，不花API调用。"""
        scores = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in problem)
            if score > 0:
                scores[domain] = score
        if scores:
            return max(scores, key=scores.get)
        return ""

    def _quick_fallback(self, problem: str, trace: List[Dict]) -> str:
        try:
            resp = self._chat(POLICY_NO_TOOL_PROMPT,
                f"{problem}\n\n请直接给出最终答案，不要详细推导。格式：最终答案：XXX",
                temperature=0.0, max_tokens=self.config.fallback_max_tokens, thinking_mode=False)
            ans = self._extract_answer(resp)
            trace.append({"step": "fallback_result", "content": ans[:100]})
            return ans or resp.strip()[:200]
        except Exception:
            return ""

    @staticmethod
    def _extract_answer(text: str) -> str:
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
        if not answer: return ""
        s = answer.strip()
        s = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", s)
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\dfrac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", s)
        s = re.sub(r"\\(?:mathbb|text|mathrm|mathcal)\{([^{}]*)\}", r"\1", s)
        s = s.replace("\\left","").replace("\\right","").replace("$","")
        return s.rstrip("。.，,；;").strip("\"'""''").strip()

    @staticmethod
    def _numeric(s: str) -> float | None:
        try:
            if "/" in s:
                p = s.split("/")
                if len(p) == 2: return float(p[0]) / float(p[1])
            return float(s)
        except: return None

    @staticmethod
    def _is_correct(verdict: str) -> bool:
        m = re.findall(r"\bVERDICT\s*[:：]\s*([AB])", verdict, re.IGNORECASE)
        if m: return m[-1].upper() == "A"
        m = re.findall(r"^\s*([AB])\s*$", verdict, re.IGNORECASE | re.MULTILINE)
        if m: return m[-1].upper() == "A"
        words = re.findall(r"\b[A-Z]+\b", verdict.upper())
        return "CORRECT" in words and "INCORRECT" not in words
