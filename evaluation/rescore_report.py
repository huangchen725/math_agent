"""Re-score an existing benchmark report without making model API calls."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.audit_dataset import load_jsonl
from evaluation.judge import judge_answer


def rescore_report(
    dataset_records: list[dict[str, Any]], report: dict[str, Any]
) -> dict[str, Any]:
    expected_by_idx: dict[str, dict[str, Any]] = {}
    for position, record in enumerate(dataset_records):
        key = str(record.get("idx", position))
        if key in expected_by_idx:
            raise ValueError(f"duplicate dataset idx: {key}")
        expected_by_idx[key] = record

    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        raise ValueError("report must contain a results list")

    results = []
    counts: Counter[str] = Counter()
    per_subject: dict[str, Counter[str]] = defaultdict(Counter)
    seen = set()
    for position, raw_result in enumerate(raw_results):
        if not isinstance(raw_result, dict):
            raise ValueError(f"report result {position} is not an object")
        key = str(raw_result.get("idx", position))
        if key in seen:
            raise ValueError(f"duplicate report idx: {key}")
        seen.add(key)
        expected_record = expected_by_idx.get(key)
        if expected_record is None:
            raise ValueError(f"report idx not found in dataset: {key}")

        expected = str(expected_record.get("answer", ""))
        actual = str(raw_result.get("extracted", ""))
        judged = judge_answer(expected, actual)
        subject = str(expected_record.get("subject", "<missing>"))
        counts[judged.status] += 1
        per_subject[subject][judged.status] += 1
        results.append(
            {
                "idx": expected_record.get("idx", position),
                "subject": subject,
                "expected": expected,
                "actual": actual,
                "status": judged.status,
                "method": judged.method,
                "detail": judged.detail,
                "legacy_verdict": raw_result.get("verdict"),
            }
        )

    missing = sorted(set(expected_by_idx) - seen)
    return {
        "summary": {
            "dataset_total": len(dataset_records),
            "report_total": len(raw_results),
            "missing_results": len(missing),
            **{status: counts[status] for status in ("correct", "wrong", "unknown", "no_answer")},
        },
        "per_subject": {
            subject: dict(sorted(subject_counts.items()))
            for subject, subject_counts in sorted(per_subject.items())
        },
        "missing_idx": missing,
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="JSONL benchmark with expected answers")
    parser.add_argument("report", type=Path, help="Existing JSON report with extracted answers")
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    parser.add_argument("--quiet", action="store_true", help="Do not print JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    rescored = rescore_report(load_jsonl(args.dataset), report)
    serialized = json.dumps(rescored, ensure_ascii=False, indent=2)
    if not args.quiet:
        print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
