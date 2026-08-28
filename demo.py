"""数学智能体交互 Demo（Gradio）。

展示推理全过程：领域路由 → 候选生成 → 工具调用 → 验证投票 → 答案聚合。
只读展示，不控制正式评测请求，不暴露 API key / 敏感 Prompt。

运行：python demo.py
"""
import os
import sys
from collections import defaultdict

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from dotenv import load_dotenv
load_dotenv(os.path.join(BASE, ".env"))

import gradio as gr

from llm_client import InternChatClient
from user_agent import ReasoningAgent


def _classify_step(step_name: str) -> str:
    """把 trace 步骤归类到推理阶段。"""
    if "domain" in step_name or "task_profile" in step_name:
        return "① 领域路由"
    if "tool_solve" in step_name or "policy_tool" in step_name:
        return "② 候选生成（工具）"
    if "policy_plain" in step_name:
        return "② 候选生成（纯推理）"
    if "verify" in step_name:
        return "③ 验证投票"
    if "critic" in step_name or "reflect" in step_name:
        return "④ 反思纠错"
    if "self_consistency" in step_name or "select_final" in step_name or "aggregate" in step_name:
        return "⑤ 答案聚合"
    if "fallback" in step_name or "truncated" in step_name or "error" in step_name:
        return "⚠️ 兜底/异常"
    return "其他"


def solve_problem(problem: str):
    """求解题目，返回 (最终答案, 推理过程 markdown, 统计摘要)。"""
    if not problem or not problem.strip():
        return "请输入题目", "（等待输入）", ""
    try:
        client = InternChatClient()
        agent = ReasoningAgent(client=client)
        result = agent.solve(problem=problem, metadata={"idx": 0})
    except Exception as e:
        return f"求解失败：{type(e).__name__}: {e}", "（无推理过程）", ""

    final_response = result.get("final_response", "")
    trace = result.get("trace", [])

    # 按阶段分组
    groups = defaultdict(list)
    for step in trace:
        phase = _classify_step(step.get("step", ""))
        content = str(step.get("content", ""))
        groups[phase].append(content)

    lines = ["## 推理过程\n"]
    for phase in ["① 领域路由", "② 候选生成（工具）", "② 候选生成（纯推理）",
                  "③ 验证投票", "④ 反思纠错", "⑤ 答案聚合", "⚠️ 兜底/异常", "其他"]:
        if phase in groups:
            lines.append(f"### {phase}")
            for c in groups[phase]:
                lines.append(f"- {c[:300]}")
            lines.append("")

    # 统计摘要
    stats = f"总步骤 {len(trace)} 步"
    return final_response, "\n".join(lines), stats


with gr.Blocks(title="数学智能体推理 Demo") as demo:
    gr.Markdown("# 数学智能体推理 Demo")
    gr.Markdown("输入数学题，查看智能体完整的推理链路（领域路由 → 工具调用 → 验证投票 → 答案聚合）。")

    with gr.Row():
        problem_input = gr.Textbox(
            label="题目",
            lines=4,
            placeholder="例如：设函数 f(z)=1/((z-1)(z-2)^2)，求 f(z) 在 z=1 处的留数。",
        )
    with gr.Row():
        solve_btn = gr.Button("求解", variant="primary")
    with gr.Row():
        answer_output = gr.Textbox(label="最终答案（final_response）", lines=3)
    with gr.Row():
        stats_output = gr.Textbox(label="统计", lines=1)
    trace_output = gr.Markdown("推理过程将显示在这里")

    solve_btn.click(
        solve_problem,
        inputs=[problem_input],
        outputs=[answer_output, trace_output, stats_output],
    )


if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
