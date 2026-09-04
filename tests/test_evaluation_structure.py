import hashlib
import importlib
from pathlib import Path

import pytest

from evaluation.io_utils import (
    file_sha256,
    read_json_object,
    read_jsonl_objects,
    write_json,
    write_jsonl,
)


def test_shared_evaluation_io_round_trips_atomically(tmp_path: Path) -> None:
    json_path = tmp_path / "nested" / "report.json"
    jsonl_path = tmp_path / "nested" / "rows.jsonl"
    report = {"message": "数学", "count": 2}
    rows = [{"idx": "a", "problem": "题目甲"}, {"idx": "b", "problem": "题目乙"}]

    write_json(json_path, report)
    write_jsonl(jsonl_path, rows)

    assert read_json_object(json_path) == report
    assert read_jsonl_objects(
        jsonl_path,
        required_nonempty_strings=("problem",),
    ) == rows
    assert file_sha256(json_path) == hashlib.sha256(json_path.read_bytes()).hexdigest()
    assert not list((tmp_path / "nested").glob("*.tmp"))


def test_shared_evaluation_io_rejects_non_object_json(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ValueError, match="not a JSON object"):
        read_json_object(path)


def test_evaluation_modules_are_grouped_without_sys_path_mutation() -> None:
    evaluation_root = Path(__file__).resolve().parents[1] / "evaluation"
    assert {path.name for path in evaluation_root.glob("*.py")} == {
        "__init__.py",
        "io_utils.py",
    }
    for path in evaluation_root.rglob("*.py"):
        assert "sys.path" not in path.read_text(encoding="utf-8")

    modules = (
        "evaluation.data.audit_dataset",
        "evaluation.data.generate_internal_benchmark",
        "evaluation.data.import_putnam_bench",
        "evaluation.scoring.judge",
        "evaluation.scoring.rescore_report",
        "evaluation.scoring.score_run",
        "evaluation.scoring.truncation_gate",
        "evaluation.experiments.freeze_experiment",
        "evaluation.experiments.blind_review",
        "evaluation.experiments.paired_compare",
    )
    for module in modules:
        importlib.import_module(module)
