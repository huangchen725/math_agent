"""Run the complete offline quality gate and write a machine-readable report."""

from __future__ import annotations

import argparse
import os
import subprocess  # nosec B404
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .project_utils import PROJECT_ROOT, atomic_write_json, git_snapshot


EVALUATION_MODULES = (
    "evaluation.data.audit_dataset",
    "evaluation.data.generate_internal_benchmark",
    "evaluation.data.import_putnam_bench",
    "evaluation.scoring.rescore_report",
    "evaluation.scoring.score_run",
    "evaluation.scoring.truncation_gate",
    "evaluation.experiments.freeze_experiment",
    "evaluation.experiments.blind_review",
    "evaluation.experiments.paired_compare",
)
MAX_OUTPUT_CHARS = 6000


def build_checks(
    python: str,
    *,
    quality_dir: Path,
    include_dependency_audit: bool = True,
) -> list[tuple[str, list[str]]]:
    checks: list[tuple[str, list[str]]] = [
        (
            "pytest_coverage",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "--cov=.",
                "--cov-report=term-missing",
                f"--cov-report=xml:{quality_dir / 'coverage.xml'}",
            ],
        ),
        ("ruff", [python, "-m", "ruff", "check", "."]),
        (
            "compileall",
            [
                python,
                "-m",
                "compileall",
                "-q",
                "math_agent",
                "evaluation",
                "scripts",
                "tests",
                "main.py",
                "demo.py",
                "user_agent.py",
                "verify_math.py",
            ],
        ),
        (
            "bandit",
            [
                python,
                "-m",
                "bandit",
                "-q",
                "-r",
                "math_agent",
                "evaluation",
                "scripts",
                "main.py",
                "demo.py",
                "verify_math.py",
            ],
        ),
        (
            "dev_lock_py310_closure",
            [
                python,
                "-m",
                "scripts.check_lock_closure",
                "--lock",
                "requirements-dev.lock",
                "--python-version",
                "3.10",
                "--platform",
                "linux",
            ],
        ),
        ("pip_check", [python, "-m", "pip", "check"]),
        (
            "secret_scan",
            [
                python,
                "-m",
                "scripts.check_secrets",
                "--root",
                ".",
                "--include-untracked",
            ],
        ),
        (
            "markdown_links",
            [python, "-m", "scripts.check_markdown_links", "--root", "."],
        ),
        ("fewshot_dry_run", [python, "verify_math.py"]),
        ("runner_help", [python, "main.py", "--help"]),
    ]
    checks.extend(
        (f"entrypoint_{module.rsplit('.', 1)[-1]}", [python, "-m", module, "--help"])
        for module in EVALUATION_MODULES
    )
    if include_dependency_audit:
        checks.insert(
            5,
            (
                "pip_audit",
                [
                    python,
                    "-m",
                    "pip_audit",
                    "--disable-pip",
                    "--no-deps",
                    "--progress-spinner",
                    "off",
                    "-r",
                    "requirements.lock",
                    "-r",
                    "requirements-dev.lock",
                    "-r",
                    "requirements-demo.lock",
                ],
            ),
        )
    return checks


def _output_tail(output: str) -> str:
    return output[-MAX_OUTPUT_CHARS:]


def _sanitize_text(value: str, root: Path) -> str:
    replacements = (
        (str(root), "<repo>"),
        (root.as_posix(), "<repo>"),
        (str(Path.home()), "<home>"),
        (Path.home().as_posix(), "<home>"),
    )
    sanitized = value
    for original, replacement in replacements:
        if original:
            sanitized = sanitized.replace(original, replacement)
    return sanitized


def _reported_command(command: list[str], root: Path) -> list[str]:
    reported = [_sanitize_text(argument, root) for argument in command]
    try:
        if Path(command[0]).resolve() == Path(sys.executable).resolve():
            reported[0] = "<python>"
    except OSError:
        pass
    return reported


def execute_check(name: str, command: list[str], root: Path) -> dict[str, Any]:
    started = time.monotonic()
    temporary_root = root / ".quality" / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "TEMP": str(temporary_root),
        "TMP": str(temporary_root),
        "TMPDIR": str(temporary_root),
    }
    # Commands are constructed from the fixed build_checks table without a shell.
    completed = subprocess.run(  # nosec B603
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        check=False,
    )
    duration_ms = round((time.monotonic() - started) * 1000)
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    return {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "duration_ms": duration_ms,
        "command": _reported_command(command, root),
        "output_tail": _sanitize_text(_output_tail(combined), root),
    }


def run_quality_gates(
    root: Path,
    output: Path,
    *,
    include_dependency_audit: bool = True,
) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    quality_dir = output.parent
    quality_dir.mkdir(parents=True, exist_ok=True)
    before = git_snapshot(root)
    started_at = datetime.now(timezone.utc).isoformat()
    results: list[dict[str, Any]] = []
    for name, command in build_checks(
        sys.executable,
        quality_dir=quality_dir,
        include_dependency_audit=include_dependency_audit,
    ):
        print(f"[quality] {name} ...", flush=True)
        result = execute_check(name, command, root)
        results.append(result)
        print(f"[quality] {name}: {result['status']}", flush=True)
    after = git_snapshot(root)
    failed = [result["name"] for result in results if result["status"] != "passed"]
    report = {
        "schema_version": 1,
        "status": "passed" if not failed else "failed",
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "code": before,
        "worktree_after": after,
        "dependency_audit_included": include_dependency_audit,
        "failed_checks": failed,
        "checks": results,
    }
    atomic_write_json(output, report)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / ".quality" / "quality-report.json",
    )
    parser.add_argument(
        "--skip-dependency-audit",
        action="store_true",
        help="Skip the network-backed vulnerability query; such a report cannot authorize a formal release.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_quality_gates(
        PROJECT_ROOT,
        args.output,
        include_dependency_audit=not args.skip_dependency_audit,
    )
    print(f"Quality report: {args.output} ({report['status']})")
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
