"""B1/B2 prompt regressions. Synthetic replies are not accuracy evidence."""
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


@pytest.mark.parametrize("policy", [{"tool_aware_prompts": True}, {"concise_recovery": True},
    {"tool_aware_prompts": True, "concise_recovery": True}])
def test_prompt_policies_with_foreign_preloads_use_strict_public_client(monkeypatch, policy):
    names = ("llm_client", "agent_types", "budget", "domain_prompts", "answer_equivalence", "math_tools")
    foreign = {name: types.ModuleType(name) for name in names}
    for name, module in foreign.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("b1_audit_entry", Path(runtime.__file__))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    recovery = policy.get("concise_recovery")
    client = StrictClient(["未完成", "最终答案：2"] if recovery else None)
    config = module.AgentConfig(tool_candidates=0, plain_candidates=1) if recovery else module.AgentConfig()
    result = module.ReasoningAgent(client, config,
        local_policy=module.Q1Policy(**policy)).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")
    assert len(client.calls) == (2 if recovery else 6)
    assert all(sys.modules[name] is original for name, original in foreign.items())


@pytest.mark.parametrize("value", [None, "false", 0, 1, {}, []])
def test_b1_invalid_switch_is_rejected_before_first_request(value):
    client = StrictClient([])
    result = runtime.ReasoningAgent(client,
        local_policy=runtime.Q1Policy(tool_aware_prompts=value)).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert not client.calls


@pytest.mark.parametrize("route,config,other,replies,expected_requests", [
    ("tool_source", {"tool_candidates": 1, "plain_candidates": 0}, {},
        ["未完成", "最终答案：2", "VERDICT: A"], 3),
    ("plain_source", {"tool_candidates": 0, "plain_candidates": 1}, {"recover_plain": True},
        ["未完成", "最终答案：2", "VERDICT: A"], 3),
    ("final_recovery", {"tool_candidates": 0, "plain_candidates": 1}, {},
        ["未完成", "最终答案：2"], 2),
])
@pytest.mark.parametrize("b1", [False, True])
def test_b2_only_changes_recovery_system_prompt_on_every_route(route, config, other, replies, expected_requests, b1):
    runs = []
    for enabled in (False, True):
        client = StrictClient(replies)
        settings = runtime.AgentConfig(**config)
        before = asdict(settings)
        result = runtime.ReasoningAgent(client, settings, local_policy=runtime.Q1Policy(
            concise_recovery=enabled, tool_aware_prompts=b1, **other)).solve("synthetic task", {})
        assert result["final_response"] == "最终答案：2"
        assert asdict(settings) == before
        assert len(client.calls) == expected_requests
        runs.append(client.calls)
    changed = 0
    for old, new in zip(*runs):
        if new["max_tokens"] != 512:
            assert old == new
            continue
        changed += 1
        assert new["temperature"] == 0.0 and new["thinking_mode"] is False
        assert old["messages"][0]["content"] == runtime.POLICY_NO_TOOL_PROMPT
        assert new["messages"][0]["content"] == runtime.CONCISE_RECOVERY_PROMPT
        assert "只输出一行" in new["messages"][0]["content"]
        assert "1. 解题思路" not in new["messages"][0]["content"]
        unchanged = copy.deepcopy(new)
        unchanged["messages"][0] = old["messages"][0]
        assert unchanged == old  # Includes the entire question and user directive.
    assert changed == 1


@pytest.mark.parametrize("response,expected", [
    ({"content": "最终答案：2", "finish_reason": "stop"}, "最终答案：2"),
    ("最终答案：2", "最终答案：2"),
    ({"content": "最终答案：2", "finish_reason": "length"}, "未解出"),
    ({"content": None, "finish_reason": "length"}, "未解出"),
    ({"content": None, "finish_reason": "stop"}, "未解出"),
    ({"content": "最终答案：2", "finish_reason": "content_filter"}, "未解出"),
    ("", "未解出"), ("最终答案：", "未解出"),
    ('{"name":"integrate"}', "未解出"), ("最终答案：\\[2", "未解出"),
])
def test_b2_never_relaxes_response_qualification_or_retries(response, expected):
    client = StrictClient(["未完成", response])
    result = runtime.ReasoningAgent(client,
        runtime.AgentConfig(tool_candidates=0, plain_candidates=1),
        local_policy=runtime.Q1Policy(concise_recovery=True)).solve("synthetic task", {})
    assert result["final_response"] == expected
    assert len(client.calls) == 2
    assert client.calls[-1]["max_tokens"] == 512


@pytest.mark.parametrize("fallback_enabled,request_limit,expected_calls", [(True, 1, 1), (True, 2, 2), (False, 16, 1)])
def test_b2_keeps_fallback_switch_and_request_budget(fallback_enabled, request_limit, expected_calls):
    client = StrictClient(["未完成", ""])
    result = runtime.ReasoningAgent(client,
        runtime.AgentConfig(tool_candidates=0, plain_candidates=1, enable_fallback=fallback_enabled,
            max_model_requests=request_limit), local_policy=runtime.Q1Policy(concise_recovery=True)).solve(
                "synthetic task", {})
    assert result["final_response"] == "未解出"
    assert len(client.calls) == expected_calls


def test_b2_is_inert_without_recovery_including_critic_and_reflection():
    replies = ["最终答案：2"]*3 + ["VERDICT: B"]*3 + ["请复核", "最终答案：2", "VERDICT: A"]
    runs = []
    for enabled in (False, True):
        client = StrictClient(replies)
        runtime.ReasoningAgent(client, local_policy=runtime.Q1Policy(concise_recovery=enabled)).solve("synthetic task", {})
        assert len(client.calls) == 9
        assert all(call["max_tokens"] != 512 for call in client.calls)
        runs.append(client.calls)
    assert runs[0] == runs[1]


def test_b2_adapter_metadata_cannot_hide_truncated_answer():
    class Adapter:
        def __init__(self):
            self.calls = []
        def complete(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False
            self.calls.append(messages)
            return {"response": {"content": "最终答案：2", "finish_reason": "stop"},
                "metadata": {"finish_reason": "length"}}
    adapter = Adapter()
    result = runtime.ReasoningAgent(StrictClient([]),
        runtime.AgentConfig(tool_candidates=0, plain_candidates=1), local_adapter=adapter,
        local_policy=runtime.Q1Policy(concise_recovery=True)).solve("synthetic task", {})
    assert result["final_response"] == "未解出"
    assert len(adapter.calls) == 2
    assert adapter.calls[-1][0]["content"] == runtime.CONCISE_RECOVERY_PROMPT


@pytest.mark.parametrize("value", [None, "false", 0, 1, {}, []])
def test_b2_invalid_switch_is_rejected_before_first_request(value):
    client = StrictClient([])
    result = runtime.ReasoningAgent(client,
        local_policy=runtime.Q1Policy(concise_recovery=value)).solve("synthetic task", {})
    assert result["final_response"] == "未解出"
    assert not client.calls
