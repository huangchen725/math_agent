import hashlib
import json
from pathlib import Path

from scripts.build_release import _is_release_path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / ".agents" / "skills" / "property-based-testing"
EXPECTED_COMMIT = "6feac677af72e52ef4d279412276b5a6f21366f0"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_property_based_testing_skill_matches_pinned_upstream() -> None:
    manifest = json.loads((SKILL_ROOT / "UPSTREAM.json").read_text(encoding="utf-8"))
    recorded = manifest["files"]
    actual = {
        path.relative_to(SKILL_ROOT).as_posix()
        for path in SKILL_ROOT.rglob("*")
        if path.is_file() and path.name != "UPSTREAM.json"
    }

    assert manifest["source_commit"] == EXPECTED_COMMIT
    assert manifest["license"] == "CC-BY-SA-4.0"
    assert actual == set(recorded)
    for relative, expected_hash in recorded.items():
        assert _sha256(SKILL_ROOT / relative) == expected_hash


def test_property_based_testing_skill_is_development_only() -> None:
    skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    notices = (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    assert "name: property-based-testing" in skill
    assert not (SKILL_ROOT / "scripts").exists()
    assert EXPECTED_COMMIT in notices
    assert not _is_release_path(
        ".agents/skills/property-based-testing/SKILL.md"
    )


def test_property_based_testing_skill_has_project_routing_and_rules() -> None:
    for relative in (
        "AGENTS.md",
        "CONTRIBUTING.md",
        ".agents/skills/math-agent-maintainer/SKILL.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert ".agents/skills/property-based-testing/SKILL.md" in text, relative

    specification = (
        ROOT / "docs" / "ENGINEERING_SPECIFICATION.md"
    ).read_text(encoding="utf-8")
    assert "**QUAL-005**" in specification
    assert "property-based-testing" in specification
