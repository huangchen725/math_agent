"""Freeze a reproducible math-agent evaluation manifest without calling a model."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
# Git is invoked with a resolved executable, a fixed argument shape, and no shell.
import subprocess  # nosec B404
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..data.audit_dataset import (
    ReferenceProblem,
    audit_dataset,
    default_references,
    load_jsonl,
)
from ..io_utils import PROJECT_ROOT, configure_utf8_stdout, file_sha256, write_json
from math_agent import AgentConfig


ROOT = PROJECT_ROOT
VALID_DATASET_ROLES = {"development", "regression", "public_test", "sealed_test"}
REQUIRED_FIELDS = (
    "idx",
    "problem",
    "answer",
    "subject",
    "task_type",
    "level",
    "source",
    "license",
    "split",
)
RUNTIME_FILES = (
    "user_agent.py",
    "math_agent/__init__.py",
    "math_agent/agent.py",
    "math_agent/agent_config.py",
    "math_agent/competition_policy.py",
    "math_agent/agent_prompts.py",
    "math_agent/agent_types.py",
    "math_agent/answer_equivalence.py",
    "math_agent/candidate_evaluation.py",
    "math_agent/candidate_generation.py",
    "math_agent/candidate_selection.py",
    "math_agent/context.py",
    "math_agent/domain_router.py",
    "math_agent/model_calls.py",
    "math_agent/model_gateway.py",
    "math_agent/response_processing.py",
    "math_agent/solver.py",
    "math_agent/task_router.py",
    "math_agent/truncation.py",
    "math_agent/deterministic_verifier.py",
    "math_agent/budget.py",
    "math_agent/domain_prompts.py",
    "math_agent/math_parsing.py",
    "math_agent/math_tools.py",
    "math_agent/tool_implementations.py",
    "math_agent/tool_loop.py",
    "math_agent/tool_registry.py",
    "math_agent/tool_executor.py",
    "math_agent/llm_client.py",
    "main.py",
    "demo.py",
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _git(
    args: list[str],
    *,
    check: bool = True,
    root: Path = ROOT,
) -> subprocess.CompletedProcess[str]:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git executable is required to freeze an experiment")
    return subprocess.run(
        [git_executable, *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )  # nosec B603


def runtime_fingerprint(root: Path = ROOT) -> str:
    digest = hashlib.sha256()
    for relative in RUNTIME_FILES:
        path = root / relative
        if not path.is_file():
            raise FileNotFoundError(f"runtime file is missing: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def git_snapshot(root: Path = ROOT) -> dict[str, Any]:
    root = root.resolve()
    commit = _git(["rev-parse", "HEAD"], root=root).stdout.strip()
    status_lines = [
        line
        for line in _git(["status", "--porcelain"], root=root).stdout.splitlines()
        if line.strip()
    ]
    return {
        "commit": commit,
        "worktree_clean": not status_lines,
        "dirty_paths": [line[3:] if len(line) > 3 else line for line in status_lines],
        "runtime_sha256": runtime_fingerprint(root),
        "root_name": root.name,
    }


def _path_is_tracked(path: Path) -> bool:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return False
    result = _git(["ls-files", "--error-unmatch", "--", relative.as_posix()], check=False)
    return result.returncode == 0


def _references_from_paths(paths: Iterable[Path]) -> list[ReferenceProblem]:
    references: list[ReferenceProblem] = []
    for path in paths:
        for item in load_jsonl(path):
            references.append(
                ReferenceProblem(
                    source=f"reference_dataset:{path.name}",
                    subject=str(item.get("subject", "")),
                    problem=str(item["problem"]),
                )
            )
    return references


def _validate_records(
    records: list[dict[str, Any]],
    *,
    dataset_role: str,
    minimum_items: int,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    if len(records) < minimum_items:
        errors.append(f"dataset has {len(records)} items; minimum is {minimum_items}")

    missing_counts = {
        field: sum(not str(record.get(field, "")).strip() for record in records)
        for field in REQUIRED_FIELDS
    }
    for field, count in missing_counts.items():
        if count:
            errors.append(f"field {field!r} is missing or empty in {count} records")

    indexes = [str(record.get("idx", "")) for record in records]
    duplicate_indexes = [
        idx for idx, count in Counter(indexes).items() if idx and count > 1
    ]
    if duplicate_indexes:
        errors.append(f"duplicate idx values: {duplicate_indexes[:10]}")

    split_counts = Counter(str(record.get("split", "<missing>")) for record in records)
    if dataset_role in {"public_test", "sealed_test"} and set(split_counts) != {"test"}:
        errors.append(f"{dataset_role} requires every record to use split='test'")

    return errors, {
        "missing_required_fields": missing_counts,
        "duplicate_idx_count": len(duplicate_indexes),
        "split_counts": dict(sorted(split_counts.items())),
        "subject_counts": dict(
            sorted(Counter(str(item.get("subject", "<missing>")) for item in records).items())
        ),
        "task_type_counts": dict(
            sorted(Counter(str(item.get("task_type", "<missing>")) for item in records).items())
        ),
        "source_counts": dict(
            sorted(Counter(str(item.get("source", "<missing>")) for item in records).items())
        ),
    }


def build_manifest(
    dataset_path: Path,
    *,
    experiment_id: str,
    model: str,
    dataset_role: str,
    repetitions: int,
    concurrency: int,
    minimum_items: int = 100,
    reference_datasets: Iterable[Path] = (),
    allow_dirty: bool = False,
    code_root: Path = ROOT,
) -> dict[str, Any]:
    if dataset_role not in VALID_DATASET_ROLES:
        raise ValueError(f"invalid dataset role: {dataset_role}")
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if minimum_items <= 0:
        raise ValueError("minimum_items must be positive")
    if not experiment_id.strip() or not model.strip():
        raise ValueError("experiment_id and model must be non-empty")

    dataset_path = dataset_path.resolve()
    records = load_jsonl(dataset_path)
    errors, dataset_summary = _validate_records(
        records,
        dataset_role=dataset_role,
        minimum_items=minimum_items,
    )
    references = default_references()
    references.extend(_references_from_paths(reference_datasets))
    audit = audit_dataset(records, references)
    overlap_counts = dict(audit["overlap_counts"])
    if dataset_role in {"public_test", "sealed_test"}:
        if overlap_counts["exact"] or overlap_counts["template"]:
            errors.append("test data overlaps prompt/sample/reference data exactly or by template")
    if dataset_role == "sealed_test" and _path_is_tracked(dataset_path):
        errors.append("sealed_test data must not be tracked by Git")

    code = git_snapshot(code_root)
    if not code["worktree_clean"] and not allow_dirty:
        errors.append("worktree is dirty; freeze from a clean commit or use --allow-dirty for a draft")

    agent_config = asdict(AgentConfig())
    warnings: list[str] = []
    if overlap_counts["near"]:
        warnings.append("near-overlap matches require manual review before a formal run")
    if dataset_role == "public_test":
        warnings.append("public data may occur in model pretraining; do not claim a sealed estimate")
    if allow_dirty and not code["worktree_clean"]:
        warnings.append("dirty-worktree manifests are drafts and cannot support a final claim")

    manifest = {
        "schema_version": 1,
        "status": "frozen" if not errors and code["worktree_clean"] else "draft",
        "experiment_id": experiment_id.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "filename": dataset_path.name,
            "role": dataset_role,
            "sha256": file_sha256(dataset_path),
            "bytes": dataset_path.stat().st_size,
            "items": len(records),
            **dataset_summary,
            "overlap_counts": overlap_counts,
            "overlap_indexes": [str(item.get("idx", "")) for item in audit["overlaps"]],
        },
        "code": code,
        "model": {"configured_name": model.strip()},
        "agent_config": agent_config,
        "agent_config_sha256": _canonical_sha256(agent_config),
        "runner": {
            "repetitions": repetitions,
            "local_max_concurrency": concurrency,
        },
        "protocol": {
            "paired_items": True,
            "answer_fields_sent_to_agent": False,
            "change_one_runtime_variable_at_a_time": True,
            "manual_items_require_blind_review": True,
        },
        "warnings": warnings,
        "errors": errors,
    }
    if errors and not allow_dirty:
        raise ValueError("; ".join(errors))
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--dataset-role", choices=sorted(VALID_DATASET_ROLES), required=True)
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--minimum-items", type=int, default=100)
    parser.add_argument("--reference-dataset", type=Path, action="append", default=[])
    parser.add_argument(
        "--code-root",
        type=Path,
        default=ROOT,
        help="Clean Git worktree whose runtime implementation will be evaluated.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Create a draft manifest instead of refusing a dirty worktree.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_utf8_stdout()
    manifest = build_manifest(
        args.dataset,
        experiment_id=args.experiment_id,
        model=args.model,
        dataset_role=args.dataset_role,
        repetitions=args.repetitions,
        concurrency=args.concurrency,
        minimum_items=args.minimum_items,
        reference_datasets=args.reference_dataset,
        allow_dirty=args.allow_dirty,
        code_root=args.code_root,
    )
    write_json(args.output, manifest)
    print(json.dumps({
        "status": manifest["status"],
        "experiment_id": manifest["experiment_id"],
        "dataset_sha256": manifest["dataset"]["sha256"],
        "items": manifest["dataset"]["items"],
        "errors": manifest["errors"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
