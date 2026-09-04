"""Explicit state passed through one problem-solving run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .budget import ExecutionBudget
from .model_gateway import ModelGateway


@dataclass
class SolveContext:
    """All mutable state owned by one ``ReasoningAgent.solve`` invocation."""

    problem: str
    metadata: dict[str, Any]
    trace: list[dict[str, Any]]
    budget: ExecutionBudget
    gateway: ModelGateway
