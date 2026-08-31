import json
import re
import sys
from pathlib import Path

from scripts.check_markdown_links import check_markdown_links
from scripts.check_secrets import MAX_SCANNED_FILE_BYTES, candidate_files, scan_paths
from scripts.run_quality_gates import build_checks, execute_check


ROOT = Path(__file__).resolve().parents[1]


def test_markdown_link_checker_accepts_local_anchor_and_external_links(tmp_path: Path) -> None:
    (tmp_path / "target.md").write_text("# Target\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[local](target.md#target) [anchor](#section) [web](https://example.com)\n",
        encoding="utf-8",
    )

    assert check_markdown_links(tmp_path) == []


def test_markdown_link_checker_rejects_missing_and_escaping_targets(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "[missing](missing.md) [escape](../outside.md)\n",
        encoding="utf-8",
    )

    findings = check_markdown_links(tmp_path)

    assert {(item.target, item.reason) for item in findings} == {
        ("missing.md", "missing"),
        ("../outside.md", "escapes root"),
    }


def test_secret_scanner_detects_tokens_without_returning_secret_text(tmp_path: Path) -> None:
    token = "sk-" + "A" * 24
    path = tmp_path / "config.py"
    path.write_text(f'API_KEY = "{token}"\n', encoding="utf-8")

    findings = scan_paths(tmp_path, [path])

    assert findings
    assert all(token not in repr(item) for item in findings)


def test_secret_scanner_allows_documented_placeholders(tmp_path: Path) -> None:
    path = tmp_path / ".env.example"
    path.write_text(
        "INTERN_API_KEY=your_api_key_here\nPASSWORD=placeholder\n",
        encoding="utf-8",
    )

    assert scan_paths(tmp_path, [path]) == []


def test_secret_scanner_rejects_environment_variants_case_insensitively(tmp_path: Path) -> None:
    path = tmp_path / ".ENV.production"
    path.write_text("placeholder\n", encoding="utf-8")

    findings = scan_paths(tmp_path, [path])

    assert [item.kind for item in findings] == ["sensitive filename"]


def test_secret_scanner_strict_mode_rejects_oversized_text(tmp_path: Path) -> None:
    path = tmp_path / "oversized.txt"
    path.write_bytes(b"x" * (MAX_SCANNED_FILE_BYTES + 1))

    findings = scan_paths(tmp_path, [path], fail_unscannable=True)

    assert [item.kind for item in findings] == ["file exceeds scan limit"]


def test_secret_scanner_can_include_non_ignored_untracked_files(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    (tmp_path / "untracked.txt").write_text("untracked\n", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", ".gitignore", "tracked.txt"], cwd=tmp_path, check=True)

    tracked = {path.name for path in candidate_files(tmp_path)}
    workspace = {
        path.name for path in candidate_files(tmp_path, include_untracked=True)
    }

    assert tracked == {".gitignore", "tracked.txt"}
    assert workspace == {".gitignore", "tracked.txt", "untracked.txt"}


def _locked_packages(path: Path) -> set[str]:
    packages = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line[0].isspace() or line.startswith(("#", "--")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)==[^ ]+", line)
        assert match, f"unlocked requirement in {path.name}: {line}"
        packages.add(match.group(1).lower())
    return packages


def _locked_versions(path: Path) -> dict[str, str]:
    versions = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"([A-Za-z0-9_.-]+)==([^ \\]+)", line)
        if match:
            versions[match.group(1).lower()] = match.group(2)
    return versions


def test_all_dependency_locks_are_exact_and_hashed() -> None:
    runtime = ROOT / "requirements.lock"
    development = ROOT / "requirements-dev.lock"
    demo = ROOT / "requirements-demo.lock"

    runtime_packages = _locked_packages(runtime)
    development_packages = _locked_packages(development)
    demo_packages = _locked_packages(demo)
    assert {"requests", "python-dotenv", "sympy"} <= runtime_packages
    assert {"pytest", "pytest-cov", "ruff", "bandit", "pip-audit", "pip-tools"} <= development_packages
    assert {"gradio", "requests", "python-dotenv", "sympy"} <= demo_packages
    assert _locked_versions(development)["stevedore"] == "5.8.0"
    for path in (runtime, development, demo):
        text = path.read_text(encoding="utf-8")
        assert "# WARNING" not in text
        assert "--no-index" not in text
        assert text.count("--hash=sha256:") >= len(_locked_packages(path))


def test_ci_actions_are_sha_pinned_and_read_only() -> None:
    workflow = (ROOT / ".github" / "workflows" / "offline-quality.yml").read_text(
        encoding="utf-8"
    )

    actions = re.findall(r"uses:\s*([^\s#]+)", workflow)
    assert actions
    assert all(re.fullmatch(r"[^@]+@[0-9a-f]{40}", action) for action in actions)
    assert "contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "pull_request_target" not in workflow
    assert 'python-version: ["3.10", "3.12"]' in workflow
    assert "pip install --require-hashes -r requirements-dev.lock" in workflow
    assert "scripts.run_quality_gates" in workflow
    assert "scripts.build_release" in workflow


def test_quality_gate_covers_required_offline_checks_without_live_api(tmp_path: Path) -> None:
    checks = build_checks(sys.executable, quality_dir=tmp_path)
    names = {name for name, _ in checks}
    flattened = [argument for _, command in checks for argument in command]

    assert {
        "pytest_coverage",
        "ruff",
        "compileall",
        "bandit",
        "pip_check",
        "pip_audit",
        "secret_scan",
        "markdown_links",
        "fewshot_dry_run",
        "runner_help",
    } <= names
    assert "--execute" not in flattened
    assert all(command[:2] != [sys.executable, "demo.py"] for _, command in checks)
    secret_command = dict(checks)["secret_scan"]
    assert "--include-untracked" in secret_command
    audit_command = dict(checks)["pip_audit"]
    assert {
        "requirements.lock",
        "requirements-dev.lock",
        "requirements-demo.lock",
    } <= set(audit_command)
    assert [name for name, _ in build_checks(
        sys.executable,
        quality_dir=tmp_path,
        include_dependency_audit=False,
    ) if name == "pip_audit"] == []


def test_execute_check_records_failure_without_shell(tmp_path: Path) -> None:
    result = execute_check(
        "expected_failure",
        [sys.executable, "-c", "raise SystemExit(7)"],
        tmp_path,
    )

    assert result["status"] == "failed"
    assert result["returncode"] == 7
    assert result["command"][0] == "<python>"


def test_execute_check_redacts_repository_and_home_paths(tmp_path: Path) -> None:
    result = execute_check(
        "path_output",
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        tmp_path,
    )

    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized
    assert str(Path.home()) not in serialized
    assert "<repo>" in result["output_tail"]
