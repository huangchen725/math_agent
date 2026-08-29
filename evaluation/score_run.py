"""Score a directory produced by main.py without making API calls."""

from __future__ import annotations

import argparse
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


def extract_final_answer(final_response: str) -> str:
    matches = _FINAL_ANSWER.findall(final_response or "")
    return matches[-1].strip() if matches else ""


def _budget_snapshot(trace: object) -> dict[str, int]:
    if not isinstance(trace, list):
        return {}
    for event in reversed(trace):
        if not isinstance(event, dict) or event.get("step") != "budget_summary":
            continue
        content = event.get("content")
        if not isinstance(content, dict):
            return {}
        return {
            key: int(content.get(key, 0))
            for key in (
                "model_requests",
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "tool_calls",
                "truncated_responses",
                "elapsed_ms",
            )
            if isinstance(content.get(key, 0), (int, float))
        }
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


def score_run(dataset: list[dict[str, Any]], output_dir: Path) -> dict[str, Any]:
    results = []
    totals: Counter[str] = Counter()
    usage: Counter[str] = Counter()
    for position, item in enumerate(dataset):
        idx = str(item.get("idx", position))
        output_path = output_dir / f"{idx}.json"
        record: dict[str, Any] = {}
        actual = ""
        method = ""
        detail = ""
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
                    judged = judge_answer(str(item.get("answer", "")), actual)
                    status = judged.status
                    method = judged.method
                    detail = judged.detail
                usage.update(_budget_snapshot(record.get("trace")))
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
                "status": status,
                "method": method,
                "detail": detail,
            }
        )

    total = len(dataset)
    conservative_low, conservative_high = wilson_interval(totals["correct"], total)
    upper_successes = totals["correct"] + totals["unknown"]
    review_low, review_high = wilson_interval(upper_successes, total)
    return {
        "summary": {
            "total": total,
            **{status: totals[status] for status in STATUSES},
            "conservative_accuracy": totals["correct"] / total if total else 0.0,
            "reviewable_accuracy_upper_bound": upper_successes / total if total else 0.0,
            "conservative_wilson_95": [conservative_low, conservative_high],
            "reviewable_wilson_95_upper_scenario": [review_low, review_high],
            "usage": dict(usage),
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    scored = score_run(load_jsonl(args.dataset), args.output_dir)
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
