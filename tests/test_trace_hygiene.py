"""R1-3 regression: public trace sanitization.

These tests fail before R1-3 lands: every string recorded into the trace
must be clipped through a single helper with an explicit truncation marker,
and the serialized trace must never contain credential-like material.
"""


class LongResponseClient:
    """产生超长模型输出的 fake client，用于触发 trace 截断路径。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        system_text = "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "system"
        )
        if "数学答案验证器" in system_text:
            return "VERDICT: B"
        if "数学解题批评者" in system_text:
            return "发现计算错误：" + "推导细节" * 2000
        user_text = "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "user"
        )
        if "重新解答" in user_text:
            return "反思推理" * 2000 + "\n最终答案：2"
        return "逐步推理" * 1500 + "\n最终答案：2"


def _walk_trace_strings(trace):
    for item in trace:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if isinstance(content, str):
            yield item.get("step", ""), content
        elif isinstance(content, list):
            for sub in content:
                if isinstance(sub, dict) and isinstance(sub.get("content"), str):
                    yield f"{item.get('step', '')}/{sub.get('step', '')}", sub["content"]


def test_trace_string_content_is_clipped():
    from user_agent import AgentConfig, ReasoningAgent

    client = LongResponseClient()
    config = AgentConfig(
        tool_candidates=1,
        plain_candidates=0,
        verifier_voting_times=1,
        enable_critic=True,
    )
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    assert result["trace"]
    for _step, content in _walk_trace_strings(result["trace"]):
        assert len(content) <= 400, f"trace step {_step} exceeds clip limit: {len(content)}"


def test_trace_serialization_contains_no_credential_material():
    import json

    from user_agent import AgentConfig, ReasoningAgent

    client = LongResponseClient()
    config = AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=True)
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    serialized = json.dumps(result["trace"], ensure_ascii=False, default=str)
    for marker in ("Bearer ", "INTERN_API_KEY", "sk-", "authorization"):
        assert marker.lower() not in serialized.lower()
