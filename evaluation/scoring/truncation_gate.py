"""Evaluate truncation acceptance criteria from one or more score_run reports."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from ..io_utils import read_json_object, write_json

ONE_SIDED_95_Z = 1.6448536269514722
DEFAULT_TARGET_RATE = 0.05
DEFAULT_BASELINE_ACCURACY = 0.22
DEFAULT_ACCURACY_TOLERANCE = 0.02


def wilson_upper_one_sided(successes: int, total: int, z: float = ONE_SIDED_95_Z) -> float:
    """Return the one-sided Wilson upper confidence bound for a binomial rate."""
    if total <= 0:
        return 1.0
    successes = min(max(int(successes), 0), int(total))
    proportion = successes / total
    denominator = 1.0 + z * z / total
    center = proportion + z * z / (2.0 * total)
    spread = z * math.sqrt(
        proportion * (1.0 - proportion) / total + z * z / (4.0 * total * total)
    )
    return min(1.0, (center + spread) / denominator)


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", report)
    if not isinstance(summary, dict):
        raise ValueError("report summary must be an object")
    return summary


def combine_summaries(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine aggregate reports without reading or exposing individual problems."""
    totals: Counter[str] = Counter()
    stage_requests: Counter[str] = Counter()
    stage_truncations: Counter[str] = Counter()
    recovery: Counter[str] = Counter()
    for report in reports:
        summary = _summary(report)
        truncation = summary.get("truncation", {})
        if not isinstance(truncation, dict):
            truncation = {}
        for key in ("total", "correct", "no_answer", "invalid"):
            value = summary.get(key, 0)
            if isinstance(value, (int, float)):
                totals[key] += int(value)
        for key in (
            "request_count",
            "truncated_count",
            "problems_with_truncation",
            "truncated_problems_with_valid_answer",
            "truncated_fragments_in_final",
        ):
            value = truncation.get(key, 0)
            if isinstance(value, (int, float)):
                totals[key] += int(value)
        candidate = truncation.get("candidate_generation", {})
        if isinstance(candidate, dict):
            totals["candidate_requests"] += int(candidate.get("request_count", 0))
            totals["candidate_truncations"] += int(candidate.get("truncated_count", 0))
        by_stage = truncation.get("by_stage", {})
        if isinstance(by_stage, dict):
            for stage, values in by_stage.items():
                if not isinstance(values, dict):
                    continue
                stage_requests[str(stage)] += int(values.get("request_count", 0))
                stage_truncations[str(stage)] += int(values.get("truncated_count", 0))
        recovery_values = truncation.get("recovery", {})
        if isinstance(recovery_values, dict):
            for key in ("required", "handled", "succeeded", "failed"):
                recovery[key] += int(recovery_values.get(key, 0))

    requests = totals["request_count"]
    truncated = totals["truncated_count"]
    candidate_requests = totals["candidate_requests"]
    candidate_truncations = totals["candidate_truncations"]
    return {
        "total": totals["total"],
        "correct": totals["correct"],
        "invalid": max(totals["invalid"], totals["no_answer"]),
        "conservative_accuracy": (
            totals["correct"] / totals["total"] if totals["total"] else 0.0
        ),
        "truncation": {
            "request_count": requests,
            "truncated_count": truncated,
            "truncation_rate": truncated / requests if requests else 0.0,
            "candidate_generation": {
                "request_count": candidate_requests,
                "truncated_count": candidate_truncations,
                "truncation_rate": (
                    candidate_truncations / candidate_requests
                    if candidate_requests else 0.0
                ),
            },
            "by_stage": {
                stage: {
                    "request_count": stage_requests[stage],
                    "truncated_count": stage_truncations[stage],
                    "truncation_rate": (
                        stage_truncations[stage] / stage_requests[stage]
                        if stage_requests[stage] else 0.0
                    ),
                }
                for stage in sorted(set(stage_requests) | set(stage_truncations))
            },
            "problems_with_truncation": totals["problems_with_truncation"],
            "recovery": {
                **dict(recovery),
                "coverage": (
                    recovery["handled"] / recovery["required"]
                    if recovery["required"] else 1.0
                ),
            },
            "truncated_problems_with_valid_answer": totals[
                "truncated_problems_with_valid_answer"
            ],
            "valid_answer_rate_after_truncation": (
                totals["truncated_problems_with_valid_answer"]
                / totals["problems_with_truncation"]
                if totals["problems_with_truncation"] else 1.0
            ),
            "truncated_fragments_in_final": totals["truncated_fragments_in_final"],
        },
    }


def evaluate_truncation_gate(
    report: dict[str, Any],
    *,
    target_rate: float = DEFAULT_TARGET_RATE,
    baseline_accuracy: float = DEFAULT_BASELINE_ACCURACY,
    accuracy_tolerance: float = DEFAULT_ACCURACY_TOLERANCE,
) -> dict[str, Any]:
    """Apply the formal truncation, recovery, structure, and accuracy checks."""
    summary = _summary(report)
    truncation = summary.get("truncation", {})
    if not isinstance(truncation, dict):
        raise ValueError("summary.truncation must be an object")
    requests = int(truncation.get("request_count", 0))
    truncated = int(truncation.get("truncated_count", 0))
    rate = truncated / requests if requests else 1.0
    upper = wilson_upper_one_sided(truncated, requests)
    candidate = truncation.get("candidate_generation", {})
    candidate = candidate if isinstance(candidate, dict) else {}
    candidate_requests = int(candidate.get("request_count", 0))
    candidate_truncated = int(candidate.get("truncated_count", 0))
    candidate_rate = (
        candidate_truncated / candidate_requests if candidate_requests else 1.0
    )
    recovery = truncation.get("recovery", {})
    recovery = recovery if isinstance(recovery, dict) else {}
    recovery_required = int(recovery.get("required", truncated))
    recovery_handled = int(recovery.get("handled", 0))
    leaks = int(truncation.get("truncated_fragments_in_final", 0))
    invalid = int(summary.get("invalid", summary.get("no_answer", 0)))
    accuracy = float(summary.get("conservative_accuracy", 0.0))
    minimum_accuracy = max(0.0, baseline_accuracy - accuracy_tolerance)
    checks = {
        "request_sample_present": requests > 0,
        "point_rate_below_target": rate < target_rate,
        "one_sided_wilson_upper_below_target": upper < target_rate,
        "candidate_generation_rate_below_target": (
            candidate_requests > 0 and candidate_rate < target_rate
        ),
        "recovery_coverage_100_percent": recovery_handled == recovery_required,
        "truncated_fragments_in_final_zero": leaks == 0,
        "invalid_zero": invalid == 0,
        "accuracy_not_materially_below_baseline": accuracy >= minimum_accuracy,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": {
            "request_count": requests,
            "truncated_count": truncated,
            "truncation_rate": rate,
            "one_sided_wilson_95_upper": upper,
            "target_rate": target_rate,
            "candidate_request_count": candidate_requests,
            "candidate_truncated_count": candidate_truncated,
            "candidate_truncation_rate": candidate_rate,
            "recovery_required": recovery_required,
            "recovery_handled": recovery_handled,
            "truncated_fragments_in_final": leaks,
            "invalid": invalid,
            "accuracy": accuracy,
            "minimum_accuracy": minimum_accuracy,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--target-rate", type=float, default=DEFAULT_TARGET_RATE)
    parser.add_argument("--baseline-accuracy", type=float, default=DEFAULT_BASELINE_ACCURACY)
    parser.add_argument("--accuracy-tolerance", type=float, default=DEFAULT_ACCURACY_TOLERANCE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reports = [read_json_object(path) for path in args.reports]
    combined = combine_summaries(reports)
    result = evaluate_truncation_gate(
        combined,
        target_rate=args.target_rate,
        baseline_accuracy=args.baseline_accuracy,
        accuracy_tolerance=args.accuracy_tolerance,
    )
    serialized = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        write_json(args.output, result)
    print(serialized, end="")
    raise SystemExit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
