import json
from pathlib import Path

from evaluation.experiments.freeze_experiment import RUNTIME_FILES, build_manifest, file_sha256
from scripts.build_release import ROOT_FILES


def _record(idx: str, problem: str, *, split: str = "test") -> dict:
    return {
        "idx": idx,
        "problem": problem,
        "answer": "1",
        "subject": "分析",
        "task_type": "calculation",
        "level": "competition",
        "source": "unit-test",
        "license": "test-only",
        "split": split,
    }


def _write_jsonl(path, rows):
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_freeze_manifest_records_dataset_code_and_agent_config(tmp_path):
    dataset = tmp_path / "benchmark.jsonl"
    _write_jsonl(dataset, [_record("a", "独立问题甲"), _record("b", "独立问题乙")])

    manifest = build_manifest(
        dataset,
        experiment_id="unit-baseline",
        model="test-model",
        dataset_role="public_test",
        repetitions=3,
        concurrency=1,
        minimum_items=2,
        allow_dirty=True,
    )

    assert manifest["dataset"]["sha256"] == file_sha256(dataset)
    assert manifest["dataset"]["items"] == 2
    assert manifest["code"]["commit"]
    assert len(manifest["code"]["runtime_sha256"]) == 64
    assert manifest["agent_config_sha256"]
    assert manifest["runner"] == {"repetitions": 3, "local_max_concurrency": 1}
    assert "task_router.py" in RUNTIME_FILES
    assert "deterministic_verifier.py" in RUNTIME_FILES
    assert "context.py" in RUNTIME_FILES
    assert "model_gateway.py" in RUNTIME_FILES
    assert "solver.py" in RUNTIME_FILES
    assert "candidate_generation.py" in RUNTIME_FILES
    assert "candidate_evaluation.py" in RUNTIME_FILES
    assert "candidate_selection.py" in RUNTIME_FILES
    assert "trace_sanitizer.py" in RUNTIME_FILES
    assert "agent_types.py" in RUNTIME_FILES
    assert not any(path.startswith("math_agent/") for path in RUNTIME_FILES)


def test_runtime_fingerprint_includes_every_root_module() -> None:
    root = Path(__file__).resolve().parents[1]
    root_modules = {
        path.relative_to(root).as_posix()
        for path in (root).glob("*.py")
    }

    assert root_modules <= set(RUNTIME_FILES)
    assert set(RUNTIME_FILES) == {
        path for path in ROOT_FILES if path.endswith(".py")
    }


def test_test_manifest_detects_cross_dataset_template_leakage(tmp_path):
    dataset = tmp_path / "test.jsonl"
    reference = tmp_path / "dev.jsonl"
    _write_jsonl(dataset, [_record("test", "计算 7^100 除以 13 的余数")])
    _write_jsonl(reference, [_record("dev", "计算 3^2024 除以 13 的余数", split="dev")])

    manifest = build_manifest(
        dataset,
        experiment_id="leak-test",
        model="test-model",
        dataset_role="public_test",
        repetitions=1,
        concurrency=1,
        minimum_items=1,
        reference_datasets=[reference],
        allow_dirty=True,
    )

    assert manifest["dataset"]["overlap_counts"]["template"] >= 1
    assert any("overlaps" in error for error in manifest["errors"])
