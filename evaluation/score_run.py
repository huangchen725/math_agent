"""Score a directory produced by main.py without making API calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.audit_dataset import load_jsonl, wilson_interval
from evaluation.judge import judge_answer


_FINAL_ANSWER = re.compile(r"^\s*最终答案\s*[:：]\s*(.*?)\s*$", re.MULTILINE)
STATUSES = ("correct", "wrong", "unknown", "no_answer", "error", "missing")
ADJUDICATION_STATUSES = {"correct", "wrong", "unknown", "no_answer"}


def extract_final_answer(final_response: str) -> str:
    matches = _FINAL_ANSWER.findall(final_response or "")
    return matches[-1].strip() if matches else ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_adjudications(path: Path) -> dict[str, dict[str, Any]]:
    adjudications: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid adjudication JSON on line {line_number}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"adjudication line {line_number} is not an object")
            idx = str(record.get("idx", ""))
            status = str(record.get("status", ""))
            reviewer_id = str(record.get("reviewer_id", "")).strip()
            if not idx or idx in adjudications:
                raise ValueError(f"missing or duplicate adjudication idx on line {line_number}")
            if status not in ADJUDICATION_STATUSES:
                raise ValueError(f"invalid adjudication status on line {line_number}: {status!r}")
            if record.get("blind") is not True or not reviewer_id:
                raise ValueError(
                    f"adjudication line {line_number} must have blind=true and reviewer_id"
                )
            score = record.get("score")
            if score is not None and (
                not isinstance(score, (int, float)) or not 0 <= float(score) <= 10
            ):
                raise ValueError(f"invalid adjudication score on line {line_number}")
            adjudications[idx] = dict(record)
    return adjudications


_SCALAR_USAGE_FIELDS = (
    "model_requests",
    "normal_model_requests",
    "recovery_requests",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "tool_calls",
    "truncated_responses",
    "truncated_fragments_in_final",
    "elapsed_ms",
)


def _budget_snapshot(trace: object) -> dict[str, Any]:
    if not isinstance(trace, list):
        return {}
    for event in reversed(trace):
        if not isinstance(event, dict) or event.get("step") != "budget_summary":
            continue
        content = event.get("content")
        if not isinstance(content, dict):
            return {}
        snapshot: dict[str, Any] = {
            key: int(content.get(key, 0))
            for key in _SCALAR_USAGE_FIELDS
            if isinstance(content.get(key, 0), (int, float))
        }
        for key in ("requests_by_stage", "truncated_by_stage", "truncation_recovery"):
            value = content.get(key)
            if isinstance(value, dict):
                snapshot[key] = dict(value)
        return snapshot
    return {}


def _group_summary(items: list[dict[str, Any]], field: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item.get(field, "<missing>"))].append(item)
    summary = {}
    for name, group in sorted(groups.items()):
        counts = Counter(str(item["status"]) for item in group)
        total = len(group)
        summary[name] = {
            "total": total,
            **{status: counts[status] for status in STATUSES},
            "conservative_accuracy": counts["correct"] / total if total else 0.0,
            "reviewable_accuracy_upper_bound": (
                (counts["correct"] + counts["unknown"]) / total if total else 0.0
            ),
        }
    return summary


def score_run(
    dataset: list[dict[str, Any]],
    output_dir: Path,
    adjudications: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    adjudications = adjudications or {}
    dataset_indexes = {str(item.get("idx", position)) for position, item in enumerate(dataset)}
    extra_adjudications = sorted(set(adjudications) - dataset_indexes)
    if extra_adjudications:
        raise ValueError(f"adjudications contain unknown idx values: {extra_adjudications[:10]}")
    results = []
    totals: Counter[str] = Counter()
    usage: Counter[str] = Counter()
    requests_by_stage: Counter[str] = Counter()
    truncated_by_stage: Counter[str] = Counter()
    recovery: Counter[str] = Counter()
    problems_with_truncation = 0
    truncated_problems_with_valid_answer = 0
    adjudicated_count = 0
    for position, item in enumerate(dataset):
        idx = str(item.get("idx", position))
        output_path = output_dir / f"{idx}.json"
        record: dict[str, Any] = {}
        actual = ""
        method = ""
        detail = ""
        auto_status = ""
        reviewer_id = ""
        human_score: float | None = None
        if not output_path.is_file():
            status = "missing"
        else:
            try:
                loaded = json.loads(output_path.read_text(encoding="utf-8-sig"))
                if not isinstance(loaded, dict):
                    raise ValueError("output is not an object")
                record = loaded
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                status = "error"
                detail = f"invalid output: {exc}"
            else:
                if record.get("status") != "success":
                    status = "error"
                    error = record.get("error")
                    detail = str(error)[:500]
                else:
                    actual = extract_final_answer(str(record.get("final_response", "")))
                    if str(item.get("grading_mode", "")) == "manual_blind":
                        status = "unknown" if actual else "no_answer"
                        method = "manual_review_required"
                        detail = "dataset requires blinded mathematical review"
                    else:
                        judged = judge_answer(str(item.get("answer", "")), actual)
                        status = judged.status
                        method = judged.method
                        detail = judged.detail
                budget_snapshot = _budget_snapshot(record.get("trace"))
                usage.update({
                    key: int(budget_snapshot.get(key, 0))
                    for key in _SCALAR_USAGE_FIELDS
                })
                requests_by_stage.update({
                    str(key): int(value)
                    for key, value in budget_snapshot.get("requests_by_stage", {}).items()
                    if isinstance(value, (int, float))
                })
                truncated_by_stage.update({
                    str(key): int(value)
                    for key, value in budget_snapshot.get("truncated_by_stage", {}).items()
                    if isinstance(value, (int, float))
                })
                recovery.update({
                    str(key): int(value)
                    for key, value in budget_snapshot.get("truncation_recovery", {}).items()
                    if isinstance(value, (int, float))
                })
                if int(budget_snapshot.get("truncated_responses", 0)) > 0:
                    problems_with_truncation += 1
                    if actual:
                        truncated_problems_with_valid_answer += 1
        auto_status = status
        adjudication = adjudications.get(idx)
        if adjudication is not None and status not in {"error", "missing"}:
            status = str(adjudication["status"])
            reviewer_id = str(adjudication["reviewer_id"])
            score = adjudication.get("score")
            human_score = float(score) if isinstance(score, (int, float)) else None
            method = "blind_human_review"
            detail = "blind adjudication override"
            adjudicated_count += 1
        totals[status] += 1
        results.append(
            {
                "idx": item.get("idx", position),
                "subject": item.get("subject", "<missing>"),
                "level": item.get("level", "<missing>"),
                "task_type": item.get("task_type", "<missing>"),
                "template_family": item.get("template_family", "<missing>"),
                "expected": item.get("answer", ""),
                "actual": actual,
                "auto_status": auto_status,
                "status": status,
                "method": method,
                "detail": detail,
                "reviewer_id": reviewer_id,
                "human_score": human_score,
            }
        )

    total = len(dataset)
    conservative_low, conservative_high = wilson_interval(totals["correct"], total)
    upper_successes = totals["correct"] + totals["unknown"]
    review_low, review_high = wilson_interval(upper_successes, total)
    stage_stats = {
        stage: {
            "request_count": requests_by_stage[stage],
            "truncated_count": truncated_by_stage[stage],
            "truncation_rate": (
                truncated_by_stage[stage] / requests_by_stage[stage]
                if requests_by_stage[stage] else 0.0
            ),
        }
        for stage in sorted(set(requests_by_stage) | set(truncated_by_stage))
    }
    candidate_stages = {"policy_tool", "policy_plain", "tool_final", "reflection"}
    candidate_requests = sum(requests_by_stage[stage] for stage in candidate_stages)
    candidate_truncations = sum(truncated_by_stage[stage] for stage in candidate_stages)
    total_requests = usage["model_requests"]
    total_truncations = usage["truncated_responses"]
    truncation_summary = {
        "request_count": total_requests,
        "truncated_count": total_truncations,
        "truncation_rate": total_truncations / total_requests if total_requests else 0.0,
        "candidate_generation": {
            "request_count": candidate_requests,
            "truncated_count": candidate_truncations,
            "truncation_rate": (
                candidate_truncations / candidate_requests if candidate_requests else 0.0
            ),
        },
        "by_stage": stage_stats,
        "problems_with_truncation": problems_with_truncation,
        "recovery": {
            "required": recovery["required"],
            "handled": recovery["handled"],
            "succeeded": recovery["succeeded"],
            "failed": recovery["failed"],
            "coverage": (
                recovery["handled"] / recovery["required"]
                if recovery["required"] else 1.0
            ),
        },
        "truncated_problems_with_valid_answer": truncated_problems_with_valid_answer,
        "valid_answer_rate_after_truncation": (
            truncated_problems_with_valid_answer / problems_with_truncation
            if problems_with_truncation else 1.0
        ),
        "truncated_fragments_in_final": usage["truncated_fragments_in_final"],
    }
    return {
        "summary": {
            "total": total,
            **{status: totals[status] for status in STATUSES},
            "conservative_accuracy": totals["correct"] / total if total else 0.0,
            "reviewable_accuracy_upper_bound": upper_successes / total if total else 0.0,
            "conservative_wilson_95": [conservative_low, conservative_high],
            "reviewable_wilson_95_upper_scenario": [review_low, review_high],
            "usage": dict(usage),
            "truncation": truncation_summary,
            "invalid": totals["no_answer"],
            "adjudicated": adjudicated_count,
        },
        "by_subject": _group_summary(results, "subject"),
        "by_level": _group_summary(results, "level"),
        "by_task_type": _group_summary(results, "task_type"),
        "by_template_family": _group_summary(results, "template_family"),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path)
    parser.add_argument(
        "--adjudications",
        type=Path,
        help="Optional blind-review JSONL produced by evaluation/blind_review.py.",
    )
    return parser.parse_args()


def build_provenance(dataset_path: Path, output_dir: Path) -> dict[str, Any]:
    digest = file_sha256(dataset_path)
    provenance: dict[str, Any] = {"dataset_sha256": digest}
    summary_path = output_dir / "_run" / "run_summary.json"
    if not summary_path.is_file():
        provenance["run_summary_present"] = False
        return provenance
    loaded = json.loads(summary_path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("run summary is not a JSON object")
    recorded_digest = str(loaded.get("input_sha256", ""))
    if recorded_digest and recorded_digest != digest:
        raise ValueError("run summary input_sha256 does not match the scored dataset")
    provenance.update(
        {
            "run_summary_present": True,
            "input_sha256": recorded_digest,
            "model": loaded.get("model"),
            "local_max_concurrency": loaded.get("local_max_concurrency"),
            "started_at": loaded.get("started_at"),
            "duration_ms": loaded.get("duration_ms"),
            "run_status": loaded.get("status"),
        }
    )
    return provenance


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    adjudications = load_adjudications(args.adjudications) if args.adjudications else None
    scored = score_run(load_jsonl(args.dataset), args.output_dir, adjudications)
    scored["provenance"] = build_provenance(args.dataset, args.output_dir)
    serialized = json.dumps(scored, ensure_ascii=False, indent=2)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(serialized + "\n", encoding="utf-8")
    if args.review:
        args.review.parent.mkdir(parents=True, exist_ok=True)
        with args.review.open("w", encoding="utf-8") as file:
            by_idx = {str(item.get("idx")): item for item in load_jsonl(args.dataset)}
            for result in scored["results"]:
                if result["status"] != "unknown":
                    continue
                source = by_idx[str(result["idx"])]
                file.write(json.dumps({**source, **result}, ensure_ascii=False) + "\n")
    print(json.dumps(scored["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
