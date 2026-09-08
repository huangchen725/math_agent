import copy
import json
from pathlib import Path

import pytest

from evaluation.audit_dataset import ReferenceProblem
from evaluation.q0_pipeline import (freeze_records, write_bundle, verify_bundle, paired_comparison,
    review_packet, reconcile_reviews, score_bound_run, near_template)
from evaluation.q1_experiments import make_plan, run_plan, VARIANTS
from evaluation.score_run import score_run


def examples():
    return [{"idx": str(i), "problem": p, "answer": "2", "subject": "algebra", "level": "university",
        "task_type": "free_response", "source": "fixture://independent-regression", "license": "MIT"}
        for i,p in enumerate(["计算1+1", "求未知数", "判断是否收敛", "计算矩阵的秩"])]


def bundle_at(path):
    rows, selection = freeze_records(examples(), per_subject=4, references=[])
    write_bundle(path, rows, selection)
    return path


def test_freeze_order_independent_and_inputs_never_include_references(tmp_path):
    left, a = freeze_records(examples(), per_subject=4, references=[])
    right, _ = freeze_records(list(reversed(examples())), per_subject=4, references=[])
    assert left == right
    write_bundle(tmp_path/"bundle", left, a)
    verify_bundle(tmp_path/"bundle")
    for split in ("dev", "test"):
        for line in (tmp_path/"bundle"/f"{split}.input.jsonl").read_text(encoding="utf-8").splitlines():
            assert set(json.loads(line)) == {"idx", "problem"}


@pytest.mark.parametrize("idx", ["../escape", "..", "a/b", "C:\\escape", "", "a"*129])
def test_malicious_ids_rejected_before_filesystem_use(tmp_path, idx):
    records = examples()
    records[0]["idx"] = idx
    with pytest.raises(ValueError):
        freeze_records(records, references=[])
    with pytest.raises(ValueError):
        score_run(records, tmp_path)


def test_duplicate_ids_and_parameter_swaps_cannot_cross_splits():
    records = examples()
    records.append({**records[0], "idx": "new", "problem": "计算2+2"})
    rows, selection = freeze_records(records, per_subject=4, references=[])
    assert selection["excluded"]["duplicate_template"] == 1
    assert len(rows) == 4
    with pytest.raises(ValueError):
        freeze_records(examples()+[examples()[0]], references=[])


def test_near_duplicates_are_removed_before_split_assignment():
    rows = examples()
    rows[0]["problem"] = "Find all integer solutions for the following quadratic polynomial equation x squared plus x equals two"
    rows.append({**rows[0], "idx": "near", "problem": rows[0]["problem"] + "."})
    rows.append({**rows[0], "idx": "near2", "problem": rows[0]["problem"].replace("integer", "real")})
    frozen, selection = freeze_records(rows, per_subject=4, references=[])
    assert len(frozen) == 4
    assert selection["excluded"].get("duplicate_template", 0) + selection["excluded"].get("near_template", 0) == 2


def test_similarity_decision_is_commutative_under_bounded_edits():
    import random
    rng = random.Random(906)
    for _ in range(400):
        left = "".join(rng.choice("abcde123") for _ in range(40))
        right = left
        for _ in range(6):
            pos = rng.randrange(len(right))
            right = right[:pos] + rng.choice("abcde123") + right[pos+1:]
        assert near_template(left, right) == near_template(right, left)


def test_reference_overlap_blocks_freeze_when_coverage_insufficient():
    with pytest.raises(ValueError, match="insufficient"):
        freeze_records(examples(), per_subject=4, references=[ReferenceProblem("prompt", "", "计算1+1")])


@pytest.mark.parametrize("name", ["dev.labels.jsonl", "test.input.jsonl"])
def test_frozen_file_tamper_rejected(tmp_path, name):
    bundle = bundle_at(tmp_path/"bundle")
    with (bundle/name).open("a", encoding="utf-8") as f:
        f.write("\n")
    with pytest.raises(ValueError, match="changed"):
        verify_bundle(bundle)


def test_freeze_refuses_overwrite(tmp_path):
    bundle_at(tmp_path/"bundle")
    with pytest.raises(ValueError, match="overwrite"):
        bundle_at(tmp_path/"bundle")


class Client:
    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        assert "fixture://" not in str(messages)
        return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：2"


def fixture_report(tmp_path):
    bundle = bundle_at(tmp_path/"bundle")
    plan = make_plan(bundle)
    output = tmp_path/"run"
    run_plan(plan, "baseline", bundle, output, Client())
    report = score_bound_run(bundle, "dev", output, model=plan["model"], code_sha=plan["code_sha"],
        config=plan["variants"]["baseline"], execution="fixture")
    return bundle, plan, output, report


def test_end_to_end_bound_fixture_and_same_task_pairing(tmp_path):
    _, _, _, report = fixture_report(tmp_path)
    paired = paired_comparison(report, report)
    assert paired["gains"] == paired["losses"] == 0
    assert paired["claim"] == "fixture diagnostics only"
    assert report["summary"]["total"] == 2


@pytest.mark.parametrize("key", ["model", "code_sha", "config", "input_sha256", "execution", "status"])
def test_run_provenance_tampering_is_rejected(tmp_path, key):
    bundle, plan, output, _ = fixture_report(tmp_path)
    path = output/"_run"/"run_summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    summary[key] = "tampered"
    path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError):
        score_bound_run(bundle, "dev", output, model=plan["model"], code_sha=plan["code_sha"],
            config=plan["variants"]["baseline"], execution="fixture")


@pytest.mark.parametrize("key", ["model", "dataset_sha256", "split", "execution", "scoring_sha256"])
def test_incomparable_models_or_datasets_cannot_be_paired(tmp_path, key):
    _, _, _, report = fixture_report(tmp_path)
    other = copy.deepcopy(report)
    other["provenance"][key] = "different"
    with pytest.raises(ValueError):
        paired_comparison(report, other)


def test_blind_review_needs_two_complete_independent_votes(tmp_path):
    _, _, _, report = fixture_report(tmp_path)
    packet = review_packet(examples(), report, salt="fixture")
    assert "model" not in json.dumps(packet)
    decisions = {x["review_id"]: "correct" for x in packet["items"]}
    first = {"reviewer": "a", "packet_sha256": packet["packet_sha256"], "decisions": decisions}
    with pytest.raises(ValueError):
        reconcile_reviews(packet, first, first)
    second = copy.deepcopy(first)
    second["reviewer"] = "b"
    second["decisions"][next(iter(decisions))] = "wrong"
    result = reconcile_reviews(packet, first, second)
    assert sum(v["disagreement"] for v in result.values()) == 1
    assert all(v["status"] == "unknown" for v in result.values() if v["disagreement"])


def test_each_ablation_has_exactly_one_variable(tmp_path):
    plan = make_plan(bundle_at(tmp_path/"bundle"))
    baseline = plan["variants"]["baseline"]
    for name in VARIANTS:
        if name in {"baseline", "combined"}:
            continue
        actual = plan["variants"][name]
        changes = [(kind,k) for kind in baseline for k,v in baseline[kind].items() if actual[kind][k] != v]
        assert len(changes) == 1


def test_stale_code_plan_cannot_make_any_request(tmp_path):
    bundle = bundle_at(tmp_path/"bundle")
    plan = make_plan(bundle)
    plan["code_sha"] = "0"*64
    with pytest.raises(ValueError, match="stale"):
        run_plan(plan, "baseline", bundle, tmp_path/"run", Client())
    assert not (tmp_path/"run").exists()


def test_new_prompt_experiments_do_not_expand_legacy_combined(tmp_path):
    plan = make_plan(bundle_at(tmp_path/"bundle"))
    baseline = plan["variants"]["baseline"]["policy"]
    assert not any(baseline.values())
    assert {k for k, v in plan["variants"]["combined"]["policy"].items() if v} == {
        "recover_plain", "deterministic", "compact_routing", "calibrated_verifier", "diverse_candidates"}
    for name in ("tool_aware_prompts", "concise_recovery"):
        candidate = plan["variants"][name]
        assert candidate["agent"] == plan["variants"]["baseline"]["agent"]
        assert {k for k, v in candidate["policy"].items() if v} == {name}


def test_scoring_nan_and_checkpoint_mismatch_are_diagnostic_not_crashes(tmp_path):
    (tmp_path/"0.json").write_text(json.dumps({"idx": "wrong", "status": "success", "final_response": "最终答案：2"}), encoding="utf-8")
    result = score_run([examples()[0]], tmp_path)
    assert result["summary"]["error"] == 1
    (tmp_path/"0.json").write_text(json.dumps({"status": "success", "final_response": "最终答案：2",
        "trace": [{"step": "budget_summary", "content": {"total_tokens": float("nan")}}]}), encoding="utf-8")
    assert score_run([examples()[0]], tmp_path)["summary"]["correct"] == 1


def test_checkpoint_tampering_cannot_reuse_a_bound_run(tmp_path):
    bundle, plan, output, _ = fixture_report(tmp_path)
    next(output.glob("*.json")).write_text('{}', encoding="utf-8")
    with pytest.raises(ValueError, match="checkpoint changed"):
        score_bound_run(bundle, "dev", output, model=plan["model"], code_sha=plan["code_sha"],
            config=plan["variants"]["baseline"], execution="fixture")


def test_plan_budget_tampering_cannot_execute(tmp_path):
    bundle = bundle_at(tmp_path/"bundle")
    plan = make_plan(bundle)
    plan["variants"]["baseline"]["agent"]["max_model_requests"] = 999
    with pytest.raises(ValueError, match="frozen ablation"):
        run_plan(plan, "baseline", bundle, tmp_path/"run", Client())


@pytest.mark.parametrize("variant", VARIANTS)
def test_all_ablation_variants_execute_strict_public_client(tmp_path, variant):
    bundle = bundle_at(tmp_path/"bundle")
    plan = make_plan(bundle)
    summary = run_plan(plan, variant, bundle, tmp_path/"run", Client())
    assert summary["completed_items"] == 2
    assert summary["execution"] == "fixture"
    assert summary["status"] == "complete"


def test_local_tool_plan_runs_with_explicit_adapter_and_cannot_mix_protocols(tmp_path):
    from local_support.xh202627_local_adapter import LocalToolAdapter
    bundle = bundle_at(tmp_path/"bundle")
    plan = make_plan(bundle, local_tools=True)
    class ToolClient:
        def chat(self, messages, temperature, max_tokens, meta_sink, **kwargs):
            meta_sink({"usage": {"total_tokens": 3}, "finish_reason": "stop"})
            return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：2"
    client = ToolClient()
    with pytest.raises(ValueError, match="tool capability"):
        run_plan(plan, "baseline", bundle, tmp_path/"no-adapter", client)
    run_plan(plan, "baseline", bundle, tmp_path/"run", client, local_adapter=LocalToolAdapter(client))
    report = score_bound_run(bundle, "dev", tmp_path/"run", model=plan["model"], code_sha=plan["code_sha"],
        config=plan["variants"]["baseline"], execution="fixture", local_tools=True)
    assert report["summary"]["usage"]["total_tokens"] == 36
    assert report["provenance"]["local_tools"] is True
    other = copy.deepcopy(report)
    other["provenance"]["local_tools"] = False
    with pytest.raises(ValueError, match="local_tools"):
        paired_comparison(report, other)
