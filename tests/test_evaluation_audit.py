import json
from pathlib import Path

import pytest

from evaluation.data.audit_dataset import (
    ReferenceProblem,
    audit_dataset,
    normalize_problem,
    normalize_template,
    wilson_interval,
)


def test_problem_normalization_distinguishes_values_but_template_finds_copy():
    first = "计算 7^100 除以 13 的余数。"
    second = "计算 3^2024 除以 13 的余数"

    assert normalize_problem(first) != normalize_problem(second)
    assert normalize_template(first) == normalize_template(second)


def test_audit_reports_prompt_overlap_and_missing_provenance():
    records = [
        {
            "idx": 1,
            "subject": "数论",
            "problem": "计算 7^100 除以 13 的余数。",
            "answer": "3",
        },
        {
            "idx": 2,
            "subject": "数论",
            "problem": "一个完全不同的问题",
            "answer": "1234",
        },
    ]
    references = [
        ReferenceProblem("prompt_fewshot", "数论", "计算 3^2024 除以 13 的余数。")
    ]

    report = audit_dataset(records, references, successes=2)

    assert report["total"] == 2
    assert report["overlap_counts"]["template"] == 1
    assert report["metadata_coverage"]["source"] == 0
    assert report["observed_accuracy"] == 1.0
    assert report["answer_length"]["at_most_3_chars"] == 1
    assert report["task_types"] == {"<missing>": 2}


def test_wilson_interval_rejects_invalid_counts_and_is_not_certainty():
    low, high = wilson_interval(36, 36)

    assert low == pytest.approx(0.9036, abs=0.001)
    assert high == 1.0
    with pytest.raises(ValueError):
        wilson_interval(2, 1)


def test_rule_of_three_is_only_reported_for_zero_observed_failures():
    records = [
        {"idx": 1, "problem": "p1", "answer": "1"},
        {"idx": 2, "problem": "p2", "answer": "2"},
    ]

    perfect = audit_dataset(records, [], successes=2)
    imperfect = audit_dataset(records, [], successes=1)

    assert perfect["rule_of_three_failure_upper_bound"] == 1.0
    assert imperfect["rule_of_three_failure_upper_bound"] is None


def test_benchmark_schema_requires_provenance_and_split():
    schema_path = Path(__file__).parents[1] / "evaluation" / "data" / "benchmark.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert {"source", "license", "split", "level"} <= set(schema["required"])
    assert schema["properties"]["split"]["enum"] == ["dev", "test"]
