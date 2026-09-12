"""Observer and durable stop invariants; no credentials or network."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import random
from functools import lru_cache
from types import SimpleNamespace

import pytest

from evaluation import xh_accuracy_diagnostic as diagnostic
from evaluation import xh202627_pilot_control as control
import user_agent as runtime


class Client:
    def __init__(self, scenario="normal"):
        self.scenario = scenario
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        assert thinking_mode is False
        self.calls.append(copy.deepcopy(dict(messages=messages, temperature=temperature,
                                              max_tokens=max_tokens, thinking_mode=thinking_mode)))
        if self.scenario == "stop":
            raise control.PilotStopped("fixture_stop")
        if "判断是否正确" in messages[-1]["content"]:
            return "VERDICT: B" if self.scenario == "negative" else "VERDICT: A"
        if "请找出错误" in messages[-1]["content"]:
            return "NO ERROR"
        if self.scenario == "cutoff" and len(self.calls) <= 3:
            return {"content": "unfinished", "finish_reason": "length"}
        return "Calculation completed.\n最终答案：4"

    def __getattr__(self, name):
        raise AssertionError("private client probe")


@pytest.mark.parametrize("scenario", ["normal", "negative", "cutoff"])
def test_observer_preserves_entire_calls_and_final(scenario, monkeypatch):
    monkeypatch.setattr(runtime.ExecutionBudget, "elapsed_seconds", lambda self: 0)
    for problem in ("Compute 2 + 2", "Solve an inequality; express the interval.", "求 2+2"):
        first, second, events = Client(scenario), Client(scenario), []
        baseline = runtime.ReasoningAgent(first).solve(problem, {})
        observed = diagnostic.observed_agent(runtime, second, events).solve(problem, {})
        assert baseline == observed
        assert first.calls == second.calls
        assert events and all(e["status"] == "completed" for e in events)
        assert "observation" not in observed
        assert observed["final_response"].endswith("最终答案：4")


def test_observer_preserves_baseexception_without_retry():
    events, client = [], Client("stop")
    class Legacy(runtime.ReasoningAgent):
        def __init__(self, client):
            super().__init__(client, local_policy=runtime.legacy_deployment_policy())
    with pytest.raises(control.PilotStopped):
        diagnostic.observed_agent(SimpleNamespace(ReasoningAgent=Legacy), client, events).solve("2+2", {})
    assert len(client.calls) == 1
    assert events[-1]["status"] == "interrupted"


@pytest.mark.parametrize("changes", [{"thinking_mode": True}, {"max_tokens": 8193}, {"max_tokens": 0}, {"extra": 1}])
def test_strict_transport_rejects_protocol_or_cap_changes(changes):
    sent = []
    payload = {"messages": [], "temperature": 0, "max_tokens": 8192, "thinking_mode": False, **changes}
    with pytest.raises(ValueError):
        diagnostic.strict_sender(lambda p: sent.append(p))(payload)
    assert sent == []


@lru_cache(maxsize=1)
def frozen_184_sources():
    # Historical diagnostic fixtures must use historical source, not whichever
    # deployment policy a later candidate happens to enable.
    revision = "1841685526e6f4d9c7211fb867d4db0aa65155d4"
    entry = diagnostic.git_bytes(revision, "user_agent.py")
    return {name: diagnostic.git_bytes(revision, name) for name in diagnostic.formal_files(entry)}


@pytest.fixture
def prepared(tmp_path):
    directory = tmp_path / "diagnostic"
    directory.mkdir()
    rows = [{"idx": str(n), "problem": "Compute 2+2"} for n in range(3)]
    diagnostic.write(directory / "inputs.json", rows)
    plan = {"allowance": diagnostic.ALLOWANCE, "model": diagnostic.MODEL,
            "tool_sha256": diagnostic.file_hash(diagnostic.__file__),
            "controller_sha256": diagnostic.file_hash(control.__file__),
            "input_sha256": diagnostic.file_hash(directory / "inputs.json")}
    diagnostic.write(directory / "plan.json", diagnostic.seal(plan))
    # No reference file exists: run must not need or read one.
    source = directory / "snapshots" / "baseline"
    source.mkdir(parents=True)
    files = {}
    for name, content in frozen_184_sources().items():
        target = source / name
        target.write_bytes(content)
        files[name] = diagnostic.file_hash(target)
    agent = diagnostic.load_source(source).ReasoningAgent(object())
    config = {"agent": asdict(agent.config), "policy": asdict(agent.local_policy)}
    diagnostic.write(source / "snapshot.json", diagnostic.seal({
        "files": files, "source_sha256": diagnostic.digest(files), "config": config,
        "config_sha256": diagnostic.digest(config)}))
    return directory


def sender(payload):
    assert set(payload) == {"messages", "temperature", "max_tokens", "thinking_mode"}
    assert payload["thinking_mode"] is False
    text = "VERDICT: A" if "判断是否正确" in payload["messages"][-1]["content"] else "最终答案：4"
    return {"response": text, "metadata": {"model": diagnostic.MODEL,
            "attempts": 1, "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}}


def test_complete_fake_default_solve_records_stages_and_never_reads_labels(prepared):
    result = diagnostic.run(prepared, "baseline", sender)
    assert result["status"] == "ready"
    receipt = result["runs"]["baseline"]
    assert receipt["attempts"] == receipt["completed_responses"]
    assert receipt["unknown_usage_requests"] == 0
    assert receipt["attempts"] <= 48
    for path in sorted((prepared / "runs/baseline").glob("item-*.json")):
        record = diagnostic.read(path)
        stages = {e["stage"] for e in record["observation"]}
        assert {"_generate_candidates", "_verify", "_aggregate"} <= stages
        assert record["result"]["final_response"].endswith("最终答案：4")
        assert record["request_ordinals"]
    assert len(list((prepared / "runs/baseline").glob("item-*.json"))) == 3
    with pytest.raises(ValueError, match="no automatic resume"):
        diagnostic.run(prepared, "baseline", sender)


@pytest.mark.parametrize("kind", ["source", "input", "config", "dependency", "tool"])
def test_modified_binding_blocks_before_sender(prepared, kind):
    if kind in ("source", "dependency"):
        name = "user_agent.py" if kind == "source" else "domain_prompts.py"
        path = prepared / "snapshots/baseline" / name
        path.write_bytes(path.read_bytes() + b"\n# modified\n")
    elif kind == "input":
        diagnostic.write(prepared / "inputs.json", [{"idx": "a", "problem": "changed"}])
    else:
        path = prepared / ("snapshots/baseline/snapshot.json" if kind == "config" else "plan.json")
        value, _ = diagnostic.unseal(path)
        if kind == "config":
            value["config"]["agent"]["max_tokens"] = 1
        else:
            value["tool_sha256"] = "a" * 64
        diagnostic.write(path, diagnostic.seal(value))
    sent = []
    with pytest.raises(ValueError):
        diagnostic.run(prepared, "baseline", lambda payload: sent.append(payload))
    assert not sent
    assert not (prepared / "execution.json").exists()


def test_transport_failure_stops_whole_batch_and_does_not_retry(prepared):
    calls = []
    def failed(payload):
        calls.append(payload)
        raise TimeoutError("SYNTHETIC SECRET not recorded")
    with pytest.raises(control.PilotStopped):
        diagnostic.run(prepared, "baseline", failed)
    assert len(calls) == 1
    state = diagnostic.read(prepared / "execution.json")
    assert state["status"] == "stopped"
    assert state["runs"]["baseline"]["unknown_usage_requests"] == 1
    assert len(list((prepared / "runs/baseline").glob("item-*.json"))) == 1
    assert "SYNTHETIC SECRET" not in (prepared / "execution.json").read_text()
    with pytest.raises(ValueError, match="no automatic resume"):
        diagnostic.run(prepared, "baseline", failed)
    assert len(calls) == 1


@pytest.mark.parametrize("limit", ["requests", "output_tokens"])
def test_admission_limit_stops_before_second_send(prepared, monkeypatch, limit):
    original = control.create
    def capped(directory, limits, **kwargs):
        params = asdict(limits)
        params[limit] = 1 if limit == "requests" else 8192
        params["output_tokens"] = min(params["output_tokens"], params["requests"] * 8192)
        return original(directory, control.Limits(**params), **kwargs)
    monkeypatch.setattr(control, "create", capped)
    sent = []
    def counted(payload):
        sent.append(payload)
        return sender(payload)
    with pytest.raises(control.PilotStopped):
        diagnostic.run(prepared, "baseline", counted)
    assert len(sent) == 1
    assert diagnostic.read(prepared / "execution.json")["status"] == "stopped"


def test_global_deadline_prevents_any_send(prepared):
    diagnostic.write(prepared / "execution.json", {"deadline": 100, "used_variants": [], "status": "ready", "runs": {}})
    sent = []
    with pytest.raises(ValueError, match="deadline"):
        diagnostic.run(prepared, "baseline", lambda p: sent.append(p), clock=lambda: 101)
    assert sent == []


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "x/../../escape", "..\\escape"])
def test_relative_artifact_path_cannot_escape(tmp_path, name):
    with pytest.raises(ValueError):
        diagnostic.safe_path(tmp_path, name)


def test_diagnostic_json_roundtrip_is_lossless_for_bounded_unicode(tmp_path):
    rng = random.Random(20260910)
    for n in range(30):
        value = {"text": "积分\n\\\"" + str(rng.randrange(10**9)), "numbers": [rng.randrange(-20, 20) for _ in range(n)]}
        path = tmp_path / "roundtrip.json"
        diagnostic.write(path, value)
        assert diagnostic.read(path) == value
        assert diagnostic.digest(value) == diagnostic.digest(json.loads(json.dumps(value)))
