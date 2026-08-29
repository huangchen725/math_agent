import pytest

from evaluation.paired_compare import compare_reports, exact_mcnemar


def _report(correct_ids, *, total=12):
    rows = []
    for number in range(total):
        idx = f"p{number}"
        rows.append(
            {
                "idx": idx,
                "status": "correct" if idx in correct_ids else "wrong",
                "subject": "分析" if number % 2 else "代数",
                "level": "competition",
                "task_type": "proof",
            }
        )
    return {
        "summary": {
            "invalid": 0,
            "error": 0,
            "missing": 0,
            "usage": {"truncated_fragments_in_final": 0},
        },
        "provenance": {
            "dataset_sha256": "dataset-hash",
            "model": "Intern-S2-Preview-35B",
        },
        "results": rows,
    }


def _manifest(commit):
    return {
        "status": "frozen",
        "dataset": {"sha256": "dataset-hash"},
        "code": {"commit": commit},
        "model": {"configured_name": "intern-s2-preview"},
        "runner": {"repetitions": 3, "local_max_concurrency": 1},
    }


def test_exact_mcnemar_uses_paired_discordant_items():
    result = exact_mcnemar(candidate_only=5, baseline_only=0)

    assert result["one_sided_improvement_p"] == pytest.approx(1 / 32)
    assert result["two_sided_p"] == pytest.approx(1 / 16)


def test_paired_comparison_requires_and_recognizes_supported_gain():
    baseline_correct = {"p0", "p1"}
    candidate_correct = {f"p{number}" for number in range(12)}
    baseline_reports = [_report(baseline_correct) for _ in range(3)]
    candidate_reports = [_report(candidate_correct) for _ in range(3)]

    result = compare_reports(
        baseline_reports,
        candidate_reports,
        baseline_manifest=_manifest("old"),
        candidate_manifest=_manifest("new"),
        candidate_reliability_gate={"passed": True},
        bootstrap_samples=2_000,
        seed=1,
    )

    assert result["summary"]["accuracy_delta"] == pytest.approx(10 / 12)
    assert result["summary"]["paired_bootstrap_95"][0] > 0
    assert result["comparability"]["verified"] is True
    assert result["decision"]["ability_improvement_demonstrated"] is True


def test_directional_gain_without_frozen_manifests_is_insufficient():
    baseline = [_report({"p0"}) for _ in range(3)]
    candidate = [_report({"p0", "p1"}) for _ in range(3)]

    result = compare_reports(
        baseline,
        candidate,
        candidate_reliability_gate={"passed": True},
        bootstrap_samples=200,
    )

    assert result["comparability"]["verified"] is False
    assert result["decision"]["ability_improvement_demonstrated"] is False


def test_report_dataset_hash_must_match_frozen_manifest():
    baseline = [_report({"p0"}) for _ in range(3)]
    candidate = [_report({"p0", "p1"}) for _ in range(3)]
    candidate[0]["provenance"]["dataset_sha256"] = "different-hash"

    result = compare_reports(
        baseline,
        candidate,
        baseline_manifest=_manifest("old"),
        candidate_manifest=_manifest("new"),
        candidate_reliability_gate={"passed": True},
        bootstrap_samples=200,
    )

    assert result["comparability"]["verified"] is False
    assert any("dataset hash" in error for error in result["comparability"]["errors"])
