"""Shared repository helpers for quality and release tooling."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(payload)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def run_git(
    args: Iterable[str],
    *,
    root: Path = PROJECT_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git executable is required")
    # The executable is resolved by shutil.which and arguments are never shell text.
    return subprocess.run(  # nosec B603
        [git_executable, *args],
        cwd=root,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def read_git_blob(root: Path, commit: str, relative: str) -> bytes:
    git_executable = shutil.which("git")
    if not git_executable:
        raise RuntimeError("git executable is required")
    # Commit comes from Git itself and relative is selected from git ls-files.
    completed = subprocess.run(  # nosec B603
        [git_executable, "cat-file", "blob", f"{commit}:{relative}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def git_snapshot(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    commit = run_git(["rev-parse", "HEAD"], root=root).stdout.strip()
    tree = run_git(["rev-parse", "HEAD^{tree}"], root=root).stdout.strip()
    branch = run_git(["branch", "--show-current"], root=root).stdout.strip()
    commit_timestamp = int(
        run_git(["show", "-s", "--format=%ct", "HEAD"], root=root).stdout.strip()
    )
    status_lines = [
        line
        for line in run_git(
            ["status", "--porcelain", "--untracked-files=all"],
            root=root,
        ).stdout.splitlines()
        if line.strip()
    ]
    return {
        "commit": commit,
        "tree": tree,
        "branch": branch,
        "commit_timestamp": commit_timestamp,
        "worktree_clean": not status_lines,
        "dirty_paths": [line[3:] if len(line) > 3 else line for line in status_lines],
    }
