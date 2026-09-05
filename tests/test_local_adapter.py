"""R1-2 regression: wide constructor with an explicit local adapter (CLIENT-002).

These tests fail before R1-2 lands: usage accounting and the local tool path
must be restored through an explicitly injected adapter, never through
capability probing on the injected client. The adapter lives outside the
formal entry import graph (``local_support/``) per CLIENT-002.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RecordingClient:
    """替身 InternChatClient：支持 meta_sink 与扩展参数并记录每次调用。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature=None, max_tokens=None, *,
             thinking_mode=None, tools=None, tool_choice=None, meta_sink=None):
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "thinking_mode": thinking_mode,
            "tools": tools,
            "tool_choice": tool_choice,
        })
        if meta_sink is not None:
            meta_sink({
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
            })
        system_text = "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "system"
        )
        if "数学答案验证器" in system_text:
            return "VERDICT: A"
        if "数学解题批评者" in system_text:
            return "NO ERROR"
        return "推理：1+1=2。\n最终答案：2"


def _make_agent(config):
    from user_agent import ReasoningAgent

    client = RecordingClient()
    adapter = _make_adapter(client)
    return ReasoningAgent(client, config, local_adapter=adapter), client


def _make_adapter(client):
    from local_support.xh202627_local_adapter import LocalToolAdapter

    return LocalToolAdapter(client)


def test_wide_constructor_restores_usage_accounting():
    from user_agent import AgentConfig

    config = AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False)
    agent, _client = _make_agent(config)

    result = agent.solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    summary = result["trace"][-1]
    assert summary["step"] == "budget_summary"
    assert summary["content"]["total_tokens"] > 0


def test_wide_constructor_restores_tool_path_without_thinking_mode():
    from user_agent import AgentConfig

    config = AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    agent, client = _make_agent(config)

    result = agent.solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    tool_calls = [call for call in client.calls if call["tools"] is not None]
    assert tool_calls, "tool candidates must receive tool definitions through the adapter"
    assert all(call["thinking_mode"] is None for call in client.calls)


def test_without_adapter_tool_calls_stay_three_argument():
    from user_agent import AgentConfig, ReasoningAgent

    client = RecordingClient()
    config = AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    assert client.calls
    assert all(call["tools"] is None for call in client.calls)
    assert all(call["thinking_mode"] is None for call in client.calls)
