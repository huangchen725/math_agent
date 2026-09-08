"""B1 prompt capability regressions. Synthetic replies are not accuracy evidence."""
import copy
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import random
import sys
import types

import pytest

import domain_prompts as domains
import user_agent as runtime


class StrictClient:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = iter(replies) if replies is not None else None

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        assert thinking_mode is False
        assert 1 <= max_tokens <= 8192
        self.calls.append(copy.deepcopy(dict(messages=messages, temperature=temperature,
            max_tokens=max_tokens, thinking_mode=thinking_mode)))
        if self.replies is not None:
            return next(self.replies)
        return "VERDICT: A" if "验证器" in messages[0]["content"] else "推导完成。\n最终答案：2"

    def __getattr__(self, name):
        raise AssertionError("Unexpected client capability probe: " + name)


def assert_no_tool_instructions(text):
    for marker in ("调用工具", "【推荐工具】", "solve_equation", "differentiate", "integrate ", "calculate "):
        assert marker not in text


def test_default_domain_prompts_match_frozen_baseline():
    hashes = json.loads((Path(__file__).parent / "fixtures" / "b1_default_domain_hashes.json").read_text(encoding="utf-8"))
    assert set(hashes) == {*domains.DOMAIN_PROMPTS, "", "unmatched-domain"}
    for domain, expected in hashes.items():
        assert sha256(domains.get_domain_prompt(domain).encode()).hexdigest() == expected
    for alias, domain in domains.DOMAIN_ALIASES.items():
        assert domains.get_domain_prompt(alias) == domains.get_domain_prompt(domain)


def test_text_rendering_preserves_all_math_content_and_examples():
    originals = copy.deepcopy(domains.DOMAIN_PROMPTS)
    for name in (*originals, "", "unmatched-domain", *domains.DOMAIN_ALIASES):
        before = domains.get_domain_prompt(name)
        after = domains.text_only_domain_prompt(before)
        assert_no_tool_instructions(after)
        # Independent invariant: every line except explicit tool instructions
        # remains at the same position, including formulas and few-shot examples.
        assert len(before.splitlines()) == len(after.splitlines())
        for old, new in zip(before.splitlines(), after.splitlines()):
            if "调用工具" not in old and "【推荐工具】" not in old:
                assert old == new
        assert domains.text_only_domain_prompt(after) == after
    assert domains.DOMAIN_PROMPTS == originals


@pytest.mark.parametrize("enable_tools", [True, False])
@pytest.mark.parametrize("extra", [{}, {"compact_routing": True}, {"diverse_candidates": True}])
def test_all_generation_sources_use_text_prompts(enable_tools, extra):
    for name in (*domains.DOMAIN_PROMPTS, ""):
        client = StrictClient()
        agent = runtime.ReasoningAgent(client, runtime.AgentConfig(enable_tools=enable_tools),
            local_policy=runtime.Q1Policy(tool_aware_prompts=True, **extra))
        # Fix the route, not the generation path, to cover every domain exactly.
        agent._detect_domain = lambda problem, selected=name: selected
        result = agent.solve("synthetic arithmetic task", {"answer": "PRIVATE_REFERENCE_999"})
        assert result["final_response"].endswith("最终答案：2")
        assert len(client.calls) == 6
        for call in client.calls[:3]:
            assert_no_tool_instructions(call["messages"][0]["content"])
            assert_no_tool_instructions(call["messages"][1]["content"])
            assert call["max_tokens"] == 8192
        assert [c["temperature"] for c in client.calls[:3]] == [0.6, 0.6, 0.8 if extra.get("diverse_candidates") else 0.6]
        assert "PRIVATE_REFERENCE_999" not in json.dumps(client.calls)


def test_historical_stop_at_tool_text_is_not_an_answer():
    tool_text = '{"name":"integrate","arguments":{"expression":"x","variable":"x"}}'
    runs = []
    for enabled in (False, True):
        # Two tool-source recoveries, then the final recovery, already exist.
        client = StrictClient([{"content": tool_text, "finish_reason": "stop"}, "",
            {"content": tool_text, "finish_reason": "stop"}, "",
            {"content": tool_text, "finish_reason": "stop"}, ""])
        result = runtime.ReasoningAgent(client,
            local_policy=runtime.Q1Policy(tool_aware_prompts=enabled)).solve("synthetic integral task", {})
        assert result["final_response"] == "未解出"
        assert all(c["thinking_mode"] is False for c in client.calls)
        runs.append(client.calls)
    assert len(runs[0]) == len(runs[1]) == 6
    assert [c["max_tokens"] for c in runs[1]] == [8192, 512, 8192, 512, 8192, 512]


def test_b1_does_not_rewrite_problem_or_leak_metadata():
    rng = random.Random(908)
    for _ in range(24):
        problem = "题面引用：调用工具 / solve_equation / 【推荐工具】 " + "".join(rng.choices("xy0123[]{}\\\n", k=80))
        client = StrictClient()
        runtime.ReasoningAgent(client, local_policy=runtime.Q1Policy(tool_aware_prompts=True)).solve(
            problem, {"answer": "SECRET_REFERENCE"})
        for call in client.calls[:3]:
            assert call["messages"][-1]["content"].startswith(problem + "\n\n")
        assert "SECRET_REFERENCE" not in json.dumps(client.calls)


@pytest.mark.parametrize("enabled", [False, True])
def test_explicit_adapter_keeps_real_tool_prompts_but_plain_stage_has_no_tools(enabled):
    class Adapter:
        def __init__(self):
            self.tools = []
            self.text = StrictClient()

        def run_tools(self, *, messages, max_rounds, temperature, max_tokens, tool_timeout_seconds, budget):
            self.tools.append(copy.deepcopy(messages))
            return "最终答案：2", [], {"finish_reason": "stop"}

        def complete(self, *, messages, temperature, max_tokens, thinking_mode):
            return {"response": self.text.chat(messages=messages, temperature=temperature,
                max_tokens=max_tokens, thinking_mode=thinking_mode), "metadata": {"finish_reason": "stop"}}

    adapter = Adapter()
    agent = runtime.ReasoningAgent(StrictClient([]), local_adapter=adapter,
        local_policy=runtime.Q1Policy(tool_aware_prompts=enabled))
    agent._detect_domain = lambda problem: "微积分"
    assert agent.solve("synthetic task", {})["final_response"] == "最终答案：2"
    assert len(adapter.tools) == 2
    for cid, messages in enumerate(adapter.tools):
        assert messages == [{"role": "system", "content": domains.get_domain_prompt("微积分")},
            {"role": "user", "content": f"synthetic task\n\n请调用工具验证关键计算。候选编号：{cid}"}]
    plain_system = adapter.text.calls[0]["messages"][0]["content"]
    if enabled:
        assert_no_tool_instructions(plain_system)
    else:
        assert plain_system == domains.get_domain_prompt("微积分")


def test_b1_only_changes_generation_messages_not_verifier_or_config():
    snapshots = []
    for enabled in (False, True):
        client = StrictClient()
        config = runtime.AgentConfig()
        before = asdict(config)
        result = runtime.ReasoningAgent(client, config,
            local_policy=runtime.Q1Policy(tool_aware_prompts=enabled)).solve("计算1+1", {})
        assert asdict(config) == before
        snapshots.append((client.calls, result))
    old, new = snapshots[0][0], snapshots[1][0]
    assert len(old) == len(new) == 6
    assert old[3:] == new[3:]
    for a, b in zip(old, new):
        assert {k: v for k, v in a.items() if k != "messages"} == {k: v for k, v in b.items() if k != "messages"}
    assert snapshots[0][1]["final_response"] == snapshots[1][1]["final_response"]


def test_b1_with_foreign_preloads_uses_strict_public_client(monkeypatch):
    names = ("llm_client", "agent_types", "budget", "domain_prompts", "answer_equivalence", "math_tools")
    foreign = {name: types.ModuleType(name) for name in names}
    for name, module in foreign.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("b1_audit_entry", Path(runtime.__file__))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    client = StrictClient()
    result = module.ReasoningAgent(client,
        local_policy=module.Q1Policy(tool_aware_prompts=True)).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")
    assert len(client.calls) == 6
    assert all(sys.modules[name] is original for name, original in foreign.items())


@pytest.mark.parametrize("value", [None, "false", 0, 1, {}, []])
def test_b1_invalid_switch_is_rejected_before_first_request(value):
    client = StrictClient([])
    result = runtime.ReasoningAgent(client,
        local_policy=runtime.Q1Policy(tool_aware_prompts=value)).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert not client.calls
