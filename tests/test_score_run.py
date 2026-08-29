import json

from evaluation.score_run import extract_final_answer, score_run


def test_extract_final_answer_uses_last_canonical_line():
    response = "推理\n最终答案：旧值\n检查\n最终答案：1/R"

    assert extract_final_answer(response) == "1/R"


def test_score_run_counts_judgments_errors_missing_and_usage(tmp_path):
    dataset = [
        {"idx": "a", "problem": "p", "answer": "1", "subject": "数论"},
        {"idx": "b", "problem": "p", "answer": "Z", "subject": "拓扑"},
        {"idx": "c", "problem": "p", "answer": "2", "subject": "数论"},
        {"idx": "d", "problem": "p", "answer": "3", "subject": "数论"},
    ]
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "status": "success",
                "final_response": "最终答案：1",
                "trace": [
                    {
                        "step": "budget_summary",
                        "content": {
                            "model_requests": 3,
                            "total_tokens": 100,
                            "truncated_responses": 1,
                            "requests_by_stage": {"policy_plain": 2, "verifier": 1},
                            "truncated_by_stage": {"policy_plain": 1},
                            "truncation_recovery": {
                                "required": 1,
                                "handled": 1,
                                "succeeded": 1,
                                "failed": 0,
                            },
                            "truncated_fragments_in_final": 0,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            {
                "status": "success",
                "final_response": "最终答案：圆周的基本群是整数群。",
                "trace": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "c.json").write_text(
        json.dumps({"status": "error", "error": {"type": "Timeout"}}),
        encoding="utf-8",
    )

    scored = score_run(dataset, tmp_path)

    assert scored["summary"]["correct"] == 1
    assert scored["summary"]["unknown"] == 1
    assert scored["summary"]["error"] == 1
    assert scored["summary"]["missing"] == 1
    assert scored["summary"]["usage"]["model_requests"] == 3
    assert scored["summary"]["usage"]["truncated_responses"] == 1
    truncation = scored["summary"]["truncation"]
    assert truncation["truncation_rate"] == 1 / 3
    assert truncation["by_stage"]["policy_plain"]["truncated_count"] == 1
    assert truncation["problems_with_truncation"] == 1
    assert truncation["recovery"]["coverage"] == 1.0
    assert truncation["valid_answer_rate_after_truncation"] == 1.0
    assert scored["by_subject"]["数论"]["total"] == 3
