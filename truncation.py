"""Shared bookkeeping for quarantined model responses."""

from __future__ import annotations

from agent_types import ModelCallResult
from budget import ExecutionBudget
from context import SolveContext


def mark_truncation(
    context: SolveContext,
    result: ModelCallResult,
    status: str,
    original_answer_present: bool,
) -> None:
    context.budget.mark_truncation_handled(
        result.request_id,
        status=status,
        original_answer_present=original_answer_present,
    )


def contain_pending_truncations(budget: ExecutionBudget) -> None:
    for event in budget.truncation_events:
        if event.get("recovery_status") == "pending":
            budget.mark_truncation_handled(
                event.get("request_id"),
                status="quarantined",
                original_answer_present=bool(event.get("original_answer_present")),
            )
