from collections import Counter

import hashlib

from evaluation.generate_internal_benchmark import (
    dataset_sha256,
    generate_records,
    serialize_records,
)


def test_internal_benchmark_is_balanced_deterministic_and_complete():
    first = generate_records()
    second = generate_records()
    subjects = Counter(str(item["subject"]) for item in first)
    families = Counter(str(item["template_family"]) for item in first)

    assert first == second
    assert len(first) == 396
    assert len(subjects) == 18
    assert set(subjects.values()) == {22}
    assert len(families) == 108
    assert min(families.values()) == 3
    assert max(families.values()) == 4
    assert len({str(item["idx"]) for item in first}) == 396
    assert len({str(item["problem"]) for item in first}) == 396
    assert len(dataset_sha256(first)) == 64
    assert dataset_sha256(first) == hashlib.sha256(
        serialize_records(first).encode("utf-8")
    ).hexdigest()


def test_internal_benchmark_records_have_provenance_and_answers():
    required = {
        "idx",
        "problem",
        "answer",
        "subject",
        "task_type",
        "level",
        "source",
        "license",
        "split",
        "template_family",
    }

    for item in generate_records():
        assert required <= set(item)
        assert all(str(item[field]).strip() for field in required)
        assert item["split"] == "test"
