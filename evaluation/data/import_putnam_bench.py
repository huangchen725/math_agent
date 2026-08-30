"""Create a deterministic public university-competition benchmark from PutnamBench."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
# Git is invoked with a resolved executable, a fixed argument shape, and no shell.
import subprocess  # nosec B404
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..io_utils import configure_utf8_stdout, file_sha256, write_json, write_jsonl

_PROBLEM_ID = re.compile(r"^putnam_(\d{4})_([ab])(\d)$")
_NONE_SOLUTIONS = {"", "none", "none."}
_SUBJECT_NAMES = {
    "abstract_algebra": "抽象代数",
    "algebra": "代数",
    "analysis": "分析",
    "combinatorics": "组合数学",
    "geometry": "几何",
    "linear_algebra": "线性代数",
    "number_theory": "数论",
    "probability": "概率论",
    "set_theory": "集合论",
}


def _source_commit(source_path: Path) -> str | None:
    git_executable = shutil.which("git")
    if not git_executable:
        return None
    result = subprocess.run(
        [git_executable, "-C", str(source_path.parent), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )  # nosec B603
    return result.stdout.strip() if result.returncode == 0 else None


def _has_target_solution(record: dict[str, Any]) -> bool:
    solution = str(record.get("informal_solution", "")).strip().casefold()
    return solution not in _NONE_SOLUTIONS


def _difficulty(problem_id: str) -> tuple[str, str, int, str]:
    match = _PROBLEM_ID.fullmatch(problem_id)
    if not match:
        raise ValueError(f"invalid Putnam problem id: {problem_id!r}")
    year, section, number_text = match.groups()
    number = int(number_text)
    if number <= 2:
        band = "introductory"
    elif number <= 4:
        band = "intermediate"
    else:
        band = "challenge"
    return year, section.upper(), number, band


def _primary_tag(record: dict[str, Any]) -> str:
    tags = record.get("tags")
    if not isinstance(tags, list) or not tags:
        return "uncategorized"
    return str(tags[0])


def _stratified_sample(
    records: list[dict[str, Any]],
    *,
    count: int,
    seed: int,
) -> list[dict[str, Any]]:
    if count < 0 or count > len(records):
        raise ValueError(f"requested sample size {count} exceeds pool size {len(records)}")
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        _, _, _, difficulty_band = _difficulty(str(record["problem_name"]))
        groups[(_primary_tag(record), difficulty_band)].append(record)

    for group in groups.values():
        group.sort(
            key=lambda item: hashlib.sha256(
                f"{seed}:item:{item['problem_name']}".encode("utf-8")
            ).digest()
        )
    group_keys = sorted(
        groups,
        key=lambda key: hashlib.sha256(
            f"{seed}:group:{key[0]}:{key[1]}".encode("utf-8")
        ).digest(),
    )

    selected: list[dict[str, Any]] = []
    while len(selected) < count:
        made_progress = False
        for key in group_keys:
            if groups[key] and len(selected) < count:
                selected.append(groups[key].pop())
                made_progress = True
        if not made_progress:
            raise RuntimeError("stratified sampler exhausted before reaching requested count")
    return selected


def _benchmark_record(record: dict[str, Any], source_commit: str) -> dict[str, Any]:
    problem_id = str(record["problem_name"])
    year, section, number, difficulty_band = _difficulty(problem_id)
    tags = [str(tag) for tag in record.get("tags", [])]
    primary_tag = tags[0] if tags else "uncategorized"
    solution = str(record.get("informal_solution", "")).strip()
    has_target = _has_target_solution(record)
    return {
        "idx": problem_id,
        "problem": str(record["informal_statement"]).strip(),
        "answer": solution if has_target else "Manual proof review required.",
        "subject": _SUBJECT_NAMES.get(primary_tag, primary_tag),
        "task_type": "answer_and_justification" if has_target else "proof",
        "level": f"Putnam {section}{number}",
        "source": f"PutnamBench informal statements@{source_commit[:12]}",
        "license": "Informal statements distributed with MAA permission via PutnamBench",
        "split": "test",
        "grading_mode": "manual_blind",
        "answer_type": "target_with_justification" if has_target else "proof",
        "reference_solution": solution if has_target else "",
        "rubric": (
            "Check both the requested conclusion and the mathematical justification. "
            "Use a blinded independent reviewer."
        ),
        "source_problem_id": problem_id,
        "source_year": int(year),
        "source_section": section,
        "source_number": number,
        "difficulty_band": difficulty_band,
        "tags": tags,
        "source_url": "https://github.com/trishullab/PutnamBench",
        "source_commit": source_commit,
    }


def build_benchmark(
    source_path: Path,
    *,
    source_commit: str,
    count: int = 120,
    answer_target_count: int = 72,
    seed: int = 20260830,
    recent_from_year: int = 2022,
    recent_count: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    source_path = source_path.resolve()
    if count <= 0:
        raise ValueError("count must be positive")
    if not 0 <= answer_target_count <= count:
        raise ValueError("answer_target_count must satisfy 0 <= value <= count")
    if not 0 <= recent_count <= count:
        raise ValueError("recent_count must satisfy 0 <= value <= count")
    actual_commit = _source_commit(source_path)
    if actual_commit and actual_commit != source_commit:
        raise ValueError(
            f"source checkout is {actual_commit}, expected pinned commit {source_commit}"
        )

    loaded = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        raise ValueError("PutnamBench source must be a JSON array")
    valid: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for position, item in enumerate(loaded):
        if not isinstance(item, dict):
            raise ValueError(f"source item {position} is not an object")
        problem_id = str(item.get("problem_name", ""))
        statement = str(item.get("informal_statement", "")).strip()
        if not _PROBLEM_ID.fullmatch(problem_id) or not statement:
            raise ValueError(f"source item {position} is malformed")
        if problem_id in seen_ids:
            raise ValueError(f"duplicate source problem id: {problem_id}")
        seen_ids.add(problem_id)
        valid.append(item)

    target_pool = [item for item in valid if _has_target_solution(item)]
    proof_pool = [item for item in valid if not _has_target_solution(item)]
    if recent_count:
        is_recent = lambda item: int(_difficulty(str(item["problem_name"]))[0]) >= recent_from_year
        recent_targets = [item for item in target_pool if is_recent(item)]
        recent_proofs = [item for item in proof_pool if is_recent(item)]
        historical_targets = [item for item in target_pool if not is_recent(item)]
        historical_proofs = [item for item in proof_pool if not is_recent(item)]
        proof_count = count - answer_target_count
        desired_recent_targets = round(recent_count * answer_target_count / count)
        lower = max(
            0,
            recent_count - len(recent_proofs),
            answer_target_count - len(historical_targets),
        )
        upper = min(
            recent_count,
            len(recent_targets),
            answer_target_count,
            len(historical_proofs) - proof_count + recent_count,
        )
        if lower > upper:
            raise ValueError("requested recent/answer/proof quotas cannot be satisfied")
        recent_target_count = min(upper, max(lower, desired_recent_targets))
        recent_proof_count = recent_count - recent_target_count
        target_records = _stratified_sample(
            recent_targets,
            count=recent_target_count,
            seed=seed,
        ) + _stratified_sample(
            historical_targets,
            count=answer_target_count - recent_target_count,
            seed=seed + 1,
        )
        proof_records = _stratified_sample(
            recent_proofs,
            count=recent_proof_count,
            seed=seed + 2,
        ) + _stratified_sample(
            historical_proofs,
            count=proof_count - recent_proof_count,
            seed=seed + 3,
        )
    else:
        recent_target_count = 0
        recent_proof_count = 0
        target_records = _stratified_sample(
            target_pool,
            count=answer_target_count,
            seed=seed,
        )
        proof_records = _stratified_sample(
            proof_pool,
            count=count - answer_target_count,
            seed=seed + 1,
        )
    selected = target_records + proof_records
    selected.sort(
        key=lambda item: hashlib.sha256(
            f"{seed + 2}:final:{item['problem_name']}".encode("utf-8")
        ).digest()
    )
    benchmark = [_benchmark_record(item, source_commit) for item in selected]

    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark_kind": "third_party_public_university_competition",
        "claim_boundary": (
            "Public benchmark; model pretraining overlap is unknown. "
            "It is not a sealed or pretraining-independent accuracy estimate."
        ),
        "source": {
            "name": "PutnamBench",
            "url": "https://github.com/trishullab/PutnamBench",
            "commit": source_commit,
            "source_file": "informal/putnam.json",
            "source_sha256": file_sha256(source_path),
            "source_records": len(valid),
            "license_note": (
                "PutnamBench states that informal statements are available with MAA permission."
            ),
        },
        "selection": {
            "seed": seed,
            "items": len(benchmark),
            "answer_target_items": answer_target_count,
            "proof_items": count - answer_target_count,
            "recent_from_year": recent_from_year,
            "recent_items": recent_count,
            "recent_answer_target_items": recent_target_count,
            "recent_proof_items": recent_proof_count,
            "selected_ids": [item["idx"] for item in benchmark],
            "subject_counts": dict(
                sorted(Counter(str(item["subject"]) for item in benchmark).items())
            ),
            "difficulty_counts": dict(
                sorted(Counter(str(item["difficulty_band"]) for item in benchmark).items())
            ),
        },
    }
    return benchmark, manifest


def write_benchmark(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    output_path: Path,
    manifest_path: Path,
) -> None:
    write_jsonl(output_path, records)
    manifest["dataset_sha256"] = file_sha256(output_path)
    manifest["dataset_bytes"] = output_path.stat().st_size
    write_json(manifest_path, manifest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Pinned PutnamBench informal/putnam.json")
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--answer-target-count", type=int, default=72)
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--recent-from-year", type=int, default=2022)
    parser.add_argument("--recent-count", type=int, default=0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_utf8_stdout()
    records, manifest = build_benchmark(
        args.source,
        source_commit=args.source_commit,
        count=args.count,
        answer_target_count=args.answer_target_count,
        seed=args.seed,
        recent_from_year=args.recent_from_year,
        recent_count=args.recent_count,
    )
    write_benchmark(records, manifest, output_path=args.output, manifest_path=args.manifest)
    print(json.dumps({
        "items": len(records),
        "dataset_sha256": manifest["dataset_sha256"],
        "manifest": str(args.manifest),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
