"""Run offline checks for the XH-202627 competition safety boundary."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from math_agent.competition_policy import (
    COMPETITION_MANUAL_SHA256,
    FORMAL_COMPETITION_MODEL,
    OFFICIAL_API_BASE,
    validate_official_api_base,
)
from math_agent.llm_client import DEFAULT_API_BASE, DEFAULT_MODEL

from .build_release import REQUIRED_RELEASE_FILES, _is_release_path
from .project_utils import PROJECT_ROOT


_RUNTIME_ROOT_FILES = ("main.py", "demo.py", "user_agent.py", "verify_math.py")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
_NETWORK_MODULES = frozenset(
    {"aiohttp", "httpx", "requests", "socket", "urllib.request", "websocket", "websockets"}
)
_NETWORK_IMPORT_ALLOWLIST = {"math_agent/llm_client.py": frozenset({"requests"})}
_PRIVATE_ARTIFACTS = (
    ".env",
    ".quality/quality-report.json",
    "dist/release.zip",
    "outputs/answer.json",
)


class _CaptureAgent:
    def __init__(self) -> None:
        self.problem: str | None = None
        self.metadata: dict[str, Any] | None = None

    def solve(self, problem: str, metadata: dict[str, Any]) -> dict[str, Any]:
        self.problem = problem
        self.metadata = metadata
        return {
            "final_response": "离线合规探针\n最终答案：0",
            "trace": [{"step": "compliance_probe", "content": "offline"}],
        }


class _RecordingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.responses = ["最终答案：0\n因为 0+0=0。", "VERDICT: A"]

    def chat(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _runtime_paths(root: Path) -> list[Path]:
    paths = sorted((root / "math_agent").glob("*.py"))
    paths.extend(root / name for name in _RUNTIME_ROOT_FILES)
    return [path for path in paths if path.is_file()]


def _imported_network_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            for network_module in _NETWORK_MODULES:
                if name == network_module or name.startswith(network_module + "."):
                    modules.add(network_module)
    return modules


def _check_runtime_network_boundary(root: Path) -> list[str]:
    findings: list[str] = []
    official_host = urlsplit(OFFICIAL_API_BASE).hostname
    for path in _runtime_paths(root):
        relative = path.relative_to(root).as_posix()
        imported = _imported_network_modules(path)
        unexpected = imported - _NETWORK_IMPORT_ALLOWLIST.get(relative, frozenset())
        if unexpected:
            findings.append(
                f"{relative}: unexpected network imports {sorted(unexpected)}"
            )
        text = path.read_text(encoding="utf-8")
        for match in _URL_PATTERN.finditer(text):
            url = match.group(0).rstrip(".,;)")
            if urlsplit(url).hostname != official_host:
                findings.append(f"{relative}: non-official runtime URL")
    return findings


def _check_answer_isolation_and_json() -> list[str]:
    from main import solve_item
    from math_agent import AgentConfig, ReasoningAgent

    sentinel_answer = "DO_NOT_FORWARD_REFERENCE_7F2A"
    item = {
        "idx": "compliance-probe",
        "problem": "计算 0+0。",
        "answer": sentinel_answer,
        "expected_answer": sentinel_answer,
        "reference_answer": sentinel_answer,
        "reference_solution": sentinel_answer,
        "solution": sentinel_answer,
    }
    agent = _CaptureAgent()
    record = solve_item(agent, item)
    serialized = json.dumps(record, ensure_ascii=False)
    findings: list[str] = []
    if agent.problem != item["problem"]:
        findings.append("runner did not forward the problem exactly")
    if agent.metadata != {"idx": item["idx"]}:
        findings.append("runner forwarded fields other than idx to the agent")
    if sentinel_answer in json.dumps(agent.metadata, ensure_ascii=False):
        findings.append("reference answer content reached agent metadata")
    if record.get("status") != "success":
        findings.append("offline contract probe did not produce success JSON")
    if serialized.count("最终答案：") != 1:
        findings.append("offline contract probe did not preserve one final-answer marker")
    if not str(record.get("final_response", "")).splitlines()[-1].startswith("最终答案："):
        findings.append("final answer is not the last response line")

    client = _RecordingClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=1,
        verifier_voting_times=1,
        enable_critic=False,
        enable_reflection=False,
        enable_fallback=False,
        enable_deterministic_verification=False,
    )
    agent_result = ReasoningAgent(client, config).solve(
        item["problem"],
        {
            "idx": item["idx"],
            "answer": sentinel_answer,
            "reference_solution": sentinel_answer,
        },
    )
    if sentinel_answer in json.dumps(client.calls, ensure_ascii=False):
        findings.append("reference-answer metadata reached a model request")
    if sentinel_answer in json.dumps(agent_result, ensure_ascii=False):
        findings.append("reference-answer metadata leaked into the agent result")
    if str(agent_result.get("final_response", "")).splitlines()[-1] != "最终答案：0":
        findings.append("full Agent compliance probe broke the final-answer contract")
    return findings


def check_competition_compliance(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """Return a machine-readable offline compliance report."""
    root = root.resolve()
    checks: list[dict[str, Any]] = []

    def record(name: str, findings: list[str]) -> None:
        checks.append(
            {
                "name": name,
                "status": "passed" if not findings else "failed",
                "findings": findings,
            }
        )

    policy_findings: list[str] = []
    if DEFAULT_MODEL != FORMAL_COMPETITION_MODEL or DEFAULT_MODEL != "intern-s1":
        policy_findings.append("runtime default model is not the formal Intern-S1 model")
    if DEFAULT_API_BASE != OFFICIAL_API_BASE:
        policy_findings.append("runtime default API base differs from the official endpoint")
    try:
        validate_official_api_base(DEFAULT_API_BASE)
    except RuntimeError:
        policy_findings.append("runtime default API base failed strict validation")
    if len(COMPETITION_MANUAL_SHA256) != 64:
        policy_findings.append("competition manual digest is malformed")
    record("formal_policy", policy_findings)

    record("runtime_network_boundary", _check_runtime_network_boundary(root))
    record("answer_isolation_and_json", _check_answer_isolation_and_json())

    release_findings = [
        f"private artifact would enter release: {path}"
        for path in _PRIVATE_ARTIFACTS
        if _is_release_path(path)
    ]
    required_compliance_files = {
        "docs/COMPETITION_COMPLIANCE.md",
        "docs/ENGINEERING_SPECIFICATION.md",
        "math_agent/competition_policy.py",
        "scripts/check_competition_compliance.py",
    }
    missing_compliance_files = sorted(
        required_compliance_files - REQUIRED_RELEASE_FILES
    )
    if missing_compliance_files:
        release_findings.append(
            f"formal release does not require compliance files: {missing_compliance_files}"
        )
    record("release_boundary", release_findings)

    failed = [item["name"] for item in checks if item["status"] != "passed"]
    return {
        "schema_version": 1,
        "status": "passed" if not failed else "failed",
        "manual_sha256": COMPETITION_MANUAL_SHA256,
        "formal_model": FORMAL_COMPETITION_MODEL,
        "failed_checks": failed,
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    return parser.parse_args()


def main() -> None:
    report = check_competition_compliance(parse_args().root)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if report["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
