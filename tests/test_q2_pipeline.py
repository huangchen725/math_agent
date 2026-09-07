"""Q2 statistics and workflow counterexamples. All clients/data here are synthetic."""
import copy
import json
from pathlib import Path
import random

import pytest

from evaluation.q0_pipeline import digest, freeze_records, write_bundle
from evaluation import q2_pipeline as q2


def bundle_at(path, count=40):
    rng = random.Random(204)
    rows = [{"idx": str(i), "problem": "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(100)),
        "answer": "2", "subject": "fixture", "level": "synthetic", "task_type": "free_response",
        "source": "fixture://q2-workflow", "license": "MIT"} for i in range(count)]
    rows, selection = freeze_records(rows, per_subject=count, references=[])
    write_bundle(path, rows, selection)
    return path


def runs(statuses, *, repeats=3, execution="real", metric_complete=True):
    # 'real' exercises the gate with synthetic records; it is not a live-model result.
    return [{"execution": execution, "rows": [{"idx": str(i), "status": s,
        "reference_sha256": digest([i]), "subject": "fixture", "invalid": s == "no_answer"}
        for i, s in enumerate(statuses)], "receipt": {"complete": metric_complete,
        "requests": 40, "attempts": 40, "total_tokens": 1000, "elapsed_ms": 1000,
        "truncated_requests": 0}} for _ in range(repeats)]


def compare(a, b, **kwargs):
    return q2.compare_repeats(a, b, q2.DEFAULT_RULES, **kwargs)


def test_clear_paired_gain_and_loss_have_opposite_decisions():
    old, new = runs(["wrong"]*20), runs(["correct"]*20)
    good, bad = compare(old,new), compare(new,old)
    assert good["status"] == "eligible"
    assert good["unknown_worst_case_cluster_interval"] == [1.0,1.0]
    assert bad["status"] == "reject"
    assert good["mean_accuracy_delta"] == -bad["mean_accuracy_delta"]


def test_repeated_identical_observations_do_not_inflate_independent_sample():
    before = ["wrong"]*10+["correct"]*10
    after = ["correct"]*20
    three, ten = compare(runs(before), runs(after)), compare(runs(before,repeats=10), runs(after,repeats=10))
    assert three["independent_items"] == ten["independent_items"] == 20
    assert three["unknown_worst_case_cluster_interval"] == ten["unknown_worst_case_cluster_interval"]


def test_item_and_repeat_order_do_not_change_statistics():
    left, right = runs(["wrong"]*10+["correct"]*10), runs(["correct"]*15+["wrong"]*5)
    original = compare(left,right)
    for run in left+right:
        run["rows"].reverse()
    assert compare(left[::-1],right[::-1]) == original


@pytest.mark.parametrize("alpha", [0.05, 0.01])
def test_bootstrap_sign_symmetry_and_bounds(alpha):
    values = [-1,0,1,1,0]*4
    a = q2.paired_bootstrap(values,alpha=alpha,samples=1000,seed=17)
    b = q2.paired_bootstrap([-x for x in values],alpha=alpha,samples=1000,seed=17)
    assert a == [-b[1],-b[0]]
    assert -1 <= a[0] <= a[1] <= 1


def test_multiplicity_correction_cannot_tighten_interval():
    a,b = runs(["wrong"]*10+["correct"]*10), runs(["correct"]*20)
    one = compare(a,b)["unknown_worst_case_cluster_interval"]
    nine = compare(a,b,comparisons=9)["unknown_worst_case_cluster_interval"]
    assert nine[0] <= one[0] <= one[1] <= nine[1]


@pytest.mark.parametrize("status", ["unknown", "no_answer", "error", "missing", "wrong"])
def test_noncorrect_states_are_preserved_in_transitions(status):
    result = compare(runs([status]*20), runs(["correct"]*20))
    assert result["transitions"] == {status+"->correct":60}
    if status == "unknown":
        assert result["status"] == "inconclusive"
        assert result["unknown_worst_case_cluster_interval"] == [0.0,0.0]


@pytest.mark.parametrize("condition", ["fixture", "missing_metrics", "high_cost", "more_truncation", "tiny_sample", "negative_repeat"])
def test_unacceptable_or_insufficient_evidence_cannot_promote(condition):
    left, right = runs(["wrong"]*20), runs(["correct"]*20)
    if condition == "fixture":
        right[0]["execution"] = "fixture"
    elif condition == "missing_metrics":
        right[0]["receipt"] = None
    elif condition == "high_cost":
        right[0]["receipt"]["total_tokens"] = 10000
    elif condition == "more_truncation":
        right[0]["receipt"]["truncated_requests"] = 1
    elif condition == "tiny_sample":
        for r in left+right:
            r["rows"] = r["rows"][:2]
    else:
        for row in left[0]["rows"]:
            row["status"] = "correct"
        for row in right[0]["rows"]:
            row["status"] = "wrong"
    assert compare(left,right)["status"] != "eligible"


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "reference", "across_repeat", "status", "subject"])
def test_malformed_pairing_is_rejected(mutation):
    left,right = runs(["wrong"]*20),runs(["correct"]*20)
    if mutation == "duplicate":
        right[0]["rows"].append(right[0]["rows"][0])
    elif mutation == "missing":
        right[0]["rows"].pop()
    elif mutation == "reference":
        right[0]["rows"][0]["reference_sha256"] = "different"
    elif mutation == "across_repeat":
        for side in (left,right):
            side[1]["rows"][0]["reference_sha256"] = "different"
    elif mutation == "status":
        right[0]["rows"][0]["status"] = "PASS"
    else:
        right[0]["rows"][0]["subject"] = "other"
    with pytest.raises(ValueError):
        compare(left,right)


class OwnedFixtureClient:
    def __init__(self, answer="2", metadata=True):
        self.answer, self.metadata = answer, metadata

    def chat(self, *, messages, temperature, max_tokens, meta_sink, **kwargs):
        if self.metadata:
            meta_sink({"model":"intern-s2-preview-397b", "usage":{"total_tokens":2},
                       "attempts":1, "finish_reason":"stop"})
        return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案："+self.answer


def finish_slot(study, variant, repeat, *, split="dev", execution="fixture", receipt=True):
    ticket = q2.reserve(study,variant,repeat,split=split)
    client = q2.ObservedTextClient(OwnedFixtureClient("3" if variant=="baseline" else "2"))
    output = study/f"{split}-{variant}-{repeat}"
    q2.run_reserved(study,ticket["slot"],output,client,execution=execution)
    # Deterministic synthetic elapsed cost, never a claimed real measurement.
    path = output/"_run"/"run_summary.json"
    summary = q2.read(path)
    summary["duration_ms"] = 1000
    q2.write(path,summary)
    telemetry = q2.receipt_from_observations(output,client.observations) if receipt else None
    q2.record(study,ticket["slot"],output,telemetry)
    return output


@pytest.fixture
def study(tmp_path):
    bundle = bundle_at(tmp_path/"bundle")
    path = tmp_path/"study"
    q2.create_study(bundle,path,candidates=["calibrated_verifier"])
    return path


def test_fixture_workflow_never_opens_holdout(study):
    for repeat in range(3):
        for variant in ("baseline","calibrated_verifier"):
            finish_slot(study,variant,repeat)
    report = q2.evaluate(study)
    assert report["candidates"]["calibrated_verifier"]["status"] == "inconclusive"
    diagnostic = report["candidates"]["calibrated_verifier"]["diagnostics"]
    assert diagnostic["candidate"]["statuses"] == {"correct": 60}
    assert diagnostic["baseline"]["statuses"] == {"wrong": 60}
    assert diagnostic["candidate"]["invalid_rate"] == 0
    assert diagnostic["candidate"]["request_metrics"]["truncated_requests"] == 0
    with pytest.raises(ValueError):
        q2.select(study,"calibrated_verifier")
    with pytest.raises(ValueError):
        q2.reserve(study,"baseline",0,split="test")


def test_synthetic_receipt_gate_selection_and_holdout_close(study):
    # Synthetic 'real' labels exercise the state machine, not actual model evidence.
    for repeat in range(3):
        for variant in ("baseline","calibrated_verifier"):
            finish_slot(study,variant,repeat,execution="real")
    q2.select(study,"calibrated_verifier")
    with pytest.raises(ValueError):
        q2.select(study,"calibrated_verifier")
    for repeat in range(3):
        for variant in ("baseline","calibrated_verifier"):
            finish_slot(study,variant,repeat,split="test",execution="real")
    result = q2.acceptance(study)
    assert result["candidates"]["calibrated_verifier"]["status"] == "eligible"
    assert q2.load_study(study)[1]["phase"] == "closed"
    with pytest.raises(ValueError):
        q2.acceptance(study)
    # Closed acceptance must still revalidate the original raw evidence.
    next((study/"dev-baseline-0").glob("*.json")).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        q2.delivery_check(study, expected_commit="unused", remote_commit="unused")


def test_failed_attempt_cannot_be_retried_or_reassigned(study):
    ticket = q2.reserve(study,"baseline",0)
    with pytest.raises(ValueError):
        q2.reserve(study,"baseline",0)
    client = q2.ObservedTextClient(OwnedFixtureClient())
    q2.run_reserved(study,ticket["slot"],study/"run",client)
    with pytest.raises(FileExistsError):
        q2.run_reserved(study,ticket["slot"],study/"rerun",client)
    with pytest.raises(ValueError):
        q2.record(study,"dev:baseline:1",study/"run")


@pytest.mark.parametrize("mutation", ["checkpoint", "receipt", "manifest"])
def test_registered_evidence_cannot_change(study, mutation):
    output = None
    for repeat in range(3):
        for variant in ("baseline","calibrated_verifier"):
            output = finish_slot(study,variant,repeat)
    if mutation == "checkpoint":
        next(output.glob("*.json")).write_text("{}",encoding="utf-8")
    elif mutation == "manifest":
        path=output/"_run"/"run_summary.json"
        data=q2.read(path);data["run_id"]="other";q2.write(path,data)
    else:
        state=q2.unseal(q2.read(study/"state.json"))
        state["runs"]["dev:baseline:0"]["data"]["receipt"]["requests"] += 1
        q2.write(study/"state.json",q2.seal(state))
    with pytest.raises(ValueError):
        q2.evaluate(study)


@pytest.mark.parametrize("field,value", [("min_delta",0), ("bootstrap_samples",10**9), ("max_cost_ratio",float("inf"))])
def test_frozen_rules_cannot_be_relaxed(study,field,value):
    p=q2.unseal(q2.read(study/"protocol.json"));p["rules"][field]=value
    if not isinstance(value,float):
        q2.write(study/"protocol.json",q2.seal(p))
        with pytest.raises(ValueError):q2.load_study(study)
    else:
        with pytest.raises(ValueError):q2.seal(p)


def test_incomplete_preregistered_matrix_cannot_select(study):
    finish_slot(study,"baseline",0)
    result=q2.evaluate(study)
    assert result["status"]=="incomplete" and len(result["missing_slots"])==5
    with pytest.raises(ValueError):q2.select(study,"calibrated_verifier")


def test_stale_code_or_dataset_rejected(study,monkeypatch):
    monkeypatch.setattr(q2,"analysis_hash",lambda:"changed")
    with pytest.raises(ValueError):q2.load_study(study)


def test_shared_holdout_marker_blocks_another_study(study):
    for repeat in range(3):
        for variant in ("baseline","calibrated_verifier"):
            finish_slot(study,variant,repeat,execution="real")
    q2.select(study,"calibrated_verifier")
    p,state=q2.load_study(study)
    marker=Path(p["bundle"])/".q2-holdout-use.json"
    q2.write(marker,{"study_id":"another","protocol_sha256":"another"})
    with pytest.raises(ValueError,match="another study"):
        q2.reserve(study,"baseline",0,split="test")


def test_absent_metadata_is_unknown_not_free_cost(study):
    ticket=q2.reserve(study,"baseline",0)
    client=q2.ObservedTextClient(OwnedFixtureClient(metadata=False))
    output=study/"missing-meta"
    q2.run_reserved(study,ticket["slot"],output,client)
    receipt=q2.receipt_from_observations(output,client.observations)
    assert receipt["complete"] is False and receipt["total_tokens"] is None
    q2.record(study,ticket["slot"],output,receipt)


@pytest.mark.parametrize("nonce", ["../escape", "C:/escape", "", "a"*100])
def test_ticket_nonce_cannot_escape_study(study,nonce):
    ticket=q2.reserve(study,"baseline",0)
    state=q2.unseal(q2.read(study/"state.json"))
    state["tickets"][ticket["slot"]]["nonce"]=nonce
    q2.write(study/"state.json",q2.seal(state))
    with pytest.raises(ValueError):
        q2.run_reserved(study,ticket["slot"],study/"run",q2.ObservedTextClient(OwnedFixtureClient()))
