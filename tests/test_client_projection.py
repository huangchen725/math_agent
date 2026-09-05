"""R1-1 regression: the public client contract is projected to three arguments.

These tests fail before the CLIENT-001 projection lands and enforce the
strict fake-client gate defined in docs/ENGINEERING_SPECIFICATION.md
(TEST-CLIENT-001): chat must receive exactly messages, temperature and
max_tokens, with no dynamic kwargs, no extension arguments and no
last-response metadata side channel.
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


class StrictThreeArgumentClient:
    """chat 只接受三个命名参数：无 **kwargs，也不提供任何元数据 getter。"""

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature, max_tokens):
        self.calls.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
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


def test_solve_uses_exactly_three_public_chat_arguments():
    from user_agent import AgentConfig, ReasoningAgent

    client = StrictThreeArgumentClient()
    config = AgentConfig(tool_candidates=1, plain_candidates=1, enable_critic=False)
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    assert client.calls, "solve must issue at least one model request"
    for call in client.calls:
        assert set(call) == {"messages", "temperature", "max_tokens"}


def test_solve_tolerates_client_without_metadata_getter():
    from user_agent import AgentConfig, ReasoningAgent

    client = StrictThreeArgumentClient()
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
