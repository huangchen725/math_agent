"""Fail-closed projection from internal trace events to public metadata."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_EXACT_STEPS = frozenset({
    "budget_exceeded",
    "budget_summary",
    "candidate_rejected",
    "critic",
    "critic_error",
    "critic_truncated",
    "deterministic_selection",
    "domain_detect",
    "emergency_required",
    "emergency_result",
    "emergency_unavailable",
    "fallback_error",
    "fallback_result",
    "final_answer_source",
    "global_error",
    "input_error",
    "reasoning_budget",
    "reflection",
    "reflect_error",
    "select_final",
    "self_consistency",
    "task_route",
    "tool_capability_fallback",
    "truncation_recovery",
    "verifier_recovery",
})
_DYNAMIC_STEP = re.compile(
    r"(?:deterministic_verify_\d+|policy_(?:plain|tool)_\d+|"
    r"tool_(?:error|solve)_\d+|tool_round_\d+(?:_(?:text|truncated))?|"
    r"verify(?:_err)?_\d+_\d+)\Z"
)
_SAFE_STAGES = frozenset({
    "critic",
    "emergency",
    "fallback",
    "policy_plain",
    "policy_tool",
    "recovery",
    "reflection",
    "tool_final",
    "unknown",
    "verifier",
})
_SAFE_STATUSES = frozenset({
    "answer_salvaged",
    "budget_exhausted",
    "completed",
    "conflict_fallback",
    "discard",
    "error",
    "fail",
    "fallback",
    "missing_explicit_answer",
    "pending",
    "quarantined",
    "recovered",
    "recovery_failed",
    "selected",
    "success",
    "truncated_again",
    "unknown",
})
_SAFE_REASONS = frozenset({
    "empty",
    "keyword_only",
    "missing_explicit_answer",
    "no_eligible_candidate",
    "proof_blocked",
    "strict_direct_pattern",
})
_SAFE_KINDS = frozenset({
    "binomial",
    "calculation",
    "derivative",
    "equation",
    "equation_solutions",
    "expression",
    "general",
    "integral",
    "limit",
    "matrix_determinant",
    "modular_power",
    "optimization",
    "probability",
    "proof",
    "residue",
})
_SAFE_FINISH_REASONS = frozenset({
    "",
    "content_filter",
    "length",
    "max_tokens",
    "stop",
    "tool_calls",
})
_SAFE_ERROR_TYPES = frozenset({
    "AttributeError",
    "BudgetExceeded",
    "ConnectionError",
    "JSONDecodeError",
    "KeyError",
    "ModuleNotFoundError",
    "OSError",
    "RuntimeError",
    "TimeoutError",
    "TypeError",
    "ValueError",
})
_INT_KEYS = frozenset({
    "api_max_tokens",
    "candidate_id",
    "completion_tokens",
    "content_chars",
    "elapsed_ms",
    "event_count",
    "failed",
    "handled",
    "model_requests",
    "normal_model_requests",
    "prompt_tokens",
    "recovery_requests",
    "request_id",
    "required",
    "response_chars",
    "succeeded",
    "target_tokens",
    "tool_calls",
    "total_model_requests",
    "total_tokens",
    "truncated_fragments_in_final",
    "truncated_responses",
    "vote_count",
    "vote_id",
})
_FLOAT_KEYS = frozenset({"confidence", "confidence_score", "timeout_seconds", "truncation_rate"})
_BOOL_KEYS = frozenset({
    "accepted",
    "original_answer_present",
    "reasoning_included",
    "recovery_attempted",
    "response_quarantined",
    "truncated",
    "valid",
})
_LIST_INT_KEYS = frozenset({"candidate_ids"})
_LIST_ENUM_KEYS = frozenset({"evidence_sources", "task_types"})
_NESTED_KEYS = frozenset({"limits", "truncation_recovery"})
_STAGE_COUNT_KEYS = frozenset({"requests_by_stage", "truncated_by_stage"})


def sanitize_trace(trace: object) -> list[dict[str, Any]]:
    """Return an idempotent, JSON-safe trace containing metadata only.

    Unknown fields and all free-form strings fail closed.  This prevents the
    problem, prompts, model responses, candidate answers, tool payloads, and
    exception messages from crossing the competition output boundary.
    """
    if not isinstance(trace, (list, tuple)):
        return []
    sanitized: list[dict[str, Any]] = []
    for event in trace:
        if not isinstance(event, Mapping):
            sanitized.append({
                "step": "unrecognized_event",
                "content": {"status": "error"},
            })
            continue
        step = _sanitize_step(event.get("step"))
        content = _sanitize_content(step, event.get("content"))
        sanitized.append({"step": step, "content": content})
    return sanitized


def _sanitize_step(value: object) -> str:
    step = value if isinstance(value, str) else ""
    if step in _EXACT_STEPS or _DYNAMIC_STEP.fullmatch(step):
        return step
    return "unrecognized_event"


def _sanitize_content(step: str, content: object) -> dict[str, Any]:
    if step == "budget_summary" and isinstance(content, Mapping):
        return _sanitize_budget(content)

    safe: dict[str, Any] = {}
    if isinstance(content, Mapping):
        for raw_key, value in content.items():
            if not isinstance(raw_key, str):
                continue
            key = raw_key
            if key in _INT_KEYS:
                parsed = _safe_int(value)
                if parsed is not None:
                    safe[key] = parsed
            elif key in _FLOAT_KEYS:
                parsed_float = _safe_float(value)
                if parsed_float is not None:
                    safe[key] = parsed_float
            elif key in _BOOL_KEYS and isinstance(value, bool):
                safe[key] = value
            elif key == "stage":
                parsed_stage = _safe_enum(value, _SAFE_STAGES)
                if parsed_stage is not None:
                    safe[key] = parsed_stage
            elif key in {
                "status",
                "action",
                "recovery_result",
                "recovery_status",
                "result",
            }:
                parsed_status = _safe_enum(value, _SAFE_STATUSES)
                if parsed_status is not None:
                    safe[key] = parsed_status
            elif key == "reason":
                parsed_reason = _safe_enum(value, _SAFE_REASONS)
                if parsed_reason is not None:
                    safe[key] = parsed_reason
            elif key in {"kind", "deterministic_verifier"}:
                parsed_kind = _safe_enum(value, _SAFE_KINDS | {""})
                if parsed_kind is not None:
                    safe[key] = parsed_kind
            elif key == "finish_reason":
                parsed_finish = _safe_enum(value, _SAFE_FINISH_REASONS)
                if parsed_finish is not None:
                    safe[key] = parsed_finish
            elif key in {"source", "final_answer_source"}:
                parsed_source = _safe_source(value)
                if parsed_source is not None:
                    safe[key] = parsed_source
            elif key == "error_type":
                parsed_error = _safe_error_type(value)
                if parsed_error is not None:
                    safe[key] = parsed_error
            elif key in _LIST_INT_KEYS and isinstance(value, (list, tuple)):
                values = [parsed for item in value if (parsed := _safe_int(item)) is not None]
                safe[key] = values[:32]
            elif key in _LIST_ENUM_KEYS and isinstance(value, (list, tuple)):
                allowed = _SAFE_KINDS if key == "task_types" else None
                values = []
                for item in value:
                    parsed_item = (
                        _safe_enum(item, allowed)
                        if allowed is not None
                        else _safe_source(item)
                    )
                    if parsed_item is not None:
                        values.append(parsed_item)
                safe[key] = values[:32]

    if not safe:
        safe["status"] = _derived_status(step)
        if isinstance(content, (str, bytes)) and step.startswith(("policy_", "verify_", "critic", "reflection")):
            safe["response_chars"] = len(content)
        elif isinstance(content, (list, tuple)):
            safe["event_count"] = len(content)
    return safe


def _sanitize_budget(content: Mapping[str, Any]) -> dict[str, Any]:
    safe = _sanitize_content("budget_fields", {
        key: value
        for key, value in content.items()
        if key not in _NESTED_KEYS | _STAGE_COUNT_KEYS | {"truncation_events"}
    })
    for key in _STAGE_COUNT_KEYS:
        value = content.get(key)
        if isinstance(value, Mapping):
            safe[key] = {
                stage: parsed
                for raw_stage, raw_count in value.items()
                if (stage := _safe_enum(raw_stage, _SAFE_STAGES)) is not None
                and (parsed := _safe_int(raw_count)) is not None
            }
    for key in _NESTED_KEYS:
        value = content.get(key)
        if isinstance(value, Mapping):
            safe[key] = _sanitize_content(key, value)
    events = content.get("truncation_events")
    if isinstance(events, (list, tuple)):
        safe["truncation_events"] = [
            _sanitize_content("truncation_recovery", event)
            for event in events[:64]
            if isinstance(event, Mapping)
        ]
    return safe


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, value)


def _safe_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return None
    return max(0.0, parsed)


def _safe_enum(value: object, allowed: frozenset[str] | set[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _safe_source(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    if value in _SAFE_STAGES or value in {
        "emergency_truncated_answer_only",
        "plain",
        "tool",
    }:
        return value
    if value.startswith("deterministic:") and value.removeprefix("deterministic:") in _SAFE_KINDS:
        return value
    return None


def _safe_error_type(value: object) -> str | None:
    return _safe_enum(value, _SAFE_ERROR_TYPES)


def _derived_status(step: str) -> str:
    if step == "unrecognized_event" or "error" in step or step in {"global_error", "input_error"}:
        return "error"
    if "truncated" in step:
        return "quarantined"
    if step in {"select_final", "self_consistency", "deterministic_selection", "final_answer_source"}:
        return "selected"
    return "completed"


__all__ = ["sanitize_trace"]
