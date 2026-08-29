"""Per-problem execution budgets shared by model and tool calls."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping


class BudgetExceeded(RuntimeError):
    """Raised when a problem exceeds a configured hard budget."""


@dataclass
class ExecutionBudget:
    max_model_requests: int = 16
    max_recovery_requests: int = 4
    max_total_tokens: int = 200_000
    max_tool_calls: int = 48
    timeout_seconds: float = 600.0
    started_at: float = field(default_factory=time.monotonic)
    model_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0
    truncated_responses: int = 0
    recovery_requests: int = 0
    requests_by_stage: dict[str, int] = field(default_factory=dict)
    truncated_by_stage: dict[str, int] = field(default_factory=dict)
    truncation_events: list[dict[str, Any]] = field(default_factory=list)
    final_answer_source: str = ""
    truncated_fragments_in_final: int = 0
    _request_records: dict[int, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("max_model_requests", "max_total_tokens", "max_tool_calls"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.max_recovery_requests < 0:
            raise ValueError("max_recovery_requests must be non-negative")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def check_deadline(self) -> None:
        if self.elapsed_seconds() >= self.timeout_seconds:
            raise BudgetExceeded(
                f"problem deadline exceeded ({self.timeout_seconds:g} seconds)"
            )

    def consume_model_request(
        self,
        *,
        stage: str = "unknown",
        candidate_id: int | None = None,
        recovery: bool = False,
    ) -> int:
        self.check_deadline()
        normal_requests = self.model_requests - self.recovery_requests
        if recovery and self.recovery_requests >= self.max_recovery_requests:
            raise BudgetExceeded(
                f"recovery request budget exceeded ({self.max_recovery_requests})"
            )
        if not recovery and normal_requests >= self.max_model_requests:
            raise BudgetExceeded(
                f"model request budget exceeded ({self.max_model_requests})"
            )
        if self.total_tokens >= self.max_total_tokens:
            raise BudgetExceeded(f"token budget exceeded ({self.max_total_tokens})")
        self.model_requests += 1
        if recovery:
            self.recovery_requests += 1
        stage = str(stage or "unknown")[:80]
        self.requests_by_stage[stage] = self.requests_by_stage.get(stage, 0) + 1
        request_id = self.model_requests
        self._request_records[request_id] = {
            "request_id": request_id,
            "stage": stage,
            "candidate_id": candidate_id,
            "recovery": bool(recovery),
            "truncated": False,
        }
        return request_id

    def consume_tool_call(self) -> None:
        self.check_deadline()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool call budget exceeded ({self.max_tool_calls})")
        self.tool_calls += 1

    def record_response_meta(
        self,
        metadata: Mapping[str, Any] | None,
        request_id: int | None = None,
    ) -> None:
        if not metadata:
            return
        finish_reason = str(metadata.get("finish_reason", ""))
        truncated = finish_reason.casefold() in {
            "length",
            "max_tokens",
        }
        record = self._request_records.get(request_id or -1)
        if truncated:
            self.truncated_responses += 1
            stage = str(record.get("stage", "unknown")) if record else "unknown"
            self.truncated_by_stage[stage] = self.truncated_by_stage.get(stage, 0) + 1
        usage = metadata.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        prompt = _nonnegative_int(usage.get("prompt_tokens"))
        completion = _nonnegative_int(usage.get("completion_tokens"))
        total = _nonnegative_int(usage.get("total_tokens"))
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total or prompt + completion
        if record is not None:
            record.update({
                "finish_reason": finish_reason[:40],
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total or prompt + completion,
                "truncated": truncated,
            })
            if truncated:
                self.truncation_events.append({
                    "request_id": record["request_id"],
                    "stage": record["stage"],
                    "candidate_id": record["candidate_id"],
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": total or prompt + completion,
                    "recovery_status": "pending",
                    "original_answer_present": False,
                })

    def mark_truncation_handled(
        self,
        request_id: int | None,
        *,
        status: str,
        original_answer_present: bool,
    ) -> None:
        """Record how one truncated response was contained without storing its text."""
        if request_id is None:
            return
        for event in reversed(self.truncation_events):
            if event.get("request_id") == request_id:
                event["recovery_status"] = str(status)[:60]
                event["original_answer_present"] = bool(original_answer_present)
                return

    def set_final_answer_source(self, source: str) -> None:
        self.final_answer_source = str(source or "")[:80]

    def mark_truncated_fragment_in_final(self) -> None:
        self.truncated_fragments_in_final += 1

    def snapshot(self) -> dict[str, Any]:
        handled = sum(
            event.get("recovery_status") not in {"", "pending", None}
            for event in self.truncation_events
        )
        recovery_succeeded = sum(
            event.get("recovery_status") in {"recovered", "answer_salvaged"}
            for event in self.truncation_events
        )
        recovery_failed = sum(
            event.get("recovery_status") in {"quarantined", "recovery_failed"}
            for event in self.truncation_events
        )
        return {
            "model_requests": self.model_requests,
            "normal_model_requests": self.model_requests - self.recovery_requests,
            "recovery_requests": self.recovery_requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "truncated_responses": self.truncated_responses,
            "truncation_rate": (
                self.truncated_responses / self.model_requests
                if self.model_requests else 0.0
            ),
            "requests_by_stage": dict(sorted(self.requests_by_stage.items())),
            "truncated_by_stage": dict(sorted(self.truncated_by_stage.items())),
            "truncation_events": [dict(event) for event in self.truncation_events],
            "truncation_recovery": {
                "required": self.truncated_responses,
                "handled": handled,
                "succeeded": recovery_succeeded,
                "failed": recovery_failed,
            },
            "final_answer_source": self.final_answer_source,
            "truncated_fragments_in_final": self.truncated_fragments_in_final,
            "elapsed_ms": round(self.elapsed_seconds() * 1000),
            "limits": {
                "model_requests": self.max_model_requests,
                "recovery_requests": self.max_recovery_requests,
                "total_model_requests": (
                    self.max_model_requests + self.max_recovery_requests
                ),
                "total_tokens": self.max_total_tokens,
                "tool_calls": self.max_tool_calls,
                "timeout_seconds": self.timeout_seconds,
            },
        }


def _nonnegative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)
