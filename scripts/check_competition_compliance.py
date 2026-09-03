"""Run offline checks for the XH-202627 competition safety boundary."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from competition_policy import (
    COMPETITION_MANUAL_SHA256,
    FORMAL_COMPETITION_MODEL,
    FORMAL_COMPETITION_MODELS,
    OFFICIAL_BASELINE_COMMIT,
    OFFICIAL_EVIDENCE_VERIFIED_ON,
    OFFICIAL_EVIDENCE_URLS,
    OFFICIAL_MATERIAL_SHA256,
    OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
    OFFICIAL_API_BASE,
    validate_official_api_base,
)
from llm_client import DEFAULT_API_BASE, DEFAULT_MODEL

from .build_release import REQUIRED_RELEASE_FILES, _is_release_path
from .project_utils import PROJECT_ROOT


_RUNTIME_ROOT_FILES = ("main.py", "demo.py", "user_agent.py", "verify_math.py")
_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+")
_NETWORK_MODULES = frozenset(
    {"aiohttp", "httpx", "requests", "socket", "urllib.request", "websocket", "websockets"}
)
_NETWORK_IMPORT_ALLOWLIST = {"llm_client.py": frozenset({"requests"})}
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

    def chat(
        self,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> str:
        self.calls.append({
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        serialized = json.dumps(messages, ensure_ascii=False)
        if "VERDICT" in serialized:
            return "VERDICT: A\nPRIVATE_VERIFIER_RESPONSE_6A1D"
        return "最终答案：0\nPRIVATE_MODEL_RESPONSE_8C3B"


def _runtime_paths(root: Path) -> list[Path]:
    paths = set(root.glob("*.py"))
    paths.update(root / name for name in _RUNTIME_ROOT_FILES)
    return sorted(path for path in paths if path.is_file())


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
        evidence_urls = (
            frozenset(OFFICIAL_EVIDENCE_URLS.values())
            if relative == "competition_policy.py"
            else frozenset()
        )
        for match in _URL_PATTERN.finditer(text):
            url = match.group(0).rstrip(".,;)")
            if urlsplit(url).hostname != official_host and url not in evidence_urls:
                findings.append(f"{relative}: non-official runtime URL")
    return findings


def _check_answer_isolation_and_json() -> list[str]:
    from main import solve_item
    from agent import AgentConfig, ReasoningAgent

    sentinel_answer = "DO_NOT_FORWARD_REFERENCE_7F2A"
    item = {
        "idx": "compliance-probe",
        "problem": "PRIVATE_HIDDEN_PROBLEM_4E9A：计算 0+0。",
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
        tool_candidates=7,
        plain_candidates=9,
        verifier_voting_times=4,
        enable_tools=True,
        enable_critic=True,
        enable_reflection=True,
        enable_fallback=False,
        enable_deterministic_verification=True,
    )
    agent_result = ReasoningAgent(
        client,
        "opaque-platform-positional",
        config,
        config={"opaque_platform_config": True},
        platform_run_id="opaque-platform-keyword",
    ).solve(
        item["problem"],
        {
            "idx": item["idx"],
            "answer": sentinel_answer,
            "reference_solution": sentinel_answer,
        },
    )
    if sentinel_answer in json.dumps(client.calls, ensure_ascii=False):
        findings.append("reference-answer metadata reached a model request")
    if len(client.calls) != 6:
        findings.append("minimum-signature client did not receive the fixed six-call sequence")
    if any(
        set(call) != {"messages", "temperature", "max_tokens"}
        for call in client.calls
    ):
        findings.append("injected client received arguments beyond the public minimum")
    if sentinel_answer in json.dumps(agent_result, ensure_ascii=False):
        findings.append("reference-answer metadata leaked into the agent result")
    trace_text = json.dumps(agent_result.get("trace", []), ensure_ascii=False)
    for private_text in (
        item["problem"],
        "PRIVATE_MODEL_RESPONSE_8C3B",
        "PRIVATE_VERIFIER_RESPONSE_6A1D",
        "最终答案：0",
    ):
        if private_text in trace_text:
            findings.append("problem, model response, or final answer leaked into trace")
            break
    if str(agent_result.get("final_response", "")).splitlines()[-1] != "最终答案：0":
        findings.append("full Agent compliance probe broke the final-answer contract")
    return findings


def _check_isolated_entrypoint_import(root: Path) -> list[str]:
    """Mirror the judge's path-based import without inheriting the repo cwd."""
    probe = """
import importlib.util
import json
from pathlib import Path
import sys

entrypoint = Path(sys.argv[1]).resolve()
project_root = str(entrypoint.parent)
sys.path = [item for item in sys.path if item not in {"", project_root}]
spec = importlib.util.spec_from_file_location("_official_user_agent_probe", entrypoint)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to create entrypoint spec")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps({"agent": module.ReasoningAgent.__name__}))
"""
    try:
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe, str(root / "user_agent.py")],
            cwd=root.parent,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )  # nosec B603
    except (OSError, subprocess.SubprocessError):
        return ["isolated user_agent import probe could not run"]
    if completed.returncode != 0:
        return ["user_agent failed isolated path-based import"]
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError):
        return ["isolated user_agent import probe returned invalid JSON"]
    if payload != {"agent": "ReasoningAgent"}:
        return ["isolated user_agent import did not expose ReasoningAgent"]
    return []


def _check_official_material_registry(root: Path) -> list[str]:
    """Keep every evidence digest and unresolved-boundary class in the release."""
    path = root / "docs" / "OFFICIAL_MATERIALS_REGISTER.md"
    if not path.is_file():
        return ["official material registry is missing"]
    text = path.read_text(encoding="utf-8").casefold()
    findings = [
        f"official material registry omits digest: {name}"
        for name, digest in OFFICIAL_MATERIAL_SHA256.items()
        if digest.casefold() not in text
    ]
    if OFFICIAL_BASELINE_COMMIT.casefold() not in text:
        findings.append("official material registry omits the pinned baseline commit")
    for name, url in OFFICIAL_EVIDENCE_URLS.items():
        if url.casefold() not in text:
            findings.append(f"official material registry omits evidence URL: {name}")
    for name, verified_on in OFFICIAL_EVIDENCE_VERIFIED_ON.items():
        if verified_on not in text:
            findings.append(
                f"official material registry omits evidence verification date: {name}"
            )
    if OFFICIAL_WEB_EVIDENCE_VERIFIED_ON not in text:
        findings.append("official material registry omits web evidence verification date")
    for required_source in tuple(f"MAT-{index:03d}" for index in range(1, 10)):
        if required_source.casefold() not in text:
            findings.append(f"official material registry omits {required_source}")
    for required_conflict in (
        "INFO-CONFLICT-001",
        "INFO-CONFLICT-002",
        "INFO-CONFLICT-003",
        "INFO-CONFLICT-004",
        "INFO-CONFLICT-005",
        "INFO-CONFLICT-006",
        "INFO-CONFLICT-007",
        "INFO-CONFLICT-008",
        "INFO-CONFLICT-009",
    ):
        if required_conflict.casefold() not in text:
            findings.append(f"official material registry omits {required_conflict}")
    for required_gap in (
        "OFFICIAL-GAP-CLIENT",
        "OFFICIAL-GAP-RESPONSE",
        "OFFICIAL-GAP-ERROR",
        "OFFICIAL-GAP-BUDGET",
        "OFFICIAL-GAP-MODEL",
        "OFFICIAL-GAP-RESOURCE",
        "OFFICIAL-GAP-JUDGE",
        "OFFICIAL-GAP-RUNNER",
        "OFFICIAL-GAP-TOOLS",
        "OFFICIAL-GAP-CHANGE",
    ):
        if required_gap.casefold() not in text:
            findings.append(f"official material registry omits {required_gap}")
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
    if DEFAULT_MODEL != FORMAL_COMPETITION_MODEL:
        policy_findings.append("runtime default model differs from the formal default")
    if DEFAULT_MODEL not in FORMAL_COMPETITION_MODELS:
        policy_findings.append("runtime default model is outside the documented allowlist")
    if DEFAULT_API_BASE != OFFICIAL_API_BASE:
        policy_findings.append("runtime default API base differs from the official endpoint")
    try:
        validate_official_api_base(DEFAULT_API_BASE)
    except RuntimeError:
        policy_findings.append("runtime default API base failed strict validation")
    if len(COMPETITION_MANUAL_SHA256) != 64:
        policy_findings.append("competition manual digest is malformed")
    if len(OFFICIAL_MATERIAL_SHA256) != 4 or any(
        len(digest) != 64 for digest in OFFICIAL_MATERIAL_SHA256.values()
    ):
        policy_findings.append("official material digest registry is malformed")
    if not OFFICIAL_EVIDENCE_URLS or not all(
        url.startswith("https://") for url in OFFICIAL_EVIDENCE_URLS.values()
    ):
        policy_findings.append("official web evidence registry is malformed")
    if (
        set(OFFICIAL_EVIDENCE_VERIFIED_ON) != set(OFFICIAL_EVIDENCE_URLS)
        or not all(
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
            for value in OFFICIAL_EVIDENCE_VERIFIED_ON.values()
        )
        or OFFICIAL_WEB_EVIDENCE_VERIFIED_ON
        != max(OFFICIAL_EVIDENCE_VERIFIED_ON.values())
    ):
        policy_findings.append("official web evidence dates are malformed")
    if not re.fullmatch(r"[0-9a-f]{40}", OFFICIAL_BASELINE_COMMIT):
        policy_findings.append("official baseline commit is malformed")
    record("formal_policy", policy_findings)

    record("official_material_registry", _check_official_material_registry(root))
    record("runtime_network_boundary", _check_runtime_network_boundary(root))
    record("isolated_entrypoint_import", _check_isolated_entrypoint_import(root))
    record("answer_isolation_and_json", _check_answer_isolation_and_json())

    release_findings = [
        f"private artifact would enter release: {path}"
        for path in _PRIVATE_ARTIFACTS
        if _is_release_path(path)
    ]
    required_compliance_files = {
        "docs/COMPETITION_COMPLIANCE.md",
        "docs/ENGINEERING_SPECIFICATION.md",
        "docs/OFFICIAL_MATERIALS_REGISTER.md",
        "competition_policy.py",
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
        "official_materials_sha256": dict(OFFICIAL_MATERIAL_SHA256),
        "official_baseline_commit": OFFICIAL_BASELINE_COMMIT,
        "official_evidence_urls": dict(OFFICIAL_EVIDENCE_URLS),
        "official_evidence_verified_on": dict(OFFICIAL_EVIDENCE_VERIFIED_ON),
        "official_web_evidence_verified_on": OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
        "formal_model": FORMAL_COMPETITION_MODEL,
        "formal_models": sorted(FORMAL_COMPETITION_MODELS),
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
