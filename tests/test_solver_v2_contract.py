"""New deployment gates; these tests never select a historical policy fixture."""

from concurrent.futures import ThreadPoolExecutor
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

import user_agent as runtime


ROOT = Path(__file__).resolve().parents[1]


def test_new_default_six_source_outside_load_with_all_foreign_modules_and_opaque_inputs(tmp_path):
    source = tmp_path / "six_sources"
    working = tmp_path / "judge_working_directory"
    source.mkdir()
    working.mkdir()
    names = ("user_agent.py", "agent_types.py", "budget.py", "domain_prompts.py",
             "answer_equivalence.py", "xh202627_corpus.py")
    assert ("user_agent.py", *runtime._FORMAL_SOURCE_FILES) == names
    for name in names:
        shutil.copyfile(ROOT / name, source / name)
    # One isolated interpreter exercises the simultaneous pollution matrix and
    # real new-controller route/selection behavior, without a repository on path.
    program = r'''
import importlib.util
import json
from pathlib import Path
import sys
import types

root = Path(sys.argv[1]).resolve()
names = ["llm_client", "agent_types", "answer_equivalence", "budget", "math_tools",
         "tool_executor", "domain_prompts", "deterministic_verifier", "local_support",
         "xh202627_corpus", "agent", "context", "solver", "client", "model_gateway"]
foreign = {name: types.ModuleType(name) for name in names}
for name, module in foreign.items():
    module.sentinel = "foreign-owned"
    sys.modules[name] = module

calls = []
review = {"checks": [
    {"candidate": 1, "status": "refuted", "reason": "First candidate omits the required boundary condition.",
     "missing_goals": [], "condition_errors": ["boundary omitted"]},
    {"candidate": 2, "status": "supported", "reason": "Second candidate checks the complete stated conditions.",
     "missing_goals": [], "condition_errors": []}],
    "selected": 2, "disagreement": "Boundary condition determines the candidate selection.",
    "repair": False, "calculations": []}
responses = iter(["Derivation one.\n最终答案：17", "Derivation two.\n最终答案：23",
                  "<selection>" + json.dumps(review) + "</selection>"])

class OfficialInternChatClient:
    def __getattribute__(self, name):
        if name != "chat":
            raise AssertionError("Client capability/private lookup: " + name)
        return object.__getattribute__(self, name)

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        assert thinking_mode is False
        assert type(max_tokens) is int and 1 <= max_tokens <= 8192
        assert len(messages) == 2
        calls.append({"messages": messages, "temperature": temperature,
                      "max_tokens": max_tokens, "thinking_mode": thinking_mode})
        return next(responses)

foreign["llm_client"].InternChatClient = OfficialInternChatClient

class OpaqueJudgeConfig:
    def __getattribute__(self, name):
        raise AssertionError("Opaque judge object inspected: " + name)
    def __repr__(self):
        raise AssertionError("Opaque judge object rendered")
    def __str__(self):
        raise AssertionError("Opaque judge object rendered")

spec = importlib.util.spec_from_file_location("xh202627_v2_contract_entry", root / "user_agent.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
agent = module.ReasoningAgent(OfficialInternChatClient(), OpaqueJudgeConfig(),
                             OpaqueJudgeConfig(), judge_context=OpaqueJudgeConfig(),
                             local_policy=OpaqueJudgeConfig())
assert agent.local_policy.solver_v2 is True
assert module.ReasoningAgent.__module__ == spec.name
assert type(agent.config) is module.AgentConfig
assert agent.config.max_model_requests == 16
result = agent.solve("Find the requested mathematical object with its boundary conditions.",
                     {"answer": "PRIVATE_LABEL_NEVER_TRANSMITTED", "idx": "../judge-output"})
assert result["final_response"].endswith("最终答案：23"), result
assert len(calls) == 3, calls
assert calls[0]["messages"][0]["content"].startswith(module.V2_ROUTE_PROMPT)
assert calls[1]["messages"][0]["content"].startswith(module.V2_ROUTE_PROMPT)
assert calls[2]["messages"][0]["content"].startswith(module.V2_REVIEW_PROMPT)
assert "PRIVATE_LABEL_NEVER_TRANSMITTED" not in json.dumps(calls)
steps = [item["step"] for item in result["trace"]]
assert "v2_route_1" in steps and "v2_route_2" in steps and "v2_review" in steps
assert "v2_retrieval_unavailable" in steps
assert all(sys.modules[name] is old and old.sentinel == "foreign-owned" for name, old in foreign.items())
assert foreign["llm_client"].InternChatClient is OfficialInternChatClient
assert not (root / "resources").exists()
assert {p.name for p in root.glob("*.py")} == {"user_agent.py", *module._FORMAL_SOURCE_FILES}
assert all(dep.__name__.startswith("xh202627_runtime_") and Path(dep.__file__).resolve().parent == root
           for dep in module._dependencies.values())
assert str(root) not in sys.path
assert str(Path.cwd()) not in sys.path
assert module._ACTIVE_BUDGET.get() is None
print(json.dumps({"foreign_modules": len(foreign), "formal_sources": 6,
                  "public_requests": len(calls), "solver_v2": agent.local_policy.solver_v2}))
'''
    result = subprocess.run([sys.executable, "-I", "-c", program, str(source)],
                            cwd=working, capture_output=True, text=True,
                            encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "foreign_modules": 15, "formal_sources": 6, "public_requests": 3, "solver_v2": True,
    }


def _empty_retrieval(monkeypatch):
    monkeypatch.setattr(runtime._dependencies["xh202627_corpus"], "build_evidence_plan", lambda problem: {
        "status": "miss", "reference": "", "methods": "", "exact_record": None, "counters": {},
    })


def _budget(result):
    return next(item["content"] for item in result["trace"] if item["step"] == "budget_summary")


def _review(count=2):
    return "<selection>" + json.dumps({
        "checks": [{"candidate": number, "status": "supported", "reason": "All stated mathematical conditions have been checked.",
                    "missing_goals": [], "condition_errors": []} for number in range(1, count + 1)],
        "selected": count, "disagreement": "No unresolved discrepancy in the independently obtained answers.",
        "repair": False, "calculations": [],
    }) + "</selection>"


def test_same_default_agent_interleaving_isolates_usage_private_metadata_and_raw_math_plans(monkeypatch):
    _empty_retrieval(monkeypatch)
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    calls = {"CASE_A": [], "CASE_B": []}

    class StrictPublicClient:
        def __getattr__(self, name):
            raise AssertionError("Private capability access: " + name)

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False and 1 <= max_tokens <= 8192
            user = messages[-1]["content"]
            case = "CASE_A" if "CASE_A" in user else "CASE_B"
            other = "CASE_B" if case == "CASE_A" else "CASE_A"
            assert other not in user
            with lock:
                calls[case].append(copy.deepcopy(messages))
                ordinal = len(calls[case])
            if ordinal == 1:
                barrier.wait(timeout=5)
            if messages[0]["content"].startswith(runtime.V2_REVIEW_PROMPT):
                assert "PRIVATE_PLAN_" + case in user
                return _review()
            plan = {"goals": ["requested object"], "conditions": ["PRIVATE_PLAN_" + case],
                    "method": "independent direct derivation", "obligations": [],
                    "calculations": [{"id": "numeric_check", "task": {"op": "evaluate", "expr": 101 if case == "CASE_A" else 103},
                                      "expected": "101" if case == "CASE_A" else "103"}]}
            answer = "11" if case == "CASE_A" else "29"
            return "<solver_plan>" + json.dumps(plan) + "</solver_plan>\nComplete derivation.\n最终答案：" + answer

    client = StrictPublicClient()

    class ExplicitLocalMetadataAdapter:
        # This is an explicit local adapter, never discovered by client probing.
        def complete(self, *, messages, temperature, max_tokens, thinking_mode):
            response = client.chat(messages=messages, temperature=temperature,
                                   max_tokens=max_tokens, thinking_mode=thinking_mode)
            amount = 11 if "CASE_A" in messages[-1]["content"] else 29
            return {"response": response, "metadata": {
                "usage": {"total_tokens": amount}, "finish_reason": "stop",
                "debug": "PRIVATE_PROVIDER_METADATA", "authorization": "FAKE_PRIVATE_METADATA",
            }}

    agent = runtime.ReasoningAgent(client, local_adapter=ExplicitLocalMetadataAdapter())
    assert agent.local_policy.solver_v2 is True

    def solve(case):
        result = agent.solve("Find the mathematical object for " + case, {
            "answer": "PRIVATE_LABEL_" + case, "token": "FAKE_SOLVE_METADATA",
        })
        assert runtime._ACTIVE_BUDGET.get() is None
        assert runtime._ACTIVE_ANSWER_REFERENCE.get() == ""
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(solve, ("CASE_A", "CASE_B")))
    assert [len(calls[case]) for case in ("CASE_A", "CASE_B")] == [3, 3]
    assert [result["final_response"].splitlines()[-1] for result in results] == ["最终答案：11", "最终答案：29"]
    assert [_budget(result)["total_tokens"] for result in results] == [33, 87]
    assert [_budget(result)["model_requests"] for result in results] == [3, 3]
    assert [_budget(result)["tool_calls"] for result in results] == [2, 2]
    all_requests = json.dumps(calls)
    for secret in ("PRIVATE_LABEL_CASE_A", "PRIVATE_LABEL_CASE_B", "FAKE_SOLVE_METADATA",
                   "PRIVATE_PROVIDER_METADATA", "FAKE_PRIVATE_METADATA"):
        assert secret not in all_requests
        assert secret not in json.dumps(results)
    for result in results:
        trace = json.dumps(result["trace"])
        assert "PRIVATE_PLAN_" not in trace and "solver_plan" not in trace and "numeric_check" not in trace
        assert "PRIVATE_PLAN_" not in result["final_response"]
        assert runtime._public_trace(result["trace"]) == result["trace"]
    assert runtime._ACTIVE_BUDGET.get() is None


@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE_MID_ROUTE_ERROR"), {"content": None}])
def test_new_default_budget_records_midroute_failure_and_preserves_complete_candidate(monkeypatch, failure):
    _empty_retrieval(monkeypatch)
    calls = []
    responses = iter(["Complete derivation.\n最终答案：23", failure])

    class Client:
        def __getattribute__(self, name):
            if name != "chat":
                raise AssertionError("Unexpected client inspection: " + name)
            return object.__getattribute__(self, name)

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False
            calls.append(messages)
            result = next(responses)
            if isinstance(result, Exception):
                raise result
            return result

    agent = runtime.ReasoningAgent(Client())
    assert agent.local_policy.solver_v2 is True
    result = agent.solve("Find the specified abstract mathematical object.", {})
    assert len(calls) == _budget(result)["model_requests"] == 2
    assert result["final_response"].endswith("最终答案：23")
    assert "v2_transport_stop" in [item["step"] for item in result["trace"]]
    assert "PRIVATE_MID_ROUTE_ERROR" not in json.dumps(result)
    assert runtime._ACTIVE_BUDGET.get() is None


@pytest.mark.parametrize("kind", ["tokens", "tool_calls", "deadline"])
def test_new_default_budget_stop_after_first_answer_keeps_it_under_original_limits(monkeypatch, kind):
    _empty_retrieval(monkeypatch)
    calls = []
    configuration = runtime.AgentConfig(max_total_tokens=10, max_tool_calls=1)
    tasks = [{"id": "c" + str(i), "task": {"op": "evaluate", "expr": i}, "expected": str(i)} for i in (1, 2)]
    plan = {"goals": ["requested object"], "conditions": [], "method": "direct derivation",
            "obligations": [], "calculations": tasks}
    response = ("<solver_plan>" + json.dumps(plan) + "</solver_plan>\n" if kind == "tool_calls" else "") + "最终答案：23"

    class PublicClient:
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False
            calls.append(messages)
            if kind == "deadline":
                # Advance only this solve's budget clock; never sleep or change
                # the process clock used by concurrently running checks.
                budget = runtime._ACTIVE_BUDGET.get()
                budget.started_at -= budget.timeout_seconds + 1
            return response

    client = PublicClient()

    class ExplicitUsageAdapter:
        def complete(self, *, messages, temperature, max_tokens, thinking_mode):
            text = client.chat(messages=messages, temperature=temperature,
                               max_tokens=max_tokens, thinking_mode=thinking_mode)
            return {"response": text, "metadata": {"usage": {"total_tokens": 10 if kind == "tokens" else 0}}}

    agent = runtime.ReasoningAgent(client, configuration, local_adapter=ExplicitUsageAdapter())
    assert agent.local_policy.solver_v2 is True
    result = agent.solve("Find the mathematical quantity with all its stated conditions.", {})
    assert result["final_response"].endswith("最终答案：23")
    assert len(calls) == _budget(result)["model_requests"] == 1
    assert _budget(result)["tool_calls"] == (1 if kind == "tool_calls" else 0)
    assert _budget(result)["total_tokens"] == (10 if kind == "tokens" else 0)
    assert "v2_budget_stop" in [item["step"] for item in result["trace"]]


@pytest.mark.parametrize("corruption", ["duplicate", "nan", "depth", "two_blocks"])
def test_malformed_plan_never_executes_a_hidden_task(monkeypatch, corruption):
    _empty_retrieval(monkeypatch)
    executed = []

    def spy(task):
        executed.append(task)
        raise AssertionError("Hidden malformed task reached executor")

    monkeypatch.setattr(runtime, "_v2_execute_calculation", spy)
    task = {"id": "hidden", "task": {"op": "evaluate", "expr": 123}}
    data = {"goals": ["object"], "conditions": [], "method": "direct", "obligations": [], "calculations": [task]}
    block = json.dumps(data)
    if corruption == "duplicate":
        block = block.replace('"goals":', '"goals": ["OTHER"], "goals":', 1)
    elif corruption == "nan":
        block = block.replace('"expr": 123', '"expr": NaN')
    elif corruption == "depth":
        block = block.replace('"expr": 123', '"expr": ' + '[' * 40 + '123' + ']' * 40)
    bad = "<solver_plan>" + block + "</solver_plan>"
    if corruption == "two_blocks":
        bad += "<solver_plan>" + json.dumps(data) + "</solver_plan>"
    responses = iter([bad + "\n最终答案：17", "最终答案：23", "Cannot decide the candidate comparison."])
    calls = []

    class Client:
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False
            calls.append(messages)
            return next(responses)

    agent = runtime.ReasoningAgent(Client())
    assert agent.local_policy.solver_v2 is True
    result = agent.solve("Find the requested mathematical quantity.", {})
    assert not executed
    assert _budget(result)["tool_calls"] == 0
    assert len(calls) == 3
    assert result["final_response"].splitlines()[-1] in ("最终答案：17", "最终答案：23")
    assert "hidden" not in json.dumps(result)
    assert runtime._ACTIVE_BUDGET.get() is None
