"""Compare baseline and candidate score reports with paired item-level statistics."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


_KNOWN_STATUSES = {"correct", "wrong", "unknown", "no_answer", "error", "missing"}


def load_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} is not a JSON object")
    return loaded


def exact_mcnemar(candidate_only: int, baseline_only: int) -> dict[str, float | int]:
    if candidate_only < 0 or baseline_only < 0:
        raise ValueError("discordant counts must be non-negative")
    discordant = candidate_only + baseline_only
    if discordant == 0:
        return {
            "discordant": 0,
            "candidate_only": candidate_only,
            "baseline_only": baseline_only,
            "one_sided_improvement_p": 1.0,
            "two_sided_p": 1.0,
        }
    denominator = 2**discordant
    one_sided = sum(
        math.comb(discordant, value)
        for value in range(candidate_only, discordant + 1)
    ) / denominator
    lower_tail = sum(
        math.comb(discordant, value)
        for value in range(0, min(candidate_only, baseline_only) + 1)
    ) / denominator
    return {
        "discordant": discordant,
        "candidate_only": candidate_only,
        "baseline_only": baseline_only,
        "one_sided_improvement_p": min(1.0, one_sided),
        "two_sided_p": min(1.0, 2 * lower_tail),
    }


def _result_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = report.get("results")
    if not isinstance(rows, list):
        raise ValueError("score report has no results list")
    mapped: dict[str, dict[str, Any]] = {}
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"result {position} is not an object")
        idx = str(row.get("idx", ""))
        status = str(row.get("status", ""))
        if not idx or idx in mapped:
            raise ValueError(f"missing or duplicate result idx: {idx!r}")
        if status not in _KNOWN_STATUSES:
            raise ValueError(f"invalid result status for {idx!r}: {status!r}")
        mapped[idx] = row
    return mapped


def _quantile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty list")
    position = (len(sorted_values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def paired_bootstrap_interval(
    item_deltas: list[float],
    *,
    samples: int = 10_000,
    seed: int = 20260830,
) -> list[float]:
    if not item_deltas:
        raise ValueError("item_deltas must not be empty")
    if samples <= 0:
        raise ValueError("samples must be positive")
    # A deterministic PRNG is required so the statistical bootstrap is reproducible.
    rng = random.Random(seed)  # nosec B311
    size = len(item_deltas)
    estimates = []
    for _ in range(samples):
        estimates.append(sum(item_deltas[rng.randrange(size)] for _ in range(size)) / size)
    estimates.sort()
    return [_quantile(estimates, 0.025), _quantile(estimates, 0.975)]


def _summary_count(report: dict[str, Any], field: str) -> int:
    summary = report.get("summary")
    if not isinstance(summary, dict):
        return 0
    value = summary.get(field, 0)
    return int(value) if isinstance(value, (int, float)) else 0


def _usage_count(report: dict[str, Any], field: str) -> int:
    summary = report.get("summary")
    usage = summary.get("usage") if isinstance(summary, dict) else None
    value = usage.get(field, 0) if isinstance(usage, dict) else 0
    return int(value) if isinstance(value, (int, float)) else 0


def _manifest_checks(
    baseline_manifest: dict[str, Any] | None,
    candidate_manifest: dict[str, Any] | None,
    repetitions: int,
) -> list[str]:
    errors: list[str] = []
    if baseline_manifest is None or candidate_manifest is None:
        return ["both frozen experiment manifests are required"]
    for label, manifest in (("baseline", baseline_manifest), ("candidate", candidate_manifest)):
        if manifest.get("status") != "frozen":
            errors.append(f"{label} manifest status is not frozen")
        runner = manifest.get("runner")
        if not isinstance(runner, dict) or runner.get("repetitions") != repetitions:
            errors.append(f"{label} manifest repetition count does not match reports")
    baseline_dataset = baseline_manifest.get("dataset")
    candidate_dataset = candidate_manifest.get("dataset")
    if not isinstance(baseline_dataset, dict) or not isinstance(candidate_dataset, dict):
        errors.append("manifest dataset metadata is missing")
    elif baseline_dataset.get("sha256") != candidate_dataset.get("sha256"):
        errors.append("baseline and candidate dataset hashes differ")
    baseline_model = baseline_manifest.get("model")
    candidate_model = candidate_manifest.get("model")
    if not isinstance(baseline_model, dict) or not isinstance(candidate_model, dict):
        errors.append("manifest model metadata is missing")
    elif baseline_model.get("configured_name") != candidate_model.get("configured_name"):
        errors.append("baseline and candidate models differ")
    baseline_runner = baseline_manifest.get("runner")
    candidate_runner = candidate_manifest.get("runner")
    if isinstance(baseline_runner, dict) and isinstance(candidate_runner, dict):
        if baseline_runner.get("local_max_concurrency") != candidate_runner.get(
            "local_max_concurrency"
        ):
            errors.append("baseline and candidate concurrency differ")
    return errors


def _report_provenance_checks(
    baseline_reports: list[dict[str, Any]],
    candidate_reports: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    hashes: set[str] = set()
    models: set[str] = set()
    for label, reports in (("baseline", baseline_reports), ("candidate", candidate_reports)):
        for number, report in enumerate(reports, start=1):
            provenance = report.get("provenance")
            if not isinstance(provenance, dict):
                errors.append(f"{label} report {number} has no provenance")
                continue
            digest = str(provenance.get("dataset_sha256", ""))
            model = str(provenance.get("model", ""))
            if not digest:
                errors.append(f"{label} report {number} has no dataset hash")
            else:
                hashes.add(digest)
            if not model:
                errors.append(f"{label} report {number} has no returned model name")
            else:
                models.add(model)
    if len(hashes) > 1:
        errors.append("score reports use different dataset hashes")
    if len(models) > 1:
        errors.append("score reports use different returned model names")
    return errors


def _group_deltas(
    paired_rows: list[tuple[dict[str, Any], dict[str, Any]]],
    field: str,
) -> dict[str, Any]:
    groups: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for baseline, candidate in paired_rows:
        name = str(baseline.get(field, "<missing>"))
        groups[name].append(
            (int(baseline["status"] == "correct"), int(candidate["status"] == "correct"))
        )
    result = {}
    for name, values in sorted(groups.items()):
        total = len(values)
        baseline_correct = sum(value[0] for value in values)
        candidate_correct = sum(value[1] for value in values)
        result[name] = {
            "observations": total,
            "baseline_accuracy": baseline_correct / total,
            "candidate_accuracy": candidate_correct / total,
            "accuracy_delta": (candidate_correct - baseline_correct) / total,
        }
    return result


def compare_reports(
    baseline_reports: list[dict[str, Any]],
    candidate_reports: list[dict[str, Any]],
    *,
    baseline_manifest: dict[str, Any] | None = None,
    candidate_manifest: dict[str, Any] | None = None,
    candidate_reliability_gate: dict[str, Any] | None = None,
    bootstrap_samples: int = 10_000,
    seed: int = 20260830,
) -> dict[str, Any]:
    if not baseline_reports or len(baseline_reports) != len(candidate_reports):
        raise ValueError("baseline and candidate must have the same non-zero number of reports")
    repetitions = len(baseline_reports)
    baseline_maps = [_result_map(report) for report in baseline_reports]
    candidate_maps = [_result_map(report) for report in candidate_reports]
    universe = set(baseline_maps[0])
    for number, (baseline, candidate) in enumerate(
        zip(baseline_maps, candidate_maps), start=1
    ):
        if set(baseline) != universe or set(candidate) != universe:
            raise ValueError(f"report pair {number} does not use the same idx universe")

    per_run = []
    paired_rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
    baseline_by_item: dict[str, list[int]] = defaultdict(list)
    candidate_by_item: dict[str, list[int]] = defaultdict(list)
    for run_number, (baseline, candidate) in enumerate(
        zip(baseline_maps, candidate_maps), start=1
    ):
        counts = Counter()
        transitions = Counter()
        for idx in sorted(universe):
            baseline_row = baseline[idx]
            candidate_row = candidate[idx]
            paired_rows.append((baseline_row, candidate_row))
            baseline_ok = int(baseline_row["status"] == "correct")
            candidate_ok = int(candidate_row["status"] == "correct")
            baseline_by_item[idx].append(baseline_ok)
            candidate_by_item[idx].append(candidate_ok)
            if baseline_ok and candidate_ok:
                counts["both_correct"] += 1
            elif baseline_ok:
                counts["baseline_only"] += 1
            elif candidate_ok:
                counts["candidate_only"] += 1
            else:
                counts["both_incorrect"] += 1
            transitions[
                f"{baseline_row['status']}->{candidate_row['status']}"
            ] += 1
        total = len(universe)
        baseline_correct = counts["both_correct"] + counts["baseline_only"]
        candidate_correct = counts["both_correct"] + counts["candidate_only"]
        per_run.append(
            {
                "run": run_number,
                "total": total,
                **dict(counts),
                "baseline_accuracy": baseline_correct / total,
                "candidate_accuracy": candidate_correct / total,
                "accuracy_delta": (candidate_correct - baseline_correct) / total,
                "mcnemar_exact": exact_mcnemar(
                    counts["candidate_only"], counts["baseline_only"]
                ),
                "status_transitions": dict(sorted(transitions.items())),
            }
        )

    item_deltas = [
        (sum(candidate_by_item[idx]) - sum(baseline_by_item[idx])) / repetitions
        for idx in sorted(universe)
    ]
    interval = paired_bootstrap_interval(
        item_deltas,
        samples=bootstrap_samples,
        seed=seed,
    )
    majority_threshold = repetitions // 2 + 1
    majority_counts = Counter()
    improved_items = []
    regressed_items = []
    for idx in sorted(universe):
        baseline_total = sum(baseline_by_item[idx])
        candidate_total = sum(candidate_by_item[idx])
        baseline_majority = baseline_total >= majority_threshold
        candidate_majority = candidate_total >= majority_threshold
        if baseline_majority and candidate_majority:
            majority_counts["both_correct"] += 1
        elif baseline_majority:
            majority_counts["baseline_only"] += 1
        elif candidate_majority:
            majority_counts["candidate_only"] += 1
        else:
            majority_counts["both_incorrect"] += 1
        if candidate_total > baseline_total:
            improved_items.append(idx)
        elif baseline_total > candidate_total:
            regressed_items.append(idx)

    total_observations = len(universe) * repetitions
    baseline_correct_observations = sum(map(sum, baseline_by_item.values()))
    candidate_correct_observations = sum(map(sum, candidate_by_item.values()))
    mean_delta = (candidate_correct_observations - baseline_correct_observations) / total_observations
    majority_mcnemar = exact_mcnemar(
        majority_counts["candidate_only"], majority_counts["baseline_only"]
    )

    comparability_errors = _manifest_checks(
        baseline_manifest, candidate_manifest, repetitions
    )
    comparability_errors.extend(
        _report_provenance_checks(baseline_reports, candidate_reports)
    )
    if isinstance(baseline_manifest, dict):
        manifest_dataset = baseline_manifest.get("dataset")
        expected_digest = (
            str(manifest_dataset.get("sha256", ""))
            if isinstance(manifest_dataset, dict)
            else ""
        )
        if expected_digest:
            for label, reports in (
                ("baseline", baseline_reports),
                ("candidate", candidate_reports),
            ):
                for number, report in enumerate(reports, start=1):
                    provenance = report.get("provenance")
                    observed = (
                        str(provenance.get("dataset_sha256", ""))
                        if isinstance(provenance, dict)
                        else ""
                    )
                    if observed and observed != expected_digest:
                        comparability_errors.append(
                            f"{label} report {number} dataset hash differs from manifest"
                        )
    reliability_passed = bool(
        isinstance(candidate_reliability_gate, dict)
        and candidate_reliability_gate.get("passed") is True
    )
    candidate_invalid = sum(_summary_count(report, "invalid") for report in candidate_reports)
    candidate_errors = sum(
        _summary_count(report, "error") + _summary_count(report, "missing")
        for report in candidate_reports
    )
    truncated_fragments = sum(
        _usage_count(report, "truncated_fragments_in_final")
        for report in candidate_reports
    )
    statistical_support = (
        mean_delta > 0
        and interval[0] > 0
        and majority_mcnemar["one_sided_improvement_p"] < 0.05
    )
    repeat_consistency = repetitions >= 3 and sum(
        run["accuracy_delta"] > 0 for run in per_run
    ) >= math.ceil(2 * repetitions / 3)
    claim_supported = (
        not comparability_errors
        and statistical_support
        and repeat_consistency
        and reliability_passed
        and candidate_invalid == 0
        and candidate_errors == 0
        and truncated_fragments == 0
    )

    return {
        "summary": {
            "items": len(universe),
            "repetitions": repetitions,
            "observations_per_version": total_observations,
            "baseline_accuracy": baseline_correct_observations / total_observations,
            "candidate_accuracy": candidate_correct_observations / total_observations,
            "accuracy_delta": mean_delta,
            "paired_bootstrap_95": interval,
            "improved_item_count": len(improved_items),
            "regressed_item_count": len(regressed_items),
            "improved_items": improved_items,
            "regressed_items": regressed_items,
        },
        "majority_over_repetitions": {
            **dict(majority_counts),
            "threshold": majority_threshold,
            "mcnemar_exact": majority_mcnemar,
        },
        "per_run": per_run,
        "by_subject": _group_deltas(paired_rows, "subject"),
        "by_level": _group_deltas(paired_rows, "level"),
        "by_task_type": _group_deltas(paired_rows, "task_type"),
        "comparability": {
            "verified": not comparability_errors,
            "errors": comparability_errors,
        },
        "reliability": {
            "candidate_gate_passed": reliability_passed,
            "candidate_invalid": candidate_invalid,
            "candidate_errors_or_missing": candidate_errors,
            "truncated_fragments_in_final": truncated_fragments,
        },
        "decision": {
            "directional_improvement": mean_delta > 0,
            "statistically_supported": statistical_support,
            "repeat_consistent": repeat_consistency,
            "ability_improvement_demonstrated": claim_supported,
            "claim": (
                "ability_improvement_demonstrated"
                if claim_supported
                else "insufficient_evidence"
            ),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-report", type=Path, action="append", required=True)
    parser.add_argument("--candidate-report", type=Path, action="append", required=True)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-reliability-gate", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=20260830)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = compare_reports(
        [load_json_object(path) for path in args.baseline_report],
        [load_json_object(path) for path in args.candidate_report],
        baseline_manifest=load_json_object(args.baseline_manifest),
        candidate_manifest=load_json_object(args.candidate_manifest),
        candidate_reliability_gate=load_json_object(args.candidate_reliability_gate),
        bootstrap_samples=args.bootstrap_samples,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({**report["summary"], **report["decision"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
