"""R1 bounded state/serialization invariants and fixed incident regressions."""
import ast
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import types

import pytest

import user_agent as runtime
from user_agent import AgentConfig, ReasoningAgent
from local_support.xh202627_local_adapter import LocalToolAdapter

ROOT = Path(__file__).resolve().parents[1]


class SequenceClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0

    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        self.calls += 1
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def solve_sequence(responses, **options):
    client = SequenceClient(responses)
    config = AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False)
    legacy = options.pop("legacy", False)
    for key, value in options.items():
        setattr(config, key, value)
    kwargs = {"local_policy": runtime.legacy_deployment_policy()} if legacy else {}
    result = ReasoningAgent(client, config, **kwargs).solve("计算1+1", {})
    assert client.calls <= config.max_model_requests
    assert type(result["trace"]) is list
    return result, client.calls


@pytest.mark.parametrize("response", [None, [], 3, {"content": None}, {"content": []}])
def test_invalid_transport_response_fails_closed_without_retry(response):
    result, calls = solve_sequence([response])
    assert result["final_response"] == "未解出"
    assert calls == 1


@pytest.mark.parametrize("stage", ["generation", "verification", "critic", "reflection"])
def test_stage_length_never_becomes_answer_or_positive_vote(stage):
    cut = {"content": "最终答案：999", "finish_reason": "length"}
    responses = {
        "generation": [cut, "最终答案：2"],
        "verification": ["最终答案：2", {"content": "VERDICT: A", "finish_reason": "length"}],
        "critic": ["最终答案：2", "VERDICT: B", cut],
        "reflection": ["最终答案：2", "VERDICT: B", "请修正计算", cut],
    }[stage]
    result, calls = solve_sequence(responses, enable_critic=stage in ("critic", "reflection"), legacy=True)
    assert result["final_response"].endswith("最终答案：2")
    assert "999" not in result["final_response"]
    assert calls == len(responses)
    if stage == "verification":
        assert any(item["step"].startswith("verify_unknown") for item in result["trace"])


@pytest.mark.parametrize("recovery", ["", "因此我们还需要计算", "最终答案：", r"\boxed{2",
    {"content": "最终答案：999", "finish_reason": "length"}, RuntimeError("fake failure")])
def test_recovery_failure_cannot_revive_isolated_content(recovery):
    result, calls = solve_sequence(["残文" * 2000, recovery], legacy=True)
    assert result["final_response"] == "未解出"
    assert calls == 2


@pytest.mark.parametrize("budget", [1, 2, 3, 4])
def test_recovery_and_verification_share_request_budget(budget):
    result, calls = solve_sequence(["残文" * 2000, "最终答案：2"], max_model_requests=budget, legacy=True)
    assert calls == min(budget, 2)
    assert result["final_response"] == ("未解出" if budget == 1 else "最终答案：2")


@pytest.mark.parametrize("tools", [0, 1])
def test_transport_failure_does_not_trigger_plain_retry(tools):
    result, calls = solve_sequence([PermissionError("synthetic private diagnostic")],
                                  tool_candidates=tools, plain_candidates=1-tools)
    assert result["final_response"] == "未解出"
    assert calls == 1


def test_verification_transport_failure_does_not_trigger_critic_retry():
    result, calls = solve_sequence(["最终答案：2", PermissionError("fake")], enable_critic=True, legacy=True)
    assert result["final_response"] == "未解出"
    assert calls == 2


@pytest.mark.parametrize("method", ["_detect_domain", "_generate_candidates", "_aggregate", "_build_response"])
def test_faults_at_every_lifecycle_boundary_return_stable_result(method, monkeypatch):
    client = SequenceClient(["最终答案：2", "VERDICT: A"])
    agent = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False),
                           local_policy=runtime.legacy_deployment_policy())
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic private diagnostic")
    monkeypatch.setattr(agent, method, fail)
    result = agent.solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert "synthetic" not in json.dumps(result["trace"])
    assert client.calls == (0 if method in ("_detect_domain", "_generate_candidates") else 2)
    assert runtime._ACTIVE_BUDGET.get() is None


@pytest.mark.parametrize("name,value", [("max_model_requests", 0), ("max_total_tokens", -1),
    ("problem_timeout_seconds", float("nan")), ("tool_candidates", "3"),
    ("max_metadata_chars", True), ("policy_temperature", float("inf"))])
def test_bad_local_config_fails_before_request(name, value):
    client = SequenceClient([])
    config = AgentConfig()
    setattr(config, name, value)
    result = ReasoningAgent(client, config).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert client.calls == 0


@pytest.mark.parametrize("secret", ["Bearer FAKE_TOKEN", "sk-FAKE_TOKEN", "INTERN_API_KEY=FAKE",
    "authorization: FAKE", "私有题面FAKE", "fake-person@example.invalid"])
@pytest.mark.parametrize("offset", [0, 299, 301, 4000])
def test_public_trace_is_content_independent_and_idempotent(secret, offset):
    untrusted = "x" * offset + secret
    trace = [
        {"step": "policy_plain_0", "content": untrusted},
        {"step": "tool_solve_0", "content": [{"step": "nested", "content": untrusted}]},
        {"step": "select_final", "content": untrusted},
        {"step": "self_consistency", "content": untrusted},
        {"step": "global_error", "content": untrusted},
        {"step": untrusted, "content": untrusted},
    ]
    public = runtime._public_trace(trace)
    assert secret not in json.dumps(public, ensure_ascii=False)
    assert runtime._public_trace(public) == public
    assert all(len(item["content"]) <= 300 for item in public)
    assert len(public) == 5


def test_metadata_does_not_override_known_transport_truncation():
    text = runtime._response_text({"content": "最终答案：999", "finish_reason": None},
                                  {"finish_reason": "length"})
    assert ReasoningAgent._extract_answer(text) == ""


def test_local_finish_reason_reaches_generation_and_recovery():
    class Client:
        def __init__(self):
            self.calls = 0
        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            self.calls += 1
            meta_sink({"usage": {"total_tokens": 7}, "finish_reason": "length"})
            return "最终答案：999"
    client = Client()
    result = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1),
                            local_adapter=LocalToolAdapter(client),
                            local_policy=runtime.legacy_deployment_policy()).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert client.calls == 2
    assert result["trace"][-1]["content"]["total_tokens"] == 14


def test_tool_terminal_request_accounts_usage_and_finish_reason():
    from budget import ExecutionBudget
    class Client:
        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            meta_sink({"usage": {"total_tokens": 19}, "finish_reason": "length"})
            return "最终答案：999"
    budget = ExecutionBudget()
    adapter = LocalToolAdapter(Client())
    text, trace, metadata = adapter.run_tools([], 0, 10, 0, 5, budget)
    assert text == "最终答案：999"
    assert metadata["finish_reason"] == "length"
    assert budget.model_requests == 1
    assert budget.total_tokens == 19


def test_same_agent_concurrent_solve_has_separate_usage_and_budget():
    class Client:
        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            amount = 11 if "ONE" in messages[-1]["content"] else 29
            meta_sink({"usage": {"total_tokens": amount}})
            return "最终答案：2"
    client = Client()
    agent = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False),
                           local_adapter=LocalToolAdapter(client),
                           local_policy=runtime.legacy_deployment_policy())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda p: agent.solve(p, {}), ["ONE", "TWO"]))
    assert [r["trace"][-1]["content"]["total_tokens"] for r in results] == [22, 58]
    assert [r["trace"][-1]["content"]["model_requests"] for r in results] == [2, 2]
    assert runtime._ACTIVE_BUDGET.get() is None


def test_local_tool_execution_through_formal_entry_preserves_request_accounting():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            self.calls += 1
            meta_sink({"usage": {"total_tokens": 15}, "finish_reason": "stop"})
            if self.calls == 1:
                assert kwargs["tools"]
                return {"role": "assistant", "content": "", "tool_calls": [{
                    "id": "calculate-1", "type": "function", "function": {
                        "name": "calculate", "arguments": '{"expression": "1+1"}',
                    },
                }]}
            if self.calls == 2:
                answers = [m["content"] for m in messages if m.get("role") == "tool"]
                assert answers == ["2"]
                return "最终答案：2"
            return "VERDICT: A"

    client = Client()
    config = AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    result = ReasoningAgent(client, config, local_adapter=LocalToolAdapter(client),
                            local_policy=runtime.legacy_deployment_policy()).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")
    assert client.calls == 3
    summary = result["trace"][-1]["content"]
    assert summary["model_requests"] == 3
    assert summary["tool_calls"] == 1
    assert summary["total_tokens"] == 45


def test_complete_formal_pollution_matrix_preserves_external_modules(monkeypatch):
    names = ["llm_client", "agent_types", "answer_equivalence", "budget", "math_tools",
             "tool_executor", "domain_prompts", "deterministic_verifier", "local_support"]
    foreign = {name: types.ModuleType(name) for name in names}
    for name, module in foreign.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("xh202627_matrix_entry", ROOT / "user_agent.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    result = module.ReasoningAgent(SequenceClient(["最终答案：2"] * 16)).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")
    assert all(sys.modules[name] is old for name, old in foreign.items())
    for loaded in module._dependencies.values():
        assert loaded.__name__.startswith("xh202627_runtime_")
        assert Path(loaded.__file__).resolve().parent == ROOT


def test_prompts_and_default_config_are_unchanged_from_reviewed_baseline():
    before = subprocess.run(["git", "show", "2cf691f:user_agent.py"], cwd=ROOT,
        check=True, capture_output=True, text=True, encoding="utf-8").stdout
    def frozen(source):
        tree = ast.parse(source)
        result = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "AgentConfig":
                result[node.name] = ast.dump(node)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.endswith("_PROMPT"):
                        result[target.id] = ast.dump(node)
        return result
    baseline = frozen(before)
    current = frozen((ROOT / "user_agent.py").read_text(encoding="utf-8"))
    # Dated user decisions authorize B2, the evidence-first verifier, and the
    # 2026-09-10 evening one-call complete-question answer-bank check. Every
    # original prompt and the entire AgentConfig AST remain frozen; an additional
    # unreviewed prompt still fails this exact allowlist.
    assert set(current) == set(baseline) | {
        "CONCISE_RECOVERY_PROMPT", "REASONED_VERIFIER_PROMPT", "ANSWER_BANK_CHECK_PROMPT",
        "V2_ROUTE_PROMPT", "V2_REVIEW_PROMPT", "V2_REPAIR_PROMPT"}
    assert {name: current[name] for name in baseline} == baseline
    assert runtime.Q1Policy().concise_recovery is False

    class Client:
        def __init__(self):
            self.calls = []
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert (temperature, max_tokens, thinking_mode) == (0.0, 512, False)
            self.calls.append(messages)
            return "最终答案：2"
    calls = []
    # Deployment was explicitly promoted on 2026-09-10. Keep the historical
    # all-off regression explicit; the ordinary deployed entry is tested apart.
    for policy in (runtime.Q1Policy(), runtime.Q1Policy(concise_recovery=True)):
        client = Client()
        agent = runtime.ReasoningAgent(client, local_policy=policy)
        assert agent._quick_fallback("synthetic task", []) == "2"
        assert len(client.calls) == 1
        calls.append(client.calls[0])
    assert calls[0][0]["content"] == runtime.POLICY_NO_TOOL_PROMPT
    assert calls[1][0]["content"] == runtime.CONCISE_RECOVERY_PROMPT
    assert calls[0][1:] == calls[1][1:]
