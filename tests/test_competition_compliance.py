from pathlib import Path

from math_agent.competition_policy import (
    FORMAL_COMPETITION_MODEL,
    OFFICIAL_API_BASE,
    competition_mode_enabled,
    validate_official_api_base,
    validate_runtime_model,
)
from scripts.check_competition_compliance import check_competition_compliance


ROOT = Path(__file__).resolve().parents[1]


def test_complete_offline_competition_compliance_probe_passes() -> None:
    report = check_competition_compliance(ROOT)

    assert report["status"] == "passed"
    assert report["formal_model"] == "intern-s1"
    assert report["failed_checks"] == []


def test_competition_policy_fails_closed() -> None:
    assert competition_mode_enabled({}) is True
    assert competition_mode_enabled({"COMPETITION_MODE": "0"}) is False
    assert validate_official_api_base(OFFICIAL_API_BASE + "/") == OFFICIAL_API_BASE
    assert validate_runtime_model(
        FORMAL_COMPETITION_MODEL,
        competition_mode=True,
    ) == FORMAL_COMPETITION_MODEL
