import pytest
from hashlib import sha256
import json

from evaluation.xh202627_response_replay import (
    MatchingReplayClient, ReplayDivergence, capture, compare, digest, inside, inspect_response, write_new,
)


def entry(answer="最终答案：7", finish="stop"):
    return ({"messages": [{"role": "user", "content": "compute"}], "temperature": 0.0, "max_tokens": 512},
            {"status": "success", "response": answer, "metadata": {"finish_reason": finish}})


def test_replay_exact_request_preserves_incompleteness():
    request, response = entry(finish="length")
    client = MatchingReplayClient([(request, response)])
    result = client.chat(**request)
    assert result["finish_reason"] == "length"
    assert client.position == 1
    with pytest.raises(ReplayDivergence):
        client.chat(**request)


@pytest.mark.parametrize("key,value", [("temperature", 0.6), ("max_tokens", 1024),
                                     ("messages", [{"role": "user", "content": "changed"}])])
def test_replay_never_shifts_old_responses_after_changed_request(key, value):
    request, response = entry()
    client = MatchingReplayClient([(request, response)])
    with pytest.raises(ReplayDivergence):
        client.chat(**{**request, key: value})
    assert client.position == 0
    assert client.mismatch == "request_changed"


def test_replay_divergence_escapes_normal_solver_exception_handlers():
    assert not issubclass(ReplayDivergence, Exception)


@pytest.mark.parametrize("recorded", ["omitted", None, False, True])
@pytest.mark.parametrize("sent", ["omitted", None, False, True])
def test_replay_distinguishes_missing_null_and_both_thinking_modes(recorded, sent):
    request, response = entry()
    incoming = dict(request)
    if recorded != "omitted":
        request["thinking_mode"] = recorded
    if sent != "omitted":
        incoming["thinking_mode"] = sent
    client = MatchingReplayClient([(request, response)])
    if recorded == sent:
        assert client.chat(**incoming)["content"] == response["response"]
    else:
        with pytest.raises(ReplayDivergence):
            client.chat(**incoming)
        assert client.position == 0 and client.mismatch == "request_changed"


@pytest.mark.parametrize("key,old,new", [("tools", [{"type": "function", "name": "old"}], []),
                                        ("tool_choice", "auto", "none")])
def test_replay_compares_tool_parameters_instead_of_ignoring_them(key, old, new):
    request, response = entry()
    request[key] = old
    with pytest.raises(ReplayDivergence):
        MatchingReplayClient([(request, response)]).chat(**{**request, key: new})
    assert MatchingReplayClient([(request, response)]).chat(**request)["content"] == response["response"]


def test_replay_rejects_unrecognized_recorded_generation_parameters():
    request, response = entry()
    client = MatchingReplayClient([({**request, "top_p": 0.2}, response)])
    with pytest.raises(ReplayDivergence):
        client.chat(**request)
    assert client.position == 0 and client.mismatch == "unsupported_recorded_request"


def test_replay_understands_queue_envelope_without_discarding_parameters():
    request, response = entry()
    request["thinking_mode"] = False
    client = MatchingReplayClient([({"ordinal": 1, "payload": request}, response)])
    assert client.chat(**request)["content"] == response["response"]


def test_solver_replay_cannot_reuse_old_responses_after_thinking_change():
    import user_agent as runtime
    entries = []

    class Recorder:
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            request = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens,
                       "thinking_mode": thinking_mode}
            text = "VERDICT: A" if max_tokens == 1024 else "最终答案：7"
            response = {"status": "success", "response": text, "metadata": {"finish_reason": "stop"}}
            entries.append((request, response))
            return {"content": text, "finish_reason": "stop"}

    config = runtime.AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    expected = runtime.ReasoningAgent(Recorder(), config).solve("计算 3+4。", {})
    exact = MatchingReplayClient(entries)
    assert runtime.ReasoningAgent(exact, config).solve("计算 3+4。", {})["final_response"] == expected["final_response"]
    assert exact.position == len(entries) > 0
    legacy = MatchingReplayClient([({k: v for k, v in req.items() if k != "thinking_mode"}, response)
                                   for req, response in entries])
    with pytest.raises(ReplayDivergence):
        runtime.ReasoningAgent(legacy, config).solve("计算 3+4。", {})
    assert legacy.position == 0 and legacy.mismatch == "request_changed"


def test_observation_cannot_turn_length_or_empty_into_success():
    assert inspect_response(entry(finish="length")[1])["answer"] == ""
    assert inspect_response(entry("\n\n")[1])["kind"] == "empty_content"
    assert inspect_response({"status": "failed"})["kind"] == "transport_or_protocol_failure"


def test_safe_paths_and_exclusive_outputs(tmp_path):
    with pytest.raises(ValueError):
        inside(tmp_path, "../escape.json")
    path = tmp_path / "report.json"
    write_new(path, {"a": 1})
    with pytest.raises(FileExistsError):
        write_new(path, {"a": 2})
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})


@pytest.mark.parametrize("tamper", [None, "response", "input", "snapshot"])
@pytest.mark.parametrize("envelope", [False, True])
def test_capture_and_compare_bind_original_files_and_stop_on_drift(tmp_path, tamper, envelope):
    pilot, bundle = tmp_path / "pilot", tmp_path / "bundle"
    pilot.mkdir()
    bundle.mkdir()
    inputs = bundle / "dev.input.jsonl"
    inputs.write_text(json.dumps({"idx": "fixture-1", "problem": "Find the result."})+"\n", encoding="utf-8")
    ledger = pilot / "request-ledger.jsonl"
    ledger.write_text(json.dumps({"event": "start", "ordinal": 1, "variant": "baseline", "stage": "generate"})+"\n")
    checkpoint = pilot / "runs/baseline-0/fixture-1.json"
    write_new(checkpoint, {"idx": "fixture-1", "final_response": "最终答案：7"})
    request, response = entry()
    request["thinking_mode"] = False
    record = {"ordinal": 1, "payload": request} if envelope else {**request, "ordinal": 1}
    write_new(pilot / "model-relay/request-0001.json", record)
    response_path = pilot / "model-relay/response-0001.json"
    write_new(response_path, response)
    item = {"idx": "fixture-1", "variant": "baseline", "request_ordinals": [1], "actual": "7",
            "checkpoint_sha256": sha256(checkpoint.read_bytes()).hexdigest()}
    write_new(pilot / "audited-result.json", {"status": "stopped", "generation_source_sha256": "a"*64,
        "ledger_sha256": sha256(ledger.read_bytes()).hexdigest(), "completed_item_diagnostics": {"items": [item]}})
    write_new(pilot / "study/protocol.json", {"bundle": str(bundle), "plans": {"dev": {
        "input_sha256": sha256(inputs.read_bytes()).hexdigest()}}})
    for relative in ("pilot-plan.json", "assistant-review.json", "runs/baseline-0/_run/run_summary.json"):
        write_new(pilot / relative, {})
    snapshot, output = tmp_path / "snapshot.json", tmp_path / "after.json"
    captured = capture(pilot, snapshot)
    assert captured["responses"] == 1 and captured["completed_items"] == 1
    manifest = json.loads(snapshot.read_text())
    assert manifest["schema_version"] == 2
    assert manifest["responses"][0]["request_sha256"] == digest(request)
    assert manifest["responses"][0]["thinking_mode_recorded"] is True
    before = {str(p): sha256(p.read_bytes()).hexdigest() for p in pilot.rglob("*.json*")}
    if tamper:
        changed = {"response": response_path, "input": inputs, "snapshot": snapshot}[tamper]
        changed.write_text("{}", encoding="utf-8")
        with pytest.raises((ValueError, KeyError)):
            compare(snapshot, output)
        assert not output.exists()
    else:
        result = compare(snapshot, output)
        assert result["actual_api_requests"] == 0 and result["response_changes"] == {"unchanged": 1}
        assert json.loads(output.read_text())["replay_contract"] == "parser_only"
        assert before == {str(p): sha256(p.read_bytes()).hexdigest() for p in pilot.rglob("*.json*")}
