"""Scan repository text for common credential patterns without echoing values."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .project_utils import PROJECT_ROOT, run_git


MAX_SCANNED_FILE_BYTES = 5 * 1024 * 1024
SENSITIVE_FILENAMES = {
    ".env",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pfx", ".pem"}
TOKEN_PATTERNS = {
    "openai-style token": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(
        r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b"
    ),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "bearer token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
}
GENERIC_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|password)"
    r"\s*[:=]\s*(['\"]?)([^\s'\"#,;]{8,})\1"
)
PLACEHOLDER_FRAGMENTS = {
    "changeme",
    "dummy",
    "example",
    "placeholder",
    "replace-me",
    "test-only",
    "your-token",
    "your_api_key",
    "你的token",
}


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str


def candidate_files(root: Path, *, include_untracked: bool = False) -> list[Path]:
    arguments = ["ls-files", "-z"]
    if include_untracked:
        arguments = ["ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    completed = run_git(arguments, root=root)
    return [root / item for item in completed.stdout.split("\0") if item]


def _is_placeholder(value: str) -> bool:
    normalized = value.strip("'\"<>[]{}() ").lower()
    if normalized.startswith(("${", "$env:", "os.getenv", "process.env")):
        return True
    return any(fragment in normalized for fragment in PLACEHOLDER_FRAGMENTS)


def scan_paths(
    root: Path,
    paths: Iterable[Path],
    *,
    fail_unscannable: bool = False,
) -> list[SecretFinding]:
    root = root.resolve()
    findings: list[SecretFinding] = []
    for path in sorted({path.resolve() for path in paths}):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        normalized_name = path.name.casefold()
        sensitive_environment = normalized_name.startswith(".env.") and normalized_name != ".env.example"
        if (
            normalized_name in SENSITIVE_FILENAMES
            or sensitive_environment
            or path.suffix.casefold() in SENSITIVE_SUFFIXES
        ):
            findings.append(SecretFinding(relative, 1, "sensitive filename"))
            continue
        if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
            if fail_unscannable:
                findings.append(SecretFinding(relative, 1, "file exceeds scan limit"))
            continue
        payload = path.read_bytes()
        if b"\0" in payload:
            if fail_unscannable:
                findings.append(SecretFinding(relative, 1, "binary content"))
            continue
        text = payload.decode("utf-8", errors="replace")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in TOKEN_PATTERNS.items():
                if pattern.search(line):
                    findings.append(SecretFinding(relative, line_number, kind))
            for match in GENERIC_ASSIGNMENT.finditer(line):
                if not _is_placeholder(match.group(2)):
                    findings.append(
                        SecretFinding(relative, line_number, "credential assignment")
                    )
    return sorted(set(findings), key=lambda item: (item.path, item.line, item.kind))


def check_repository_files(
    root: Path,
    *,
    include_untracked: bool = False,
) -> list[SecretFinding]:
    root = root.resolve()
    return scan_paths(
        root,
        candidate_files(root, include_untracked=include_untracked),
        fail_unscannable=True,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Also scan non-ignored untracked files in the working tree.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.root.resolve()
    findings = check_repository_files(root, include_untracked=args.include_untracked)
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: possible {finding.kind}")
        raise SystemExit(1)
    scope = "tracked and untracked" if args.include_untracked else "tracked"
    count = len(candidate_files(root, include_untracked=args.include_untracked))
    print(f"Repository secret scan: OK ({count} {scope} files)")


if __name__ == "__main__":
    main()
