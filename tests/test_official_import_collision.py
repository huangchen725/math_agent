"""Regression for the official llm_client preload order.

This test intentionally exercises the restored historical runtime without
changing it. Post-anchor runtimes must add the stricter three-argument gate
defined in docs/ENGINEERING_SPECIFICATION.md.
"""

import importlib.util
import sys
import types
from pathlib import Path


def test_official_llm_client_preload_does_not_block_first_request(monkeypatch):
    calls = []
    official_module = types.ModuleType("llm_client")

    class OfficialInternChatClient:
        def chat(self, messages, **kwargs):
            calls.append({"messages": messages, "kwargs": kwargs})
            system_text = "\n".join(
                message.get("content", "")
                for message in messages
                if message.get("role") == "system"
            )
            if "数学答案验证器" in system_text:
                return "VERDICT: A"
            if "数学解题批评者" in system_text:
                return "NO ERROR"
            return "推理：2+2=4。\n最终答案：4"

    official_module.InternChatClient = OfficialInternChatClient
    monkeypatch.setitem(sys.modules, "llm_client", official_module)

    root = Path(__file__).resolve().parents[1]
    module_name = "recovery_user_agent_collision_test"
    spec = importlib.util.spec_from_file_location(module_name, root / "user_agent.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)

    client = OfficialInternChatClient()
    result = module.ReasoningAgent(client).solve("计算 2+2。", {})

    assert len(calls) == 6
    assert result["final_response"].endswith("最终答案：4")
    assert not hasattr(client, "chat_with_metadata")
