import json

import pytest

from evaluation.blind_review import create_review_packet, resolve_review


def _write_result(directory, idx, answer):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{idx}.json").write_text(
        json.dumps(
            {
                "status": "success",
                "final_response": f"Reasoning\n最终答案：{answer}",
                "trace": [],
            }
        ),
        encoding="utf-8",
    )


def test_blind_packet_randomizes_labels_and_resolves_them(tmp_path):
    baseline_dir = tmp_path / "baseline"
    candidate_dir = tmp_path / "candidate"
    dataset = [
        {"idx": "p1", "problem": "P1", "answer": "1"},
        {"idx": "p2", "problem": "P2", "answer": "2"},
    ]
    for item in dataset:
        _write_result(baseline_dir, item["idx"], "old")
        _write_result(candidate_dir, item["idx"], "new")

    packet, key = create_review_packet(
        dataset,
        baseline_dir,
        candidate_dir,
        blinding_secret="unit-test-secret",
    )
    completed = []
    for row in packet:
        completed.append(
            {
                **row,
                "a_status": "correct",
                "b_status": "wrong",
                "reviewer_id": "reviewer-1",
            }
        )

    baseline, candidate = resolve_review(completed, key)
    by_baseline = {item["idx"]: item["status"] for item in baseline}
    by_candidate = {item["idx"]: item["status"] for item in candidate}
    for idx, mapping in key["mappings"].items():
        expected_baseline = "correct" if mapping["a"] == "baseline" else "wrong"
        expected_candidate = "correct" if mapping["a"] == "candidate" else "wrong"
        assert by_baseline[idx] == expected_baseline
        assert by_candidate[idx] == expected_candidate


def test_resolve_rejects_unidentified_review(tmp_path):
    packet = [{"idx": "p1", "a_status": "correct", "b_status": "wrong", "blind": True}]
    key = {"mappings": {"p1": {"a": "baseline", "b": "candidate"}}}

    with pytest.raises(ValueError, match="reviewer_id"):
        resolve_review(packet, key)
