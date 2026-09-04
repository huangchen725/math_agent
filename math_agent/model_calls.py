"""Small explicit adapters around :class:`ModelGateway`."""

from __future__ import annotations

from typing import Any

from .agent_types import ModelCallResult
from .context import SolveContext


def call_model_result(
    context: SolveContext,
    system_prompt: str,
    user_content: str,
    *,
    stage: str,
    candidate_id: int | None = None,
    recovery: bool = False,
    **kwargs: Any,
) -> ModelCallResult:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_content})
    return context.gateway.chat(
        messages,
        stage=stage,
        candidate_id=candidate_id,
        recovery=recovery,
        **kwargs,
    )


def call_model_text(
    context: SolveContext,
    system_prompt: str,
    user_content: str,
    **kwargs: Any,
) -> str:
    stage = str(kwargs.pop("stage", "unknown"))
    candidate_id = kwargs.pop("candidate_id", None)
    recovery = bool(kwargs.pop("recovery", False))
    return call_model_result(
        context,
        system_prompt,
        user_content,
        stage=stage,
        candidate_id=candidate_id,
        recovery=recovery,
        **kwargs,
    ).text
