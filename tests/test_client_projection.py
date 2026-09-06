"""Public client contract regression.

Historically R1-1 projected the public client contract to three arguments
(messages/temperature/max_tokens). On 2026-09-06 the contract was amended
with official evaluation evidence: the 9/5 run (ba63ac0) proved the platform
client accepts extended keywords (112/112 success, 0 errors), while the 9/6
run (c009929) proved the three-argument protocol is catastrophic with
Intern-S2-Preview-397B, whose default thinking chain burned the max_tokens
budget (84% truncated requests, 52 invalid answers). The public contract now
allows exactly messages, temperature, max_tokens and thinking_mode; tool
transport keywords (tools, tool_choice) remain local-adapter-only extras
tolerated by the guard. No dynamic kwargs, no last-response metadata side
channel.
"""

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / ".agents" / "policy_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("client_projection_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StrictPublicClient:
    """chat 只接受公开协议命名参数：无 **kwargs，也不提供任何元数据 getter。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature, max_tokens, thinking_mode=None,
             tools=None, tool_choice=None):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "thinking_mode": thinking_mode,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
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


def test_solve_uses_only_public_protocol_arguments():
    from user_agent import AgentConfig, ReasoningAgent

    client = StrictPublicClient()
    config = AgentConfig(tool_candidates=1, plain_candidates=1, enable_critic=False)
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    assert client.calls, "solve must issue at least one model request"
    for call in client.calls:
        assert set(call) <= {
            "messages", "temperature", "max_tokens",
            "thinking_mode", "tools", "tool_choice",
        }


def test_solve_always_disables_thinking_mode():
    from user_agent import AgentConfig, ReasoningAgent

    client = StrictPublicClient()
    config = AgentConfig(tool_candidates=1, plain_candidates=1, enable_critic=False)
    ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert client.calls, "solve must issue at least one model request"
    for call in client.calls:
        # 397B 默认思维链会吃满 max_tokens（9/6 评测 84% 截断），
        # 因此所有请求必须显式关闭 thinking。
        assert call["thinking_mode"] is False


def test_solve_tolerates_client_without_metadata_getter():
    from user_agent import AgentConfig, ReasoningAgent

    client = StrictPublicClient()
    assert not hasattr(client, "get_last_response_meta")
    config = AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")


def test_runtime_sources_pass_client_contract_scan():
    guard = _load_guard()
    manifest = guard.load_manifest()

    for path in ("user_agent.py", "math_tools.py", "verify_math.py", "llm_client.py"):
        text = (ROOT / path).read_text(encoding="utf-8")
        findings = guard.scan_python_text(path, text, manifest)
        assert findings == []


def test_user_agent_no_longer_imports_llm_client():
    text = (ROOT / "user_agent.py").read_text(encoding="utf-8")

    assert "from llm_client import" not in text
    assert "import llm_client" not in text
