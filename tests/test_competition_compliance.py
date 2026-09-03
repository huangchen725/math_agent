import json
from pathlib import Path

from competition_policy import (
    FORMAL_COMPETITION_MODEL,
    FORMAL_COMPETITION_MODELS,
    OFFICIAL_BASELINE_COMMIT,
    OFFICIAL_EVIDENCE_VERIFIED_ON,
    OFFICIAL_EVIDENCE_URLS,
    OFFICIAL_MATERIAL_SHA256,
    OFFICIAL_WEB_EVIDENCE_VERIFIED_ON,
    OFFICIAL_API_BASE,
    competition_mode_enabled,
    validate_official_api_base,
    validate_runtime_model,
)
from scripts.check_competition_compliance import (
    _check_runtime_network_boundary,
    check_competition_compliance,
)
from trace_sanitizer import sanitize_trace


ROOT = Path(__file__).resolve().parents[1]


def test_complete_offline_competition_compliance_probe_passes() -> None:
    report = check_competition_compliance(ROOT)

    assert report["status"] == "passed"
    assert report["formal_model"] == "intern-s1"
    assert report["official_materials_sha256"] == dict(OFFICIAL_MATERIAL_SHA256)
    assert report["official_baseline_commit"] == OFFICIAL_BASELINE_COMMIT
    assert report["official_evidence_urls"] == dict(OFFICIAL_EVIDENCE_URLS)
    assert report["official_evidence_verified_on"] == dict(
        OFFICIAL_EVIDENCE_VERIFIED_ON
    )
    assert report["official_web_evidence_verified_on"] == OFFICIAL_WEB_EVIDENCE_VERIFIED_ON
    assert report["formal_models"] == sorted(FORMAL_COMPETITION_MODELS)
    assert report["failed_checks"] == []


def test_competition_policy_fails_closed() -> None:
    assert competition_mode_enabled({}) is True
    assert competition_mode_enabled({"COMPETITION_MODE": "0"}) is False
    assert validate_official_api_base(OFFICIAL_API_BASE + "/") == OFFICIAL_API_BASE
    assert validate_runtime_model(
        FORMAL_COMPETITION_MODEL,
        competition_mode=True,
    ) == FORMAL_COMPETITION_MODEL
    assert validate_runtime_model(
        "intern-s2-preview",
        competition_mode=True,
    ) == "intern-s2-preview"


def test_runtime_network_scan_allows_only_registered_evidence_urls(
    tmp_path: Path,
) -> None:
    package = tmp_path / "math_agent"
    package.mkdir()
    registered_url = next(iter(OFFICIAL_EVIDENCE_URLS.values()))
    (package / "competition_policy.py").write_text(
        f'EVIDENCE_URL = "{registered_url}"\n',
        encoding="utf-8",
    )

    assert _check_runtime_network_boundary(tmp_path) == []

    (tmp_path / "main.py").write_text(
        'UNAUTHORIZED_URL = "https://example.invalid/solver"\n',
        encoding="utf-8",
    )
    assert _check_runtime_network_boundary(tmp_path) == [
        "main.py: non-official runtime URL"
    ]


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
