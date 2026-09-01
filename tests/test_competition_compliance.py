import json
from pathlib import Path

from math_agent.competition_policy import (
    FORMAL_COMPETITION_MODEL,
    OFFICIAL_API_BASE,
    competition_mode_enabled,
    validate_official_api_base,
    validate_runtime_model,
)
from scripts.check_competition_compliance import check_competition_compliance
from math_agent.trace_sanitizer import sanitize_trace


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


def test_public_trace_projection_is_idempotent_json_safe_and_secret_free() -> None:
    secrets = (
        "PRIVATE HIDDEN PROBLEM 7F2A",
        "PRIVATE MODEL RESPONSE 8C3B",
        "最终答案：SECRET_ANSWER_9D4C",
    )
    raw_trace = [
        {"step": "policy_plain_7", "content": secrets[1]},
        {
            "step": "task_route",
            "content": {
                "task_types": ["calculation"],
                "confidence": 0.8,
                "reason": "strict_direct_pattern",
                "raw_prompt": secrets[0],
            },
        },
        {
            "step": "budget_summary",
            "content": {
                "model_requests": 2,
                "requests_by_stage": {"policy_plain": 1, "verifier": 1},
                "final_answer_source": "policy_plain",
                "private": secrets[2],
            },
        },
        {
            "step": "global_error",
            "content": {
                "error_type": "PrivateHiddenProblem7F2A",
                "source": "deterministic:private_answer_9d4c",
            },
        },
        {"step": secrets[0], "content": {"status": "completed"}},
    ]

    projected = sanitize_trace(raw_trace)
    serialized = json.dumps(projected, ensure_ascii=False)

    assert sanitize_trace(projected) == projected
    assert all(secret not in serialized for secret in secrets)
    assert projected[1]["content"]["task_types"] == ["calculation"]
    assert projected[2]["content"]["model_requests"] == 2
    assert projected[3]["content"] == {"status": "error"}
    assert projected[4]["step"] == "unrecognized_event"
