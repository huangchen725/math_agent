"""增强版数学推理智能体 v17 —— 回退到v13最优架构。

v17 = v13架构(thinking=False+8192+2工具+1纯推理+简单投票) + 微分几何修复
v6→v10→v13 三次成功都是简单配置；v7/v11/v15/v16 四次失败都是加了复杂度
结论：v13是最优，不再加复杂功能

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

REFLECTION_PROMPT = """你之前的解答可能有误。请根据反馈重新解答。

原题：{problem}
之前的解答：{prev_answer}
批评反馈：{feedback}

请修正错误，给出完整推理和最终答案。"""


@dataclass
class AgentConfig:
    """智能体配置（v17：回退v13最优架构）。"""
    # 候选生成：v13配置（全部温度0.6，不加多温度）
    tool_candidates: int = 2
    plain_candidates: int = 1
    verifier_voting_times: int = 1
    # 温度
    policy_temperature: float = 0.6
    planner_temperature: float = 0.2
    verifier_temperature: float = 0.0
    critic_temperature: float = 0.3
    reflection_temperature: float = 0.3
    # token
    max_tokens: int = 8192
    verifier_max_tokens: int = 1024
    critic_max_tokens: int = 1024
    fallback_max_tokens: int = 512
    # v1.2：题级自适应 max_tokens（证明题上探、短答案压缩，官方 cap 8192 / 默认 4096）
    adaptive_max_tokens: bool = True
    prove_max_tokens: int = 8192      # 证明题/解析题：需保留完整证明
    compute_max_tokens: int = 4096    # 常规计算/方程/微积分/概率
    short_max_tokens: int = 2048      # 选择/填空/短答案
    # thinking mode（v13: False——thinking导致截断）
    policy_thinking_mode: bool = False
    verifier_thinking_mode: bool = False
    planner_thinking_mode: bool = False
    critic_thinking_mode: bool = False
    # 功能开关
    enable_tools: bool = True
    enable_critic: bool = True
    enable_reflection: bool = True
    enable_fallback: bool = True
    max_tool_rounds: int = 3


class ReasoningAgent:
    """增强版数学推理智能体 v17——v13最优架构。"""

    def __init__(self, client: InternChatClient, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.client = client
        self._max_tokens = None  # v1.2：每题求解时由 _resolve_max_tokens 决定，供各策略复用

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
        # 阶段0（v1.2）：题级自适应 max_tokens + 题型判定（本地规则，不花 API）
        self._max_tokens = self._resolve_max_tokens(problem)
        task_type = self._detect_task_type(problem)
        trace.append({"step": "task_profile", "content": f"type={task_type}, max_tokens={self._max_tokens}"})

        # 阶段1：关键词检测领域
        domain_name = self._detect_domain(problem)
        domain_prompt = get_domain_prompt(domain_name)
        if domain_name:
            trace.append({"step": "domain_detect", "content": f"关键词识别: {domain_name}"})

        # 阶段2：多候选生成（全部温度0.6，v13配置）
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
                "content": candidate,
                "confidence": confidence + (0.3 if answer else -0.5),
                "answer": answer,
                "raw_confidence": confidence,
            })
            trace.extend(vt)

        # 阶段4：Critic + 反思（仅低置信度触发）
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
                            "content": refined,
                            "confidence": rc + (0.3 if ra else -0.5),
                            "answer": ra,
                            "raw_confidence": rc,
                            "temp": 0.3,
                        })
                        trace.extend(rv)

        # 阶段6：加权聚合
        final_answer = self._aggregate(scored, trace)
        if not final_answer and scored:
            final_answer = self._extract_answer(scored[0]["content"]) or "未解出"

        best_content = max(scored, key=lambda x: x["confidence"])["content"] if scored else ""
        final_response = self._build_response(best_content, final_answer, task_type)

        return {"final_response": final_response or final_answer or "未解出", "trace": trace}

    def _build_response(self, content: str, answer: str, task_type: str = "compute") -> str:
        """v1.2：题型化收敛 final_response。

        - 选择/填空：精简为"最终答案：XXX"（judger 只需选项/结果）
        - 证明/计算：保留完整 content（含关键推导步骤，官方要求证明题给完整证明）
        """
        if not content:
            return answer or "未解出"
        if task_type in ("choice", "fill"):
            return f"最终答案：{answer}" if answer else content.strip()
        if "最终答案" in content:
            return content.strip()
        return f"{content.strip()}\n最终答案：{answer}"

    def _generate_candidates(self, problem: str, idx: int, domain_prompt: str) -> Tuple[List[str], List[Dict]]:
        """v17：回退v13——全部温度0.6，简单候选生成。"""
        candidates, trace = [], []
        for i in range(self.config.tool_candidates):
            if self.config.enable_tools:
                cand, tt = self._solve_tools(problem, idx, i, domain_prompt)
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
                max_tokens=self._active_max_tokens(),
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
            err_msg = str(e)[:200]
            # v1.2：区分超时与其它错误，超时降级到纯推理，不重复相同工具请求
            step = f"tool_timeout_{cid}" if ("timeout" in err_msg.lower() or "failed after" in err_msg.lower()) else f"tool_error_{cid}"
            trace = [{"step": step, "content": err_msg}]
            return self._solve_plain(problem, domain_prompt), trace

    def _solve_plain(self, problem: str, domain_prompt: str) -> str:
        try:
            prefix = domain_prompt or POLICY_NO_TOOL_PROMPT
            return self._chat(prefix, f"{problem}\n\n请给出完整解答。",
                              temperature=self.config.policy_temperature,
                              max_tokens=self._active_max_tokens(),
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
                              max_tokens=self._active_max_tokens(),
                              thinking_mode=self.config.policy_thinking_mode)
            trace.append({"step": "reflection", "content": resp[:1000]})
            return resp
        except Exception as e:
            trace.append({"step": "reflect_error", "content": str(e)[:200]})
            return ""

    def _aggregate(self, scored: List[Dict], trace: List[Dict]) -> str:
        """v17：回退v13——简单多数投票。"""
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
            trace.append({"step": "self_consistency", "content": f"答案 '{bg[0]['norm']}' 获得 {len(bg)} 票一致"})
            return bg[0]["norm"]
        best = max(with_ans, key=lambda x: x["confidence"])
        trace.append({"step": "select_final", "content": f"选最高分: {best['norm']}"})
        return best["norm"]

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
        scores = {}
        for domain, keywords in self._DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in problem)
            if score > 0:
                scores[domain] = score
        if scores:
            return max(scores, key=scores.get)
        return ""

    def _detect_task_type(self, problem: str) -> str:
        """本地规则判定题型（v1.2，不花 API 调用）。

        返回 prove / choice / fill / compute。
        """
        if re.search(r"证明|求证|show\s+that|prove\b|verify\s+that", problem, re.IGNORECASE):
            return "prove"
        # 选择题：出现 (A)/(B)/(C)/(D) 或 A. B. C. D. 选项
        if re.search(r"[（(]\s*[ABCD]\s*[)）]", problem) or re.search(r"\b[ABCD]\.\s", problem):
            return "choice"
        # 填空题：下划线占位
        if re.search(r"[_＿]{2,}|填空|___", problem):
            return "fill"
        return "compute"

    def _resolve_max_tokens(self, problem: str) -> int:
        """题级自适应 max_tokens（v1.2）。

        证明题上探 8192 以保留完整证明；选择/填空压缩到 2048；其余用 4096。
        官方规则：不传默认 4096、硬 cap 8192。
        """
        if not self.config.adaptive_max_tokens:
            return self.config.max_tokens
        task_type = self._detect_task_type(problem)
        if task_type == "prove":
            return self.config.prove_max_tokens
        if task_type in ("choice", "fill"):
            return self.config.short_max_tokens
        return self.config.compute_max_tokens

    def _active_max_tokens(self) -> int:
        """当前题生效的 max_tokens（各策略统一复用，避免重复计算）。"""
        return self._max_tokens or self.config.max_tokens

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
        """v12稳定版——不做激进转换。"""
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
        """v12稳定版。"""
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
