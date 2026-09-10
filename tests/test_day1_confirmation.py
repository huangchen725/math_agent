"""The repair confirmation carries forward cost and cannot resume old work."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import pytest

from evaluation import xh_day1_confirmation as confirm
from evaluation import xh_day1_diagnostic as day1
from evaluation import xh_accuracy_diagnostic as helper


@pytest.fixture
def probe(tmp_path, monkeypatch):
    target = tmp_path / "confirmation"
    target.mkdir()
    (tmp_path / "live").mkdir()
    prior = {"status": "completed", "attempts": 83, "completed_responses": 83,
             "started_at": 0, "phases": list(day1.PHASES),
             "unknown_usage_requests": 0, "requested_output_tokens": 398848, "deadline": 10000,
             "known_usage": {"prompt_tokens": 64146, "completion_tokens": 66893, "total_tokens": 131039}}
    rows = [{"idx": str(i), "problem": "Synthetic public probe " + str(i)} for i in range(8)]
    helper.write(tmp_path / "hit-inputs.json", rows)
    helper.write(tmp_path / "day1-inputs.json", rows[:6])
    original_plan = {"caps": day1.CAPS, "model": day1.MODEL,
                     "input_sha256": helper.file_hash(tmp_path / "day1-inputs.json"),
                     "tool_sha256": helper.file_hash(day1.__file__),
                     "helper_sha256": helper.file_hash(helper.__file__),
                     "controller_sha256": helper.file_hash(confirm.control.__file__)}
    helper.write(tmp_path / "live/plan.json", helper.seal(original_plan))
    prior["plan_sha256"] = helper.file_hash(tmp_path / "live/plan.json")
    helper.write(tmp_path / "live/execution.json", prior)
    helper.write(tmp_path / "hit-plan.json", helper.seal({"input_sha256": helper.file_hash(tmp_path / "hit-inputs.json")}))
    snapshot = {"source_sha256": "1" * 64, "config_sha256": "2" * 64, "config": {"synthetic": True}}
    plan = {"prior_state_sha256": helper.file_hash(tmp_path / "live/execution.json"),
            "original_hit_plan_sha256": helper.file_hash(tmp_path / "hit-plan.json"),
            "source_sha256": snapshot["source_sha256"], "global_caps": day1.CAPS,
            "additional_request_cap": 8, "model": day1.MODEL,
            "input_sha256": helper.file_hash(tmp_path / "hit-inputs.json"),
            "tool_sha256": helper.file_hash(confirm.__file__), "admission_sha256": helper.file_hash(day1.__file__),
            "helper_sha256": helper.file_hash(helper.__file__), "controller_sha256": helper.file_hash(confirm.control.__file__)}
    helper.write(target / "plan.json", helper.seal(plan))
    monkeypatch.setattr(helper, "check_snapshot", lambda _: (snapshot, None))
    class Agent:
        def __init__(self, client):
            self.client = client
        def solve(self, problem, metadata):
            text = self.client.chat(messages=[{"role": "user", "content": problem}],
                                    temperature=0, max_tokens=8192, thinking_mode=False)
            return {"final_response": text["content"], "trace": []}
    monkeypatch.setattr(helper, "load_source", lambda _: SimpleNamespace(ReasoningAgent=Agent))
    return tmp_path, prior


def send(payload):
    assert set(payload) == {"messages", "temperature", "max_tokens", "thinking_mode"}
    return {"response": "最终答案：4", "metadata": {"model": day1.MODEL, "attempts": 1,
            "finish_reason": "stop", "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}}


def test_confirmation_carries_cost_preserves_original_and_cannot_resume(probe):
    directory, prior = probe
    original = sha256((directory / "live/execution.json").read_bytes()).hexdigest()
    result = confirm.run(directory, send, clock=lambda: 0)
    assert result["attempts"] == 91 and result["additional_attempts"] == 8
    assert result["requested_output_tokens"] == 398848 + 8 * 8192
    assert result["known_usage"]["total_tokens"] == 131119
    assert result["deadline"] == prior["deadline"]
    assert result["unknown_usage_requests"] == 0
    assert sha256((directory / "live/execution.json").read_bytes()).hexdigest() == original
    with pytest.raises(ValueError, match="cannot restart"):
        confirm.run(directory, send, clock=lambda: 0)


@pytest.mark.parametrize("change", [{"attempts": 193}, {"requested_output_tokens": 650000},
                                   {"deadline": 350}, {"status": "stopped"}, {"unknown_usage_requests": 1}])
def test_original_limits_and_stops_cannot_be_bypassed(probe, change):
    directory, prior = probe
    helper.write(directory / "live/execution.json", {**prior, **change})
    plan, _ = helper.unseal(directory / "confirmation/plan.json")
    plan["prior_state_sha256"] = helper.file_hash(directory / "live/execution.json")
    helper.write(directory / "confirmation/plan.json", helper.seal(plan))
    sent = []
    with pytest.raises(ValueError):
        confirm.run(directory, lambda p: sent.append(p), clock=lambda: 0)
    assert not sent and not (directory / "confirmation/execution.json").exists()


def test_prior_receipt_mutation_is_rejected_before_execution(probe):
    directory, prior = probe
    helper.write(directory / "live/execution.json", {**prior, "attempts": 0})
    with pytest.raises(ValueError, match="modified confirmation binding"):
        confirm.run(directory, send, clock=lambda: 0)


def test_changed_original_probes_cannot_be_resealed_as_a_confirmation(probe):
    directory, _ = probe
    rows = helper.read(directory / "hit-inputs.json")
    rows[0]["problem"] = "a substituted easier problem"
    helper.write(directory / "hit-inputs.json", rows)
    with pytest.raises(ValueError, match="original fixed probes changed"):
        confirm.preceding_batch(directory)


def test_local_preparation_failure_stops_all_future_dispatch(probe, monkeypatch):
    directory, _ = probe
    def fail(*args, **kwargs):
        raise OSError("synthetic local resource failure")
    monkeypatch.setattr(confirm.control, "create", fail)
    sent = []
    with pytest.raises(RuntimeError, match="local preparation failed"):
        confirm.run(directory, lambda p: sent.append(p), clock=lambda: 0)
    state = helper.read(directory / "confirmation/execution.json")
    assert state["status"] == "stopped" and state["attempts"] == 83
    assert not sent
    with pytest.raises(ValueError, match="cannot restart"):
        confirm.run(directory, send, clock=lambda: 0)


def test_later_worker_failure_stops_before_earlier_slow_request_finishes(probe, monkeypatch):
    directory, _ = probe
    began = threading.Event()
    original = confirm.control.create
    witnessed = []
    def create(path, *args, **kwargs):
        if path.parent.name == "item-01":
            assert began.wait(3)
            raise OSError("second worker failed during preparation")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(confirm.control, "create", create)
    def slow_send(payload):
        began.set()
        until = time.monotonic() + 3
        stopped = False
        while time.monotonic() < until:
            if helper.read(directory / "confirmation/execution.json")["status"] == "stopped":
                stopped = True
                break
            time.sleep(.01)
        witnessed.append(stopped)
        return send(payload)
    with pytest.raises(RuntimeError, match="local preparation failed"):
        confirm.run(directory, slow_send, clock=lambda: 0)
    assert witnessed and all(witnessed)


def test_stop_persists_after_overlapping_real_json_reader_closes(tmp_path, monkeypatch):
    path = tmp_path / "execution.json"
    state = {"status": "running"}
    helper.write(path, state)
    admission = day1.Admission(path, state, lambda _: None)
    reader_open = threading.Event()
    release_reader = threading.Event()
    writer_waiting = threading.Event()
    writer_finished = threading.Event()
    errors, observed = [], []
    real_lock = threading.RLock()

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "json-stop-writer":
                writer_waiting.set()
            real_lock.acquire()
            return self

        def __exit__(self, *args):
            real_lock.release()

    original_read = Path.read_bytes

    def held_read(target):
        if target != path:
            return original_read(target)
        with target.open("rb") as stream:
            reader_open.set()
            assert release_reader.wait(3)
            return stream.read()

    def reader():
        try:
            observed.append(helper.read(path))
        except BaseException as exc:
            errors.append(exc)

    def writer():
        try:
            admission.stop("local_execution_failure")
        except BaseException as exc:
            errors.append(exc)
        finally:
            writer_finished.set()

    monkeypatch.setattr(helper, "_JSON_IO_LOCK", ObservedLock())
    monkeypatch.setattr(Path, "read_bytes", held_read)
    threads = [threading.Thread(target=reader, name="json-state-reader"),
               threading.Thread(target=writer, name="json-stop-writer")]
    threads[0].start()
    try:
        assert reader_open.wait(3)
        threads[1].start()
        assert writer_waiting.wait(3)
        assert not writer_finished.is_set(), "replace must wait for the open reader"
    finally:
        release_reader.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=3)
    assert not any(thread.is_alive() for thread in threads)
    assert not errors
    assert observed == [{"status": "running"}]
    assert writer_finished.is_set()
    assert state["status"] == "stopped"
    assert helper.read(path) == {"status": "stopped", "stop_reason": "local_execution_failure"}
    assert not path.with_suffix(".tmp").exists()
