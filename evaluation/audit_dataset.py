"""Audit a JSONL benchmark for size, metadata, duplicates, and prompt overlap."""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REQUIRED_PROVENANCE_FIELDS = ("source", "license", "split", "level")


@dataclass(frozen=True)
class ReferenceProblem:
    source: str
    subject: str
    problem: str


def normalize_problem(text: str) -> str:
    """Normalize presentation differences without changing numbers or operators."""
    value = unicodedata.normalize("NFKC", str(text)).casefold()
    value = value.replace(r"\left", "").replace(r"\right", "")
    value = value.replace("→", "->").replace("−", "-").replace("×", "*")
    return re.sub(r"[\s，。,.！？?：:；;、'\"`$\\{}\[\]()]", "", value)


def normalize_template(text: str) -> str:
    """Normalize constants to expose parameter-swapped copies of a question."""
    value = normalize_problem(text)
    return re.sub(r"\d+(?:\.\d+)?", "#", value)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number} is not a JSON object")
            problem = record.get("problem")
            if not isinstance(problem, str) or not problem.strip():
                raise ValueError(f"line {line_number} has no non-empty problem")
            records.append(record)
    return records


def default_references() -> list[ReferenceProblem]:
    from verify_math import parse_fewshot_examples

    references = [
        ReferenceProblem("prompt_fewshot", item["domain"], item["problem"])
        for item in parse_fewshot_examples()
    ]
    sample_path = ROOT / "sample_data" / "dev.jsonl"
    if sample_path.is_file():
        references.extend(
            ReferenceProblem(
                "sample_data",
                str(item.get("subject", "")),
                str(item["problem"]),
            )
            for item in load_jsonl(sample_path)
        )
    return references


def references_from_dataset(path: Path) -> list[ReferenceProblem]:
    """Load another JSONL split as overlap-only references."""
    return [
        ReferenceProblem(
            f"reference_dataset:{path.name}",
            str(item.get("subject", "")),
            str(item["problem"]),
        )
        for item in load_jsonl(path)
    ]


def _match_problem(
    problem: str,
    references: Iterable[ReferenceProblem],
    near_threshold: float,
) -> dict[str, Any] | None:
    normalized = normalize_problem(problem)
    template = normalize_template(problem)
    best: tuple[int, float, ReferenceProblem, str] | None = None
    for reference in references:
        ref_normalized = normalize_problem(reference.problem)
        ref_template = normalize_template(reference.problem)
        if normalized == ref_normalized:
            candidate = (3, 1.0, reference, "exact")
        elif len(template) >= 8 and template == ref_template:
            candidate = (2, 1.0, reference, "template")
        else:
            ratio = SequenceMatcher(None, template, ref_template).ratio()
            if ratio < near_threshold:
                continue
            candidate = (1, ratio, reference, "near")
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    if best is None:
        return None
    _, similarity, reference, match_type = best
    return {
        "match_type": match_type,
        "similarity": round(similarity, 4),
        "reference_source": reference.source,
        "reference_subject": reference.subject,
        "reference_problem": reference.problem,
    }


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise ValueError("successes and total must satisfy 0 <= successes <= total")
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def audit_dataset(
    records: list[dict[str, Any]],
    references: Iterable[ReferenceProblem],
    *,
    successes: int | None = None,
    near_threshold: float = 0.82,
) -> dict[str, Any]:
    references = list(references)
    subjects = Counter(str(record.get("subject", "<missing>")) for record in records)
    lengths = [len(str(record["problem"])) for record in records]
    answer_lengths = [
        len(str(record.get("answer", "")).strip())
        for record in records
        if str(record.get("answer", "")).strip()
    ]
    task_types = Counter(
        str(record.get("task_type", "<missing>")) for record in records
    )
    metadata_coverage = {
        field: sum(bool(record.get(field)) for record in records)
        for field in REQUIRED_PROVENANCE_FIELDS
    }

    normalized_counts = Counter(normalize_problem(record["problem"]) for record in records)
    duplicate_items = sum(count - 1 for count in normalized_counts.values() if count > 1)
    overlaps = []
    for record in records:
        match = _match_problem(str(record["problem"]), references, near_threshold)
        if match:
            overlaps.append(
                {
                    "idx": record.get("idx"),
                    "subject": record.get("subject"),
                    "problem": record["problem"],
                    **match,
                }
            )
    overlap_counts = Counter(item["match_type"] for item in overlaps)

    result: dict[str, Any] = {
        "total": len(records),
        "subjects": dict(sorted(subjects.items())),
        "subject_count": len(subjects),
        "min_items_per_subject": min(subjects.values(), default=0),
        "max_items_per_subject": max(subjects.values(), default=0),
        "problem_length": {
            "min": min(lengths, default=0),
            "median": statistics.median(lengths) if lengths else 0,
            "max": max(lengths, default=0),
            "under_40_chars": sum(length < 40 for length in lengths),
        },
        "answer_length": {
            "present": len(answer_lengths),
            "min": min(answer_lengths, default=0),
            "median": statistics.median(answer_lengths) if answer_lengths else 0,
            "max": max(answer_lengths, default=0),
            "at_most_3_chars": sum(length <= 3 for length in answer_lengths),
        },
        "task_types": dict(sorted(task_types.items())),
        "metadata_coverage": metadata_coverage,
        "exact_duplicates_within_dataset": duplicate_items,
        "overlap_counts": {
            "exact": overlap_counts["exact"],
            "template": overlap_counts["template"],
            "near": overlap_counts["near"],
            "total": len(overlaps),
        },
        "overlaps": overlaps,
    }
    if successes is not None:
        low, high = wilson_interval(successes, len(records))
        result["observed_accuracy"] = successes / len(records) if records else 0.0
        result["wilson_95_interval"] = [low, high]
        result["rule_of_three_failure_upper_bound"] = (
            min(1.0, 3 / len(records))
            if records and successes == len(records)
            else None
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path, help="JSONL benchmark to audit")
    parser.add_argument("--successes", type=int, help="Observed correct count")
    parser.add_argument("--near-threshold", type=float, default=0.82)
    parser.add_argument(
        "--reference-dataset",
        type=Path,
        action="append",
        default=[],
        help="Additional JSONL split to check for cross-dataset leakage.",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    parser.add_argument("--quiet", action="store_true", help="Write JSON without printing it")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    records = load_jsonl(args.dataset)
    references = default_references()
    for reference_path in args.reference_dataset:
        references.extend(references_from_dataset(reference_path))
    report = audit_dataset(
        records,
        references,
        successes=args.successes,
        near_threshold=args.near_threshold,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if not args.quiet:
        print(serialized)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
