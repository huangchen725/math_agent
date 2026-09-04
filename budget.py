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
    max_total_tokens: int = 200_000
    max_tool_calls: int = 48
    timeout_seconds: float = 600.0
    started_at: float = field(default_factory=time.monotonic)
    model_requests: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tool_calls: int = 0

    def __post_init__(self) -> None:
        for name in ("max_model_requests", "max_total_tokens", "max_tool_calls"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def elapsed_seconds(self) -> float:
        return max(0.0, time.monotonic() - self.started_at)

    def check_deadline(self) -> None:
        if self.elapsed_seconds() >= self.timeout_seconds:
            raise BudgetExceeded(
                f"problem deadline exceeded ({self.timeout_seconds:g} seconds)"
            )

    def consume_model_request(self) -> None:
        self.check_deadline()
        if self.model_requests >= self.max_model_requests:
            raise BudgetExceeded(
                f"model request budget exceeded ({self.max_model_requests})"
            )
        if self.total_tokens >= self.max_total_tokens:
            raise BudgetExceeded(f"token budget exceeded ({self.max_total_tokens})")
        self.model_requests += 1

    def consume_tool_call(self) -> None:
        self.check_deadline()
        if self.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool call budget exceeded ({self.max_tool_calls})")
        self.tool_calls += 1

    def record_response_meta(self, metadata: Mapping[str, Any] | None) -> None:
        if not metadata:
            return
        usage = metadata.get("usage")
        if not isinstance(usage, Mapping):
            return
        prompt = _nonnegative_int(usage.get("prompt_tokens"))
        completion = _nonnegative_int(usage.get("completion_tokens"))
        total = _nonnegative_int(usage.get("total_tokens"))
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total or prompt + completion

    def snapshot(self) -> dict[str, Any]:
        return {
            "model_requests": self.model_requests,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tool_calls": self.tool_calls,
            "elapsed_ms": round(self.elapsed_seconds() * 1000),
            "limits": {
                "model_requests": self.max_model_requests,
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

