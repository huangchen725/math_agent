"""Shared filesystem, JSON, hashing, and console helpers for offline evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def configure_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json_object(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} is not a JSON object")
    return loaded


def read_jsonl_objects(
    path: Path,
    *,
    required_nonempty_strings: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number} of {path}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {line_number} of {path} is not a JSON object")
            for field in required_nonempty_strings:
                value = record.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(
                        f"line {line_number} of {path} has no non-empty {field}"
                    )
            records.append(record)
    return records


def atomic_write_text(path: Path, text: str) -> None:
    """Replace one output atomically using a temporary file in the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            file.write(text)
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_json(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def write_jsonl(
    path: Path,
    records: Iterable[dict[str, Any]],
    *,
    sort_keys: bool = False,
) -> None:
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=sort_keys) + "\n"
        for record in records
    )
    atomic_write_text(path, payload)
