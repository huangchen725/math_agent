import argparse
import asyncio
import json
import hashlib
from pathlib import Path

import pytest

import main
from main import (
    build_output_record,
    build_run_summary,
    file_sha256,
    is_processed,
    load_jsonl,
    result_path,
)


def test_result_path_accepts_safe_idx(tmp_path: Path):
    assert result_path(tmp_path, {"idx": "Q_01-a"}) == tmp_path / "Q_01-a.json"


@pytest.mark.parametrize("idx", ["../escape", "a/b", "a\\b", "", "x" * 129])
def test_result_path_rejects_unsafe_idx(tmp_path: Path, idx: str):
    with pytest.raises(ValueError, match="idx"):
        result_path(tmp_path, {"idx": idx})


def test_is_processed_requires_valid_success_record(tmp_path: Path):
    path = tmp_path / "1.json"
    assert is_processed(path) is False

    path.write_text("not json", encoding="utf-8")
    assert is_processed(path) is False

    path.write_text(json.dumps({"status": "error", "final_response": "x"}), encoding="utf-8")
    assert is_processed(path) is False

    path.write_text(json.dumps({"status": "success", "final_response": "  "}), encoding="utf-8")
    assert is_processed(path) is False

    path.write_text(json.dumps({"status": "success", "final_response": "42"}), encoding="utf-8")
    assert is_processed(path) is True


def test_load_jsonl_validates_problem_and_duplicate_idx(tmp_path: Path):
    path = tmp_path / "input.jsonl"
    path.write_text(
        '{"idx": "same", "problem": "1+1"}\n'
        '{"idx": "same", "problem": "2+2"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Duplicate idx"):
        load_jsonl(path)

    path.write_text('{"idx": "ok", "problem": ""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty problem"):
        load_jsonl(path)


def test_build_output_record_preserves_unsolved_trace_for_diagnosis():
    record = build_output_record(
        {"idx": 1},
        {
            "final_response": "未解出",
            "trace": [{"step": "global_error", "content": "rate limited"}],
        },
    )

    assert record["status"] == "error"
    assert record["error"]["type"] == "Unsolved"
    assert record["trace"] == [
        {"step": "global_error", "content": "rate limited"}
    ]


def test_file_sha256_and_run_summary_are_reproducible(tmp_path: Path):
    input_path = tmp_path / "input.jsonl"
    content = b'{"problem":"1+1"}\n'
    input_path.write_bytes(content)

    assert file_sha256(input_path) == hashlib.sha256(content).hexdigest()

    summary = build_run_summary(
        statuses=["success", "error", "skipped", "success"],
        input_path=input_path,
        input_sha256="abc",
        model="test-model",
        duration_ms=12,
        started_at="2026-08-29T00:00:00+00:00",
    )
    assert summary["status"] == "completed_with_errors"
    assert summary["total_items"] == 4
    assert summary["success"] == 2
    assert summary["error"] == 1
    assert summary["skipped"] == 1
    assert summary["input_file"] == "input.jsonl"


def test_run_writes_results_and_privacy_safe_summary(tmp_path: Path, monkeypatch):
    input_path = tmp_path / "private_questions.jsonl"
    input_path.write_text(
        '{"idx":"a","problem":"secret problem one"}\n'
        '{"idx":"b","problem":"secret problem two"}\n',
        encoding="utf-8",
    )
    output_dir = tmp_path / "outputs"

    class FakeClient:
        model = "fake-model"

    class FakeAgent:
        def __init__(self, client):
            self.client = client

        def solve(self, problem, metadata):
            return {"final_response": "推理\n最终答案：2", "trace": []}

    monkeypatch.setattr(main, "InternChatClient", FakeClient)
    monkeypatch.setattr(main, "ReasoningAgent", FakeAgent)
    args = argparse.Namespace(input_file=str(input_path), output_dir=str(output_dir))

    asyncio.run(main.run(args))

    assert json.loads((output_dir / "a.json").read_text(encoding="utf-8"))["status"] == "success"
    summary_text = (output_dir / "_run" / "run_summary.json").read_text(encoding="utf-8")
    summary = json.loads(summary_text)
    assert summary["success"] == 2
    assert summary["model"] == "fake-model"
    assert "secret problem" not in summary_text
