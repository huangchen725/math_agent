"""Regression tests for the repository hard-rule preflight."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / ".agents" / "policy_guard.py"


def _load_guard():
    spec = importlib.util.spec_from_file_location("project_policy_guard", GUARD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def test_authoritative_spec_contains_every_manifest_rule() -> None:
    manifest = guard.load_manifest()
    specification = (ROOT / manifest["authoritative_spec"]).read_text(encoding="utf-8")

    missing = [rule for rule in manifest["required_rule_ids"] if rule not in specification]

    assert missing == []


def test_every_project_skill_has_policy_overlay() -> None:
    skill_root = ROOT / ".agents" / "skills"
    skill_directories = [path.parent for path in skill_root.glob("*/SKILL.md")]

    missing = [
        str(path.relative_to(ROOT))
        for path in skill_directories
        if not (path / "PROJECT_POLICY.md").is_file()
    ]

    assert missing == []


def test_upstream_skill_files_match_recorded_current_hashes() -> None:
    skill_root = ROOT / ".agents" / "skills" / "property-based-testing"
    upstream = json.loads((skill_root / "UPSTREAM.json").read_text(encoding="utf-8"))
    modified = {item["path"]: item for item in upstream["local_modifications"]}

    for relative_path, item in modified.items():
        assert upstream["files"][relative_path] == item["upstream_sha256"]

    mismatches = []
    for relative_path, expected_digest in upstream["files"].items():
        if relative_path in modified:
            expected_digest = modified[relative_path]["current_sha256"]
        actual_digest = hashlib.sha256((skill_root / relative_path).read_bytes()).hexdigest()
        if actual_digest != expected_digest:
            mismatches.append(relative_path)

    assert mismatches == []


def test_r1_preflight_allows_planned_runtime_change() -> None:
    manifest = guard.load_manifest()

    triggers, blockers = guard.evaluate(["user_agent.py"], manifest, planned=True)

    assert "ANCHOR-001" in triggers["user_agent.py"]
    assert manifest["phase"] == "R1"
    assert blockers == []


def test_r1_changed_runtime_is_scanned_for_client_contract() -> None:
    manifest = guard.load_manifest()

    triggers, blockers = guard.evaluate(["user_agent.py"], manifest, planned=False)

    assert "CLIENT-001" in triggers["user_agent.py"]
    rules = {finding.rule for finding in blockers}
    assert "DOC-001" in rules
    assert "ANCHOR-001" not in rules


def test_document_only_preflight_is_allowed() -> None:
    manifest = guard.load_manifest()

    triggers, blockers = guard.evaluate(["README.md"], manifest, planned=True)

    assert triggers["README.md"] == {
        "DOC-001",
        "EVIDENCE-001",
        "POLICY-001",
        "SKILL-001",
        "WORK-001",
        "WORK-002",
        "WORK-003",
    }
    assert blockers == []


def test_external_action_triggers_rules_without_a_file_change() -> None:
    manifest = guard.load_manifest()

    triggers, blockers = guard.evaluate([], manifest, planned=True, actions=["real-api", "push"])

    assert "API-AUTH-001" in triggers["action:real-api"]
    assert "SUBMIT-001" in triggers["action:push"]
    assert {"WORK-001", "WORK-002", "WORK-003"}.issubset(triggers["action:push"])
    assert blockers == []


def test_formal_scan_blocks_private_client_and_type_identity() -> None:
    manifest = guard.load_manifest()
    source = """
def call(client):
    if isinstance(client, InternChatClient):
        return client.chat_with_metadata(messages=[], temperature=0, max_tokens=1)
"""

    blockers = guard.scan_python_text("xh202627_gateway.py", source, manifest)

    rules = {finding.rule for finding in blockers}
    assert "IMPORT-002" in rules
    assert "CLIENT-002" in rules


def test_formal_scan_blocks_extra_or_dynamic_chat_arguments() -> None:
    manifest = guard.load_manifest()
    source = """
def call(client, options):
    client.chat(messages=[], temperature=0, max_tokens=1, thinking_mode=True)
    client.chat(messages=[], temperature=0, max_tokens=1, **options)
"""

    blockers = guard.scan_python_text("xh202627_gateway.py", source, manifest)

    client_findings = [finding for finding in blockers if finding.rule == "CLIENT-001"]
    assert len(client_findings) == 2


def test_entrypoint_must_physically_declare_reasoning_agent() -> None:
    manifest = guard.load_manifest()

    blockers = guard.scan_python_text("user_agent.py", "class Other: pass\n", manifest)

    assert "ENTRY-001" in {finding.rule for finding in blockers}


def test_anchor_canary_matches_last_scored_runtime() -> None:
    manifest = guard.load_manifest()

    assert guard._anchor_canary(manifest) == []
