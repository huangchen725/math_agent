"""Build a bounded, deterministic source delivery archive with provenance."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from agent import AgentConfig
from competition_policy import (
    COMPETITION_MANUAL_SHA256,
    FORMAL_COMPETITION_MODEL,
    FORMAL_COMPETITION_MODELS,
    OFFICIAL_BASELINE_COMMIT,
    OFFICIAL_EVIDENCE_VERIFIED_ON,
    OFFICIAL_EVIDENCE_URLS,
    OFFICIAL_MATERIAL_SHA256,
    OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
)

from .check_secrets import scan_paths
from .project_utils import (
    PROJECT_ROOT,
    atomic_write_bytes,
    canonical_json_bytes,
    git_snapshot,
    read_git_blob,
    run_git,
    sha256_bytes,
    sha256_file,
)
from .run_quality_gates import EVALUATION_MODULES


MAX_RELEASE_FILE_BYTES = 5 * 1024 * 1024
MAX_RELEASE_TOTAL_BYTES = 50 * 1024 * 1024
MAX_QUALITY_REPORT_BYTES = 2 * 1024 * 1024
RELEASE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
ROOT_FILES = {
    ".env.example",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "ARCHITECTURE.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "SUBMISSION_INFO.md",
    "THIRD_PARTY_NOTICES.md",
    "agent.py",
    "agent_config.py",
    "agent_prompts.py",
    "agent_types.py",
    "answer_equivalence.py",
    "budget.py",
    "candidate_evaluation.py",
    "candidate_generation.py",
    "candidate_selection.py",
    "competition_policy.py",
    "context.py",
    "demo.py",
    "deterministic_verifier.py",
    "domain_prompts.py",
    "domain_router.py",
    "llm_client.py",
    "main.py",
    "math_parsing.py",
    "math_tools.py",
    "model_calls.py",
    "model_gateway.py",
    "pyproject.toml",
    "requirements-demo.lock",
    "requirements-demo.txt",
    "requirements-dev.lock",
    "requirements-dev.txt",
    "requirements.lock",
    "requirements.txt",
    "response_processing.py",
    "solver.py",
    "task_router.py",
    "tool_executor.py",
    "tool_implementations.py",
    "tool_loop.py",
    "tool_registry.py",
    "trace_sanitizer.py",
    "truncation.py",
    "user_agent.py",
    "verify_math.py",
    "创新点说明.md",
    "技术报告.md",
}
ALLOWED_PREFIXES = (
    ".agents/skills/math-agent-maintainer/",
    ".github/",
    "docs/",
    "evaluation/",
    "sample_data/",
    "scripts/",
    "tests/",
)
ALLOWED_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
REQUIRED_RELEASE_FILES = {
    "ARCHITECTURE.md",
    "LICENSE",
    "README.md",
    "docs/COMPETITION_COMPLIANCE.md",
    "docs/ENGINEERING_SPECIFICATION.md",
    "docs/OFFICIAL_MATERIALS_REGISTER.md",
    "agent.py",
    "agent_config.py",
    "competition_policy.py",
    "requirements-dev.lock",
    "requirements.lock",
    "scripts/check_competition_compliance.py",
    "user_agent.py",
}
REQUIRED_QUALITY_CHECKS = {
    "bandit",
    "compileall",
    "competition_compliance",
    "dev_lock_py310_closure",
    "fewshot_dry_run",
    "markdown_links",
    "pip_audit",
    "pip_check",
    "pytest_coverage",
    "ruff",
    "runner_help",
    "secret_scan",
    *(f"entrypoint_{module.rsplit('.', 1)[-1]}" for module in EVALUATION_MODULES),
}


class ReleaseError(RuntimeError):
    """Raised when release provenance or contents are unsafe."""


def _is_release_path(relative: str) -> bool:
    if relative in ROOT_FILES:
        return True
    return relative.endswith(tuple(ALLOWED_SUFFIXES)) and relative.startswith(ALLOWED_PREFIXES)


def _tracked_paths(root: Path) -> set[str]:
    return {
        item
        for item in run_git(["ls-files", "-z"], root=root).stdout.split("\0")
        if item
    }


def _workspace_paths(root: Path) -> set[str]:
    return {
        item
        for item in run_git(
            ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            root=root,
        ).stdout.split("\0")
        if item
    }


def collect_release_files(root: Path, *, include_untracked: bool) -> dict[str, Path]:
    root = root.resolve()
    candidates = _workspace_paths(root) if include_untracked else _tracked_paths(root)
    selected: dict[str, Path] = {}
    total_bytes = 0
    for relative in sorted(candidates):
        normalized = PurePosixPath(relative).as_posix()
        if not _is_release_path(normalized):
            continue
        path = root / Path(*PurePosixPath(normalized).parts)
        if path.is_symlink():
            raise ReleaseError(f"release input may not be a symlink: {normalized}")
        if not path.is_file():
            raise ReleaseError(f"release input is missing: {normalized}")
        size = path.stat().st_size
        if size > MAX_RELEASE_FILE_BYTES:
            raise ReleaseError(f"release input exceeds per-file limit: {normalized}")
        total_bytes += size
        if total_bytes > MAX_RELEASE_TOTAL_BYTES:
            raise ReleaseError("release inputs exceed total size limit")
        selected[normalized] = path
    missing = sorted(REQUIRED_RELEASE_FILES - set(selected))
    if missing:
        raise ReleaseError(f"required release files are missing: {missing}")
    return selected


def load_quality_report(path: Path, snapshot: dict[str, Any], *, formal: bool) -> dict[str, Any]:
    if not path.is_file():
        if formal:
            raise ReleaseError(f"quality report is required: {path}")
        return {"status": "not_provided", "checks": []}
    if path.stat().st_size > MAX_QUALITY_REPORT_BYTES:
        raise ReleaseError("quality report exceeds size limit")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseError(f"quality report is invalid: {exc}") from exc
    if not isinstance(report, dict):
        raise ReleaseError("quality report must be a JSON object")
    if not formal:
        return report
    if report.get("status") != "passed" or not report.get("dependency_audit_included"):
        raise ReleaseError("formal release requires a passed report with dependency audit")
    report_code = report.get("code")
    report_after = report.get("worktree_after")
    if not isinstance(report_code, dict) or not isinstance(report_after, dict):
        raise ReleaseError("quality report has no code snapshots")
    if report_code.get("commit") != snapshot["commit"]:
        raise ReleaseError("quality report commit does not match HEAD")
    if report_code.get("tree") != snapshot["tree"]:
        raise ReleaseError("quality report tree does not match HEAD")
    if report_after.get("commit") != snapshot["commit"] or report_after.get("tree") != snapshot["tree"]:
        raise ReleaseError("repository changed while quality checks were running")
    if not report_code.get("worktree_clean") or not report_after.get("worktree_clean"):
        raise ReleaseError("formal release quality report must come from a clean worktree")
    checks = report.get("checks")
    if not isinstance(checks, list):
        raise ReleaseError("quality report checks must be a list")
    statuses = {
        item.get("name"): item.get("status")
        for item in checks
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    missing = sorted(REQUIRED_QUALITY_CHECKS - set(statuses))
    failed = sorted(name for name in REQUIRED_QUALITY_CHECKS if statuses.get(name) != "passed")
    if missing or failed:
        raise ReleaseError(f"quality report is incomplete; missing={missing}, failed={failed}")
    return report


def load_release_payloads(
    root: Path,
    files: dict[str, Path],
    snapshot: dict[str, Any],
    *,
    formal: bool,
) -> dict[str, bytes]:
    if formal:
        return {
            relative: read_git_blob(root, snapshot["commit"], relative)
            for relative in sorted(files)
        }
    return {relative: path.read_bytes() for relative, path in sorted(files.items())}


def _file_records(payloads: dict[str, bytes]) -> list[dict[str, Any]]:
    return [
        {"path": relative, "bytes": len(payload), "sha256": sha256_bytes(payload)}
        for relative, payload in sorted(payloads.items())
    ]


def build_release_manifest(
    payloads: dict[str, bytes],
    snapshot: dict[str, Any],
    quality_path: Path,
    quality_report: dict[str, Any],
    *,
    model: str,
    formal: bool,
) -> dict[str, Any]:
    config = asdict(AgentConfig())
    locks = [
        {"path": relative, "sha256": sha256_bytes(payload)}
        for relative, payload in sorted(payloads.items())
        if relative.endswith(".lock")
    ]
    quality_summary = {
        "status": quality_report.get("status", "unknown"),
        "dependency_audit_included": bool(quality_report.get("dependency_audit_included")),
        "checks": [
            {"name": item.get("name"), "status": item.get("status")}
            for item in quality_report.get("checks", [])
            if isinstance(item, dict)
        ],
    }
    if quality_path.is_file():
        quality_summary["report_sha256"] = sha256_file(quality_path)
    return {
        "schema_version": 1,
        "status": "formal" if formal else "draft",
        "project": "XH-202627 math agent",
        "model": model,
        "competition": {
            "manual_sha256": COMPETITION_MANUAL_SHA256,
            "official_materials_sha256": dict(OFFICIAL_MATERIAL_SHA256),
            "official_baseline_commit": OFFICIAL_BASELINE_COMMIT,
            "official_evidence_urls": dict(OFFICIAL_EVIDENCE_URLS),
            "official_evidence_verified_on": dict(OFFICIAL_EVIDENCE_VERIFIED_ON),
            "official_web_evidence_verified_on": OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
            "formal_model_default": FORMAL_COMPETITION_MODEL,
            "formal_models_allowed": sorted(FORMAL_COMPETITION_MODELS),
            "formal_model_match": model in FORMAL_COMPETITION_MODELS,
        },
        "source": snapshot,
        "source_date_epoch": snapshot["commit_timestamp"],
        "agent_config": config,
        "dependency_locks": locks,
        "quality": quality_summary,
        "files": _file_records(payloads),
    }


def _zip_datetime(epoch: int) -> tuple[int, int, int, int, int, int]:
    converted = datetime.fromtimestamp(epoch, timezone.utc)
    year = min(2107, max(1980, converted.year))
    return (year, converted.month, converted.day, converted.hour, converted.minute, converted.second)


def _zip_entry(name: str, payload: bytes, epoch: int) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name, date_time=_zip_datetime(epoch))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.flag_bits |= 0x800
    return info, payload


def write_release_archive(
    archive_path: Path,
    payloads: dict[str, bytes],
    manifest: dict[str, Any],
    quality_report: dict[str, Any],
) -> tuple[Path, Path]:
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    entries = dict(payloads)
    entries["release/release-manifest.json"] = canonical_json_bytes(manifest)
    entries["release/quality-report.json"] = canonical_json_bytes(quality_report)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{archive_path.name}.",
        suffix=".tmp",
        dir=archive_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
            strict_timestamps=False,
        ) as archive:
            for name, payload in sorted(entries.items()):
                info, content = _zip_entry(name, payload, manifest["source_date_epoch"])
                archive.writestr(info, content)
        os.replace(temporary_path, archive_path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    digest_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    atomic_write_bytes(
        digest_path,
        f"{sha256_file(archive_path)}  {archive_path.name}\n".encode("ascii"),
    )
    return archive_path, digest_path


def build_release(
    root: Path,
    output_dir: Path,
    quality_path: Path,
    *,
    model: str,
    name: str | None = None,
    allow_dirty: bool = False,
) -> tuple[Path, Path, dict[str, Any]]:
    root = root.resolve()
    unresolved_quality_path = quality_path if quality_path.is_absolute() else root / quality_path
    if unresolved_quality_path.is_symlink():
        raise ReleaseError("quality report may not be a symlink")
    quality_path = unresolved_quality_path.resolve()
    try:
        quality_path.relative_to(root)
    except ValueError as exc:
        raise ReleaseError("quality report must be inside the repository") from exc
    snapshot = git_snapshot(root)
    formal = snapshot["worktree_clean"] and not allow_dirty
    if not snapshot["worktree_clean"] and not allow_dirty:
        raise ReleaseError("formal release requires a clean Git worktree")
    if formal and model not in FORMAL_COMPETITION_MODELS:
        raise ReleaseError(
            "formal competition release requires a documented Intern-S model: "
            f"{', '.join(sorted(FORMAL_COMPETITION_MODELS))}"
        )
    files = collect_release_files(root, include_untracked=allow_dirty)
    secret_findings = scan_paths(root, files.values(), fail_unscannable=True)
    if secret_findings:
        locations = [f"{item.path}:{item.line} ({item.kind})" for item in secret_findings]
        raise ReleaseError(f"release inputs failed secret scan: {locations}")
    quality_report = load_quality_report(quality_path, snapshot, formal=formal)
    if quality_path.is_file():
        quality_findings = scan_paths(root, [quality_path], fail_unscannable=True)
        if quality_findings:
            locations = [
                f"{item.path}:{item.line} ({item.kind})" for item in quality_findings
            ]
            raise ReleaseError(f"quality report failed secret scan: {locations}")
    payloads = load_release_payloads(root, files, snapshot, formal=formal)
    manifest = build_release_manifest(
        payloads,
        snapshot,
        quality_path,
        quality_report,
        model=model,
        formal=formal,
    )
    archive_name = name or f"math-agent-{snapshot['commit'][:12]}"
    if not RELEASE_NAME.fullmatch(archive_name):
        raise ReleaseError("release name must contain only letters, numbers, dot, underscore, or hyphen")
    archive_path = output_dir.resolve() / f"{archive_name}.zip"
    archive_path, digest_path = write_release_archive(
        archive_path,
        payloads,
        manifest,
        quality_report,
    )
    return archive_path, digest_path, manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "dist")
    parser.add_argument(
        "--quality-report",
        type=Path,
        default=PROJECT_ROOT / ".quality" / "quality-report.json",
    )
    parser.add_argument("--model", default=FORMAL_COMPETITION_MODEL)
    parser.add_argument("--name")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Build a draft from the current workspace; never marks the archive formal.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        archive, digest, manifest = build_release(
            PROJECT_ROOT,
            args.output_dir,
            args.quality_report,
            model=args.model,
            name=args.name,
            allow_dirty=args.allow_dirty,
        )
    except ReleaseError as exc:
        print(f"Release refused: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "archive": str(archive),
                "sha256_file": str(digest),
                "commit": manifest["source"]["commit"],
                "files": len(manifest["files"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
