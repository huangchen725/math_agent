import json
import random
import threading
import time

import pytest

from evaluation import xh202627_pilot_control as control

IDENTITY = {key: "a" * 64 for key in ("source_sha256", "config_sha256", "input_sha256")}
PAYLOAD = {"messages": [{"role": "user", "content": "compute"}], "temperature": 0.0, "max_tokens": 512}


def setup(tmp_path, *, identity=None, **limits):
    path = tmp_path / "control"
    control.create(path, control.Limits(**{"requests": 20, "output_tokens": 20000, "dispatch_seconds": 30,
                                         "wait_seconds": 2, **limits}), model="fixture-model", identity=identity or IDENTITY)
    return path


def receipt(text="最终答案：7"):
    return {"response": text, "metadata": {"model": "Fixture-Model", "attempts": 1,
        "finish_reason": "stop", "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5}}}


def wait_for(predicate):
    until = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < until
        time.sleep(0.005)


def launch_call(path):
    results = []
    def call():
        try:
            results.append(control.RelayClient(path).chat(**PAYLOAD))
        except control.PilotStopped as error:
            results.append(type(error).__name__)
    thread = threading.Thread(target=call)
    thread.start()
    wait_for(lambda: control.status(path)["queued"] is not None)
    return thread, results


def test_pause_before_worker_admission_sends_nothing(tmp_path):
    path = setup(tmp_path)
    thread, result = launch_call(path)
    acknowledgment = control.pause(path)
    assert acknowledgment["last_admitted_ordinal"] == 0
    assert acknowledgment["queued_not_sent"] == 1
    assert not control.serve_once(path, lambda _: pytest.fail("unexpected send"))
    thread.join(2)
    assert not thread.is_alive() and result == ["PilotStopped"]
    assert control.status(path)["unknown_usage_requests"] == 0


def test_pause_during_inflight_collects_one_receipt_and_does_not_restart(tmp_path):
    path = setup(tmp_path)
    caller, result = launch_call(path)
    entered, release = threading.Event(), threading.Event()
    sends = []
    def send(payload):
        sends.append(payload)
        entered.set()
        assert release.wait(2)
        return receipt()
    worker = threading.Thread(target=control.serve, args=(path, send))
    worker.start()
    assert entered.wait(2)
    assert control.pause(path)["in_flight"] == 1
    release.set()
    worker.join(2)
    caller.join(2)
    assert not worker.is_alive() and not caller.is_alive()
    assert len(sends) == 1 and result == [{"content": "最终答案：7", "finish_reason": "stop"}]
    state = control.status(path)
    assert state["status"] == "paused" and state["known_usage"]["total_tokens"] == 5
    assert state["unknown_usage_requests"] == 0
    with pytest.raises(control.PilotStopped):
        control.RelayClient(path).chat(**PAYLOAD)


@pytest.mark.parametrize("bound", ["request", "output", "time"])
def test_each_global_limit_stops_before_send(tmp_path, bound):
    path = setup(tmp_path, **({"requests": 1, "output_tokens": 8192} if bound == "request" else
                             {"output_tokens": 1} if bound == "output" else {}))
    calls = []
    if bound == "request":
        first, _ = launch_call(path)
        assert control.serve_once(path, lambda p: calls.append(p) or receipt())
        first.join(2)
    caller, result = launch_call(path)
    future = control.status(path)["deadline"]+1
    assert not control.serve_once(path, lambda p: calls.append(p) or receipt(),
                                  clock=(lambda: future) if bound == "time" else time.monotonic)
    caller.join(2)
    assert result == ["PilotStopped"] and not caller.is_alive()
    assert len(calls) == int(bound == "request")


def test_uncertain_failure_is_not_retried_or_logged_with_secret(tmp_path):
    path = setup(tmp_path)
    caller, result = launch_call(path)
    def fail(_):
        raise TimeoutError("Bearer SYNTHETIC_SECRET_DO_NOT_LOG")
    assert control.serve_once(path, fail)
    caller.join(2)
    assert result == ["PilotStopped"]
    state = control.status(path)
    assert state["attempts"] == 1 and state["unknown_usage_requests"] == 1
    assert not control.serve_once(path, lambda _: pytest.fail("retry"))
    assert all("SYNTHETIC_SECRET" not in f.read_text() for f in path.glob("*.json*"))


def test_receipt_is_published_only_after_state_commit(tmp_path):
    path = setup(tmp_path)
    caller, _ = launch_call(path)
    assert control.serve_once(path, lambda _: receipt())
    caller.join(2)
    assert control.status(path)["in_flight"] is None
    second, _ = launch_call(path)
    control.pause(path)
    second.join(2)
    assert not second.is_alive()


def test_controller_deadline_keeps_late_receipt_and_no_extra_send(tmp_path):
    path = setup(tmp_path, wait_seconds=0.1)
    caller, result = launch_call(path)
    entered, release = threading.Event(), threading.Event()
    def send(_):
        entered.set()
        assert release.wait(2)
        return receipt()
    worker = threading.Thread(target=control.serve, args=(path, send))
    worker.start()
    assert entered.wait(2)
    caller.join(2)
    assert not caller.is_alive() and result == ["PilotStopped"]
    assert control.status(path)["stop_reason"] == "relay_deadline"
    release.set()
    worker.join(2)
    assert not worker.is_alive()
    assert control.status(path)["completed_responses"] == 1
    assert control.status(path)["status"] == "stopped"


def test_observation_keeps_blank_content_separate_from_reasoning():
    body = {"id": "PROVIDER_ID", "model": "fixture-model", "usage": receipt()["metadata"]["usage"],
        "choices": [{"finish_reason": "stop", "message": {"content": "\n\n", "reasoning_content": "SYNTHETIC_REASONING"}}]}
    projected = control.project_response(body)
    assert projected["response"] == "\n\n"
    assert projected["diagnostics"]["reasoning_content"]["present"]
    assert projected["diagnostics"]["whitespace_only_content"]
    assert "SYNTHETIC_REASONING" not in json.dumps(projected)
    assert "PROVIDER_ID" not in json.dumps(projected)


@pytest.mark.parametrize("change", [{"attempts": 2}, {"model": "wrong-model"},
                                   {"usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 1}}])
def test_invalid_receipt_fails_globally(tmp_path, change):
    path = setup(tmp_path)
    caller, _ = launch_call(path)
    response = receipt()
    response["metadata"].update(change)
    control.serve_once(path, lambda _: response)
    caller.join(2)
    assert control.status(path)["unknown_usage_requests"] == 1
    assert control.status(path)["status"] == "stopped"


def test_q1_partial_run_remains_interrupted_and_labels_do_not_reach_sender(tmp_path):
    from evaluation.q0_pipeline import digest, freeze_records, write_bundle
    from evaluation.q1_experiments import make_plan
    rng = random.Random(209)
    rows = [{"idx": str(i), "problem": "".join(rng.choice("abcdefghijklmn") for _ in range(90)),
        "answer": "PRIVATE_REFERENCE", "subject": "fixture", "level": "synthetic", "task_type": "free_response",
        "source": "fixture://pause", "license": "MIT"} for i in range(4)]
    rows, selection = freeze_records(rows, per_subject=4, references=[])
    bundle = tmp_path / "bundle"
    write_bundle(bundle, rows, selection)
    plan = make_plan(bundle, model="fixture-model")
    identity = {"source_sha256": plan["code_sha"], "input_sha256": plan["input_sha256"],
                "config_sha256": digest(plan["variants"]["baseline"])}
    path = setup(tmp_path, identity=identity, requests=1, output_tokens=8192)
    def send(payload):
        assert "PRIVATE_REFERENCE" not in json.dumps(payload)
        return receipt()
    worker = threading.Thread(target=control.serve, args=(path, send))
    worker.start()
    output = tmp_path / "run"
    result = control.run_controlled(plan, "baseline", bundle, output,
                                    control.RelayClient(path))
    worker.join(2)
    assert not worker.is_alive()
    assert result["status"] == "interrupted"
    summary = json.loads((output / "_run/run_summary.json").read_text())
    assert summary["status"] == "interrupted" and summary["completed_items"] == 0
    assert not list(output.glob("*.json"))


@pytest.mark.parametrize("status_code", [200, 302])
def test_http_adapter_is_one_send_no_retry_no_redirect(monkeypatch, status_code):
    import requests
    calls = []
    class Response:
        def __init__(self):
            self.status_code = status_code
        def raise_for_status(self):
            pass
        def json(self):
            return {"model": "fixture-model", "usage": receipt()["metadata"]["usage"],
                    "choices": [{"finish_reason": "stop", "message": {"content": "7"}}]}
    class Session:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def mount(self, prefix, adapter):
            assert adapter.max_retries.total == 0
        def post(self, url, **kwargs):
            calls.append(kwargs)
            return Response()
    monkeypatch.setattr(requests, "Session", Session)
    if status_code == 302:
        with pytest.raises(ValueError):
            control._http_once(PAYLOAD, "SYNTHETIC_KEY", "fixture-model")
    else:
        assert control._http_once(PAYLOAD, "SYNTHETIC_KEY", "fixture-model")["response"] == "7"
    assert len(calls) == 1
    assert calls[0]["timeout"] == (10, 300) and calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("field,value", [("limits", {"requests": 10000}), ("model", "changed-model"),
                                       ("identity", IDENTITY | {"input_sha256": "b" * 64})])
def test_changed_control_binding_prevents_send(tmp_path, field, value):
    path = setup(tmp_path)
    state = control._read(path / "state.json")
    state[field] = value
    control._write(path / "state.json", state)
    control.serve(path, lambda _: pytest.fail("modified control must not send"))
    assert control._read(path / "state.json")["stop_reason"] == "relay_protocol_failure"
    with pytest.raises(ValueError, match="modified relay plan"):
        control.status(path)


@pytest.mark.parametrize("values", [{"requests": True}, {"output_tokens": -1},
    {"wait_seconds": 360}, {"dispatch_seconds": float("nan")}, {"wait_seconds": float("inf")}])
def test_invalid_limits_fail_before_creating_state(tmp_path, values):
    with pytest.raises(ValueError):
        setup(tmp_path, **values)
    assert not (tmp_path / "control").exists()


def test_q1_wrong_identity_stops_before_loading_or_sending(tmp_path):
    path = setup(tmp_path)
    plan = {"code_sha": "a" * 64, "input_sha256": "a" * 64, "model": "fixture-model", "variants": {"baseline": {}}}
    with pytest.raises(ValueError, match="identity differs"):
        control.run_controlled(plan, "baseline", tmp_path / "absent_bundle", tmp_path / "absent_output",
                               control.RelayClient(path))
    assert control.status(path)["attempts"] == 0 and control.status(path)["status"] == "stopped"
    assert not (tmp_path / "absent_output").exists()


def hanging_child(marker):
    from pathlib import Path
    Path(marker).write_text("started", encoding="utf-8")
    time.sleep(30)


def test_actual_spawned_process_is_terminated_at_local_deadline(tmp_path):
    import multiprocessing
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(TimeoutError, match="child deadline"):
        control._bounded_child(hanging_child, (str(tmp_path / "started"),), wait_seconds=1)
    assert time.monotonic()-started < 6
    assert {p.pid for p in multiprocessing.active_children()} <= before


def test_sender_uses_bounded_child_and_receipt_without_network(monkeypatch):
    calls = []
    def child(target, args, *, wait_seconds):
        assert target is control._http_child
        calls.append(wait_seconds)
        control._write(control.Path(args[-1]), {"status": "success", "receipt": receipt()})
    monkeypatch.setattr(control, "_bounded_child", child)
    result = control.make_http_sender("SYNTHETIC_KEY", "fixture-model")(PAYLOAD)
    assert result == receipt() and calls == [345]
