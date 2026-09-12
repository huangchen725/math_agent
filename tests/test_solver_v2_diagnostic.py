"""Bounded one-shot diagnostic invariants; all transports are offline fakes."""
from concurrent.futures import ThreadPoolExecutor
import copy
from dataclasses import dataclass
import json
import random
from types import SimpleNamespace

import pytest

from evaluation import solver_v2_diagnostic as diagnostic
from evaluation import xh_accuracy_diagnostic as helpers
from evaluation import xh202627_pilot_control as control


def payload(tokens=1024):
    return {"messages": [{"role": "user", "content": "public fixture"}],
            "temperature": 0, "max_tokens": tokens, "thinking_mode": False}


def sender(value):
    assert value["thinking_mode"] is False
    return {"response": "Derived from public fixture.\n最终答案：4",
            "metadata": {"model": diagnostic.MODEL, "attempts": 1, "finish_reason": "stop",
                         "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}}}


def initial():
    return {"status": "running", "dispatch_deadline": 10000, "attempts": 0,
            "completed_responses": 0, "requested_output_tokens": 0, "truncations": 0,
            "known_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


@pytest.mark.parametrize("boundary", ["requests", "tokens", "deadline"])
def test_admission_stops_before_send_at_each_hard_boundary(tmp_path, boundary):
    state, sent = initial(), []
    if boundary == "requests":
        state["attempts"] = diagnostic.CAPS["requests"]
    elif boundary == "tokens":
        state["requested_output_tokens"] = diagnostic.CAPS["output_tokens"] - 1023
    else:
        state["dispatch_deadline"] = 0
    admission = diagnostic.Admission(tmp_path / "state.json", state, lambda p: sent.append(p), clock=lambda: 0)
    with pytest.raises(RuntimeError, match="admission stopped"):
        admission.send(payload())
    assert not sent
    assert helpers.read(tmp_path / "state.json")["status"] == "stopped"


def test_last_dispatch_may_finish_after_dispatch_window(tmp_path):
    state = initial()
    state["dispatch_deadline"] = 1
    admission = diagnostic.Admission(tmp_path / "state.json", state, sender, clock=lambda: 0.99)
    admission.send(payload())
    assert state["completed_responses"] == 1


def test_concurrent_random_reservations_preserve_nonrenewable_budget(tmp_path):
    rng = random.Random(20260913)
    for trial in range(8):
        state, sent = initial(), []
        state["attempts"] = diagnostic.CAPS["requests"] - rng.randint(1, 5)
        state["requested_output_tokens"] = diagnostic.CAPS["output_tokens"] - rng.randint(2048, 24000)
        before = copy.deepcopy(state)
        def send(value):
            sent.append(value["max_tokens"])
            return sender(value)
        admission = diagnostic.Admission(tmp_path / f"state-{trial}.json", state, send, clock=lambda: 0)
        sizes = [rng.randint(1, 8192) for _ in range(10)]
        def attempt(tokens):
            try:
                admission.send(payload(tokens))
            except RuntimeError:
                pass
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(attempt, sizes))
        assert state["attempts"] == before["attempts"] + len(sent) <= diagnostic.CAPS["requests"]
        assert state["requested_output_tokens"] == before["requested_output_tokens"] + sum(sent)
        assert state["requested_output_tokens"] <= diagnostic.CAPS["output_tokens"]
        assert state["completed_responses"] == len(sent)


def test_uncertain_send_is_charged_once_and_stops_other_workers(tmp_path):
    state, sent = initial(), []
    def failing(value):
        sent.append(value)
        raise TimeoutError("SYNTHETIC_PRIVATE_EXCEPTION")
    path = tmp_path / "state.json"
    admission = diagnostic.Admission(path, state, failing, clock=lambda: 0)
    with pytest.raises(TimeoutError):
        admission.send(payload(8192))
    with pytest.raises(RuntimeError):
        admission.send(payload())
    assert len(sent) == state["attempts"] == 1
    assert state["completed_responses"] == 0 and state["requested_output_tokens"] == 8192
    assert "SYNTHETIC_PRIVATE_EXCEPTION" not in path.read_text()


@pytest.mark.parametrize("change", [{"thinking_mode": True}, {"max_tokens": 8193}, {"max_tokens": False},
                                    {"tools": []}, {"timeout": 10}])
def test_public_protocol_rejection_precedes_admission(tmp_path, change):
    sent, state = [], initial()
    admission = diagnostic.Admission(tmp_path / "state.json", state, lambda p: sent.append(p))
    with pytest.raises(ValueError):
        admission.send({**payload(), **change})
    assert not sent and state["attempts"] == 0


@pytest.mark.parametrize("rows", [
    [{"idx": "x", "problem": "p", "answer": "label"}],
    [{"idx": "x", "problem": "p"}, {"idx": "x", "problem": "q"}],
    [{"idx": [], "problem": "p"}], [], [None],
])
def test_inputs_reject_reference_leakage_and_ambiguous_identity(tmp_path, rows):
    path = tmp_path / "inputs.json"
    helpers.write(path, rows)
    with pytest.raises(ValueError):
        diagnostic.read_inputs(path)


def test_input_pathlike_identifiers_remain_data(tmp_path):
    # Output paths use numeric positions, never identifiers.
    path = tmp_path / "inputs.json"
    rows = [{"idx": "../../outside", "problem": "Compute 2+2"}]
    helpers.write(path, rows)
    assert diagnostic.read_inputs(path) == rows


@dataclass
class Config:
    max_tokens: int = 1024


@dataclass
class Policy:
    solver_v2: bool = True


class Agent:
    def __init__(self, client):
        self.client, self.config, self.local_policy = client, Config(), Policy()

    def _chat(self, system_prompt, user_content, *, temperature=0, max_tokens=1024):
        result = self.client.chat(messages=[{"role": "system", "content": system_prompt},
                                 {"role": "user", "content": user_content}],
                                  temperature=temperature, max_tokens=max_tokens, thinking_mode=False)
        return result["content"] if isinstance(result, dict) else result

    def solve(self, problem, metadata):
        response = self._chat("ROUTE", problem)
        return {"final_response": response, "trace": [{"step": "v2_route_1"}]}


def module():
    return SimpleNamespace(ReasoningAgent=Agent, V2_ROUTE_PROMPT="ROUTE",
                           V2_REVIEW_PROMPT="REVIEW", V2_REPAIR_PROMPT="REPAIR")


def test_observer_preserves_request_and_complete_result():
    class Client:
        def __init__(self):
            self.calls = []
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            self.calls.append(copy.deepcopy(locals_without_self(locals())))
            return "最终答案：4"
    left, right, events = Client(), Client(), []
    expected = Agent(left).solve("2+2", {})
    actual = diagnostic.observed_agent(module(), right, events).solve("2+2", {})
    assert expected == actual and left.calls == right.calls
    assert events == [{"stage": "chat", "kind": "route", "response": "最终答案：4",
                       "finish_reason": None}]


def locals_without_self(values):
    return {k: v for k, v in values.items() if k != "self"}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    directory = tmp_path / "new-attempt"
    directory.mkdir()
    rows = [{"idx": f"public-{n}", "problem": "2+2"} for n in range(2)]
    plan = {"attempt_id": "new-fixture", "selection": [
        {"idx": row["idx"], "stratum": "nonhit", "subject": "algebra"} for row in rows]}
    frozen = {"snapshots": {"baseline": "a" * 64, "candidate": "b" * 64}}
    frozen["identities"] = {v: {"source_sha256": "a" * 64, "config_sha256": "b" * 64}
                            for v in ("baseline", "candidate")}
    helpers.write(directory / "freeze.json", {"fixture": True})
    monkeypatch.setattr(diagnostic, "check_freeze",
                        lambda path: (plan, rows, frozen, {"baseline": module(), "candidate": module()}))
    return directory, plan, rows


def test_full_pairs_need_no_reference_file_and_cannot_run_twice(prepared):
    directory, _, _ = prepared
    result = diagnostic.run(directory, sender)
    assert result["status"] == "completed"
    assert result["attempts"] == result["completed_responses"] == 4
    assert result["unknown_usage_requests"] == 0
    assert not (directory / "reference-audit.json").exists()
    artifacts = list((directory / "runs").glob("item-*/*/result.json"))
    assert len(artifacts) == 4
    for artifact in artifacts:
        recorded = helpers.read(artifact)
        assert recorded["status"] == "completed"
        assert recorded["requests_sent"] == 1
        assert recorded["result"]["final_response"].endswith("最终答案：4")
        assert recorded["observation"][0]["kind"] == "route"
    with pytest.raises(FileExistsError):
        diagnostic.run(directory, sender)


def test_failed_batch_keeps_claim_and_never_retries(prepared, monkeypatch):
    directory, _, _ = prepared
    monkeypatch.setitem(diagnostic.CAPS, "concurrency", 1)
    sent = []
    def failing(value):
        sent.append(value)
        raise TimeoutError("SYNTHETIC_PRIVATE_EXCEPTION")
    result = diagnostic.run(directory, failing)
    assert result["status"] == "stopped"
    assert len(sent) == result["attempts"] == result["unknown_usage_requests"] == 1
    assert "SYNTHETIC_PRIVATE_EXCEPTION" not in (directory / "execution.json").read_text()
    with pytest.raises(FileExistsError):
        diagnostic.run(directory, failing)


@pytest.mark.parametrize("field,value", [("requests", 1), ("output_tokens", 1024)])
def test_global_cap_records_incomplete_pair_without_resuming(prepared, monkeypatch, field, value):
    directory, _, _ = prepared
    monkeypatch.setitem(diagnostic.CAPS, "concurrency", 1)
    monkeypatch.setitem(diagnostic.CAPS, field, value)
    result = diagnostic.run(directory, sender)
    assert result["status"] == "stopped" and result["attempts"] == 1
    records = [helpers.read(path) for path in (directory / "runs").glob("item-*/*/result.json")]
    assert sum(r["status"] == "completed" for r in records) == 1
    assert sum(r.get("requests_sent", 0) for r in records) == 1
    assert any(r["status"] == "not_started" for r in records)


@pytest.mark.parametrize("text,expected", [
    ("Reasoning contains 4; final conclusion is 5.", ""),
    ("最终答案：4", "4"),
    ("最终答案：4\n最终答案：5", ""),
    ("最终答案：", ""),
    ("Derivation\n最终答案：1. 1/3; 2. 4/3", "1. 1/3; 2. 4/3"),
])
def test_grading_requires_unique_canonical_delivery(text, expected):
    assert diagnostic.answer_body(text) == expected


def test_candidate_coverage_excludes_reviews_and_truncation():
    events = [
        {"stage": "chat", "kind": "route", "finish_reason": "length", "response": "最终答案：1"},
        {"stage": "chat", "kind": "review", "finish_reason": "stop", "response": "最终答案：2"},
        {"stage": "chat", "kind": "route", "finish_reason": "stop", "response": "最终答案：3"},
        {"stage": "_aggregate", "before": [[{"answer": {"raw": "4"}}]]},
        {"stage": "chat", "kind": "repair", "finish_reason": "stop", "response": "最终答案：3"},
    ]
    assert diagnostic.candidate_answers(events) == ["3", "4"]


def test_analysis_separates_unknown_and_incomplete_pairs(prepared, monkeypatch):
    directory, plan, rows = prepared
    diagnostic.run(directory, sender)
    references = [{"idx": row["idx"], "expected": "4" if n == 0 else "unsupported semantic answer",
                   "independent_review": "fixture"} for n, row in enumerate(rows)]
    helpers.write(directory / "reference-audit.json", references)
    plan["reference_sha256"] = helpers.file_hash(directory / "reference-audit.json")
    monkeypatch.setattr(diagnostic, "check_plan", lambda p: (plan, rows))
    diagnostic.analyze(directory)
    report = helpers.read(directory / "analysis.json")
    assert report["strata"]["nonhit"]["complete_pairs"] == 2
    for variant in ("baseline", "candidate"):
        assert report["strata"]["nonhit"][variant]["correct"] == 1
        assert report["strata"]["nonhit"][variant]["unknown"] == 1
    assert report["items"][1]["variants"]["candidate"]["manual_review_required"]
    artifact = next((directory / "runs").glob("item-*/*/result.json"))
    artifact.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="modified execution result"):
        diagnostic.analyze(directory)


def test_diagnostic_json_roundtrip_and_seal_are_unicode_safe(tmp_path):
    rng = random.Random(13)
    for n in range(20):
        record = {"math": "积分 √x 最终答案：\n", "values": [rng.randint(-99, 99) for _ in range(n)]}
        path = tmp_path / "record.json"
        helpers.write(path, helpers.seal(record))
        recovered, digest = helpers.unseal(path)
        assert recovered == record
        assert digest == helpers.digest(json.loads(json.dumps(record)))
