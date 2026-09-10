"""Shared live-admission limits without network or credentials."""
from concurrent.futures import ThreadPoolExecutor
import copy
import threading

import pytest

from evaluation import xh_day1_diagnostic as day1
from evaluation import xh_accuracy_diagnostic as helpers


def payload(tokens=1024):
    return {"messages": [{"role": "user", "content": "public fixture"}],
            "temperature": 0, "max_tokens": tokens, "thinking_mode": False}


def sender(_payload):
    return {"response": "最终答案：4", "metadata": {"model": day1.MODEL,
            "attempts": 1, "finish_reason": "stop", "usage": {
                "prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}}


def state():
    return {"status": "running", "deadline": 10000, "attempts": 0,
            "completed_responses": 0, "requested_output_tokens": 0,
            "known_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


@pytest.mark.parametrize("boundary", ["requests", "tokens", "deadline"])
def test_admission_refuses_before_send_at_any_boundary(tmp_path, boundary):
    current, sent = state(), []
    if boundary == "requests":
        current["attempts"] = day1.CAPS["requests"]
    elif boundary == "tokens":
        current["requested_output_tokens"] = day1.CAPS["output_tokens"] - 1023
    else:
        current["deadline"] = 360
    budget = day1.Admission(tmp_path / "state.json", current, lambda p: sent.append(p), clock=lambda: 0)
    with pytest.raises(RuntimeError):
        budget.send(payload())
    assert not sent
    assert helpers.read(tmp_path / "state.json")["status"] == "stopped"


def test_parallel_admission_never_exceeds_global_cap(tmp_path):
    current, sent, gate = state(), [], threading.Lock()
    current["attempts"] = day1.CAPS["requests"] - 2
    def send(value):
        with gate:
            sent.append(copy.deepcopy(value))
        return sender(value)
    budget = day1.Admission(tmp_path / "state.json", current, send, clock=lambda: 0)
    def attempt(_):
        try:
            budget.send(payload())
        except RuntimeError:
            pass
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(attempt, range(10)))
    assert len(sent) == 2
    assert current["attempts"] == day1.CAPS["requests"]
    assert current["completed_responses"] == 2
    assert current["known_usage"]["total_tokens"] == 20


def test_uncertain_request_is_reserved_and_no_retry(tmp_path):
    current, sent = state(), []
    def fail(value):
        sent.append(value)
        raise TimeoutError("SYNTHETIC_PRIVATE_EXCEPTION")
    path = tmp_path / "state.json"
    budget = day1.Admission(path, current, fail, clock=lambda: 0)
    with pytest.raises(TimeoutError):
        budget.send(payload(8192))
    with pytest.raises(RuntimeError):
        budget.send(payload())
    assert len(sent) == 1
    assert current["attempts"] == 1 and current["completed_responses"] == 0
    assert current["requested_output_tokens"] == 8192
    assert "SYNTHETIC_PRIVATE_EXCEPTION" not in path.read_text()


def test_changed_protocol_never_reaches_network(tmp_path):
    sent, current = [], state()
    budget = day1.Admission(tmp_path / "state.json", current, lambda p: sent.append(p))
    for changes in ({"thinking_mode": True}, {"max_tokens": 8193}, {"tools": []}):
        with pytest.raises(ValueError):
            budget.send({**payload(), **changes})
    assert not sent and current["attempts"] == 0


def test_input_rejects_labels_and_duplicate_id(tmp_path):
    path = tmp_path / "input.json"
    for rows in ([{"idx": "a", "problem": "x", "answer": "secret"}],
                 [{"idx": "a", "problem": "x"}, {"idx": "a", "problem": "y"}]):
        helpers.write(path, rows)
        with pytest.raises(ValueError):
            day1.inputs(path, len(rows))
