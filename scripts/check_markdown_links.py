"""Validate repository-local links in Markdown without network access."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .project_utils import PROJECT_ROOT


SKIPPED_DIRECTORIES = {
    ".git",
    ".quality",
    ".venv",
    "dist",
    "htmlcov",
    "outputs",
}
INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
FENCED_BLOCK = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)


@dataclass(frozen=True)
class BrokenLink:
    document: str
    target: str
    reason: str


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in SKIPPED_DIRECTORIES for part in path.relative_to(root).parts)
    )


def _link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1:target.index(">")]
    return target.split(maxsplit=1)[0]


def _local_target(raw_target: str) -> str | None:
    target = unquote(_link_target(raw_target))
    if not target or target.startswith("#"):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    return parsed.path


def check_markdown_links(root: Path) -> list[BrokenLink]:
    root = root.resolve()
    broken: list[BrokenLink] = []
    for document in markdown_files(root):
        text = FENCED_BLOCK.sub("", document.read_text(encoding="utf-8"))
        raw_targets = [match.group(1) for match in INLINE_LINK.finditer(text)]
        raw_targets.extend(match.group(1) for match in REFERENCE_LINK.finditer(text))
        for raw_target in raw_targets:
            target = _local_target(raw_target)
            if target is None:
                continue
            resolved = (document.parent / target).resolve()
            try:
                resolved.relative_to(root)
            except ValueError:
                broken.append(
                    BrokenLink(document.relative_to(root).as_posix(), raw_target, "escapes root")
                )
                continue
            if not resolved.exists():
                broken.append(
                    BrokenLink(document.relative_to(root).as_posix(), raw_target, "missing")
                )
    return broken


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    broken = check_markdown_links(args.root)
    if broken:
        for finding in broken:
            print(f"{finding.document}: {finding.target} ({finding.reason})")
        raise SystemExit(1)
    print(f"Markdown local links: OK ({len(markdown_files(args.root.resolve()))} files)")


if __name__ == "__main__":
    main()
