"""Independent acceptance probes for commit 2cf691f; fake data, no network."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor

import pytest

from user_agent import AgentConfig, ReasoningAgent

ROOT = Path(__file__).resolve().parents[1]
RESIDUE = "推导尚未完成" * 600
SYNTHETIC_SECRET = "Bearer FAKE_ACCEPTANCE_TOKEN_NOT_A_REAL_SECRET"


class FakeClient:
    def __init__(self, policy="推理。\n最终答案：2", fallback="", reflect=None):
        self.policy = policy
        self.fallback = fallback
        self.reflect = reflect
        self.calls = 0

    def chat(self, messages, temperature, max_tokens, **kwargs):
        self.calls += 1
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if "数学答案验证器" in system:
            return "VERDICT: A" if RESIDUE in user else "VERDICT: B"
        if "数学解题批评者" in system:
            return "请重新计算"
        if "请直接给出最终答案" in user:
            return self.fallback
        if "你之前的解答可能有误" in user and self.reflect is not None:
            return self.reflect
        return self.policy


def agent(client, **kwargs):
    return ReasoningAgent(client, AgentConfig(
        tool_candidates=0, plain_candidates=1, enable_critic=False, **kwargs
    ))


def test_wide_constructor_accepts_unknown_keywords():
    result = ReasoningAgent(FakeClient(), runner_context=object()).solve("计算1+1", {})
    assert isinstance(result["final_response"], str)


def test_wide_constructor_accepts_extra_positionals():
    result = ReasoningAgent(FakeClient(), object(), object()).solve("计算1+1", {})
    assert isinstance(result["final_response"], str)


def test_unknown_second_argument_does_not_become_config():
    result = ReasoningAgent(FakeClient(), {"runner": "opaque"}).solve("计算1+1", {})
    assert isinstance(result["final_response"], str)


def test_public_trace_removes_synthetic_secret():
    result = agent(FakeClient(policy=SYNTHETIC_SECRET + "\n最终答案：2")).solve("计算1+1", {})
    assert SYNTHETIC_SECRET not in json.dumps(result["trace"], ensure_ascii=False)


def test_public_trace_bounds_answer_selection_event():
    result = agent(FakeClient(policy="最终答案：" + "x" * 1500)).solve("求x", {})
    for item in result["trace"]:
        if isinstance(item.get("content"), str):
            assert len(item["content"]) <= 400, item["step"]


def test_budget_initialization_failure_stays_inside_solve():
    client = FakeClient()
    result = agent(client, max_model_requests=0).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert client.calls == 0


def test_metadata_recursion_failure_stays_inside_solve():
    metadata = {}
    for _ in range(5000):
        metadata = {"x": metadata}
    client = FakeClient()
    result = agent(client).solve("计算1+1", metadata)
    assert result["final_response"] == "未解出"
    assert client.calls == 0


def test_isolated_candidates_stay_isolated_when_recovery_empty():
    result = agent(FakeClient(policy=RESIDUE, fallback="")).solve("计算1+1", {})
    assert result["final_response"] == "未解出"


def test_incomplete_recovery_is_not_published_as_answer():
    result = agent(FakeClient(policy=RESIDUE, fallback="因此我们还需要计算")).solve("计算1+1", {})
    assert result["final_response"] == "未解出"


def test_reflection_obeys_same_truncation_isolation():
    client = FakeClient(reflect=RESIDUE)
    # Both original and truncated reflection receive B; extraction must not give
    # the reflection a new answer even if another verifier later changes votes.
    original_chat = client.chat

    def chat(messages, temperature, max_tokens, **kwargs):
        if "数学答案验证器" in messages[0]["content"] and "推导尚未完成" in messages[-1]["content"]:
            client.calls += 1
            return "VERDICT: A"
        return original_chat(messages, temperature, max_tokens, **kwargs)

    client.chat = chat
    result = ReasoningAgent(client, AgentConfig(
        tool_candidates=0, plain_candidates=1, enable_critic=True,
    )).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")


@pytest.mark.parametrize("name", ["agent_types", "answer_equivalence", "budget", "math_tools", "domain_prompts"])
def test_preloaded_foreign_runtime_module(name, monkeypatch):
    monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    spec = importlib.util.spec_from_file_location("acceptance_polluted_entry", ROOT / "user_agent.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    result = module.ReasoningAgent(FakeClient()).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")


def test_entry_loads_by_path_outside_repository(tmp_path):
    # Formal entry must load by its file path with only the standard library available.
    program = f"""
import sys, importlib.util
spec = importlib.util.spec_from_file_location('acceptance_entry', {str(ROOT / 'user_agent.py')!r})
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
"""
    result = subprocess.run([sys.executable, "-I", "-c", program], cwd=tmp_path,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


def test_local_adapter_usage_is_per_concurrent_request():
    from local_support.xh202627_local_adapter import LocalToolAdapter

    first_recorded = threading.Event()
    second_recorded = threading.Event()

    class InterleavingClient:
        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            amount = messages[0]["content"]
            if amount == 11:
                meta_sink({"usage": {"total_tokens": 11}})
                first_recorded.set()
                assert second_recorded.wait(5)
            else:
                assert first_recorded.wait(5)
                meta_sink({"usage": {"total_tokens": 29}})
                second_recorded.set()
            return "最终答案：2"

    adapter = LocalToolAdapter(InterleavingClient())

    def call(amount):
        result = adapter.complete(messages=[{"content": amount}], temperature=0, max_tokens=1)
        return result["metadata"]["usage"]["total_tokens"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(call, 11)
        second = executor.submit(call, 29)
        observed = (first.result(), second.result())
    assert observed == (11, 29)


def test_strict_client_with_private_attribute_trap_passes():
    class PublicOnlyClient:
        def __getattribute__(self, name):
            if name != "chat":
                raise AssertionError("Unexpected client attribute access: " + name)
            return object.__getattribute__(self, name)

        def chat(self, *, messages, temperature, max_tokens, **kwargs):
            if "数学答案验证器" in messages[0]["content"]:
                return "VERDICT: A"
            return "最终答案：2"

    result = ReasoningAgent(PublicOnlyClient()).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")


def test_root_file_copy_imports_when_loader_provides_root_path(tmp_path):
    manifest = json.loads((ROOT / ".agents/policies/policy_manifest.json").read_text())
    for name in manifest["runtime_files"]:
        shutil.copy2(ROOT / name, tmp_path / name)
    program = f"""
import sys
sys.path.insert(0, {str(tmp_path)!r})
from user_agent import ReasoningAgent
class Client:
    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        return '最终答案：2'
assert ReasoningAgent(Client()).solve('计算1+1', {{}})['final_response'].endswith('最终答案：2')
"""
    result = subprocess.run([sys.executable, "-I", "-c", program], cwd=tmp_path,
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
