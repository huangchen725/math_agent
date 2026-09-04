"""One explicit gateway for model calls, metadata, and per-problem budgets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .agent_types import ModelCallResult
from .budget import ExecutionBudget


class ModelGateway:
    """Bind an injected client to one optional per-problem execution budget."""

    def __init__(self, client: Any, budget: ExecutionBudget | None = None) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("client must provide a callable chat method")
        self.client = client
        self.budget = budget

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        stage: str,
        candidate_id: int | None = None,
        recovery: bool = False,
        **kwargs: Any,
    ) -> ModelCallResult:
        """Perform one request and atomically bind its response metadata."""
        request_id = None
        if self.budget is not None:
            request_id = self.budget.consume_model_request(
                stage=stage,
                candidate_id=candidate_id,
                recovery=recovery,
            )

        raw_response, metadata = self._invoke(messages, **kwargs)
        if self.budget is not None:
            self.budget.record_response_meta(metadata, request_id)

        if isinstance(raw_response, str):
            text = raw_response
        elif isinstance(raw_response, Mapping):
            text = str(raw_response.get("content", ""))
        else:
            raise TypeError(
                f"unsupported model response type: {type(raw_response).__name__}"
            )

        usage = metadata.get("usage")
        return ModelCallResult(
            text=text,
            stage=stage,
            finish_reason=str(metadata.get("finish_reason", "")),
            usage=usage if isinstance(usage, Mapping) else {},
            candidate_id=candidate_id,
            request_id=request_id,
            raw_response=raw_response,
        )

    def _invoke(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> tuple[Any, Mapping[str, Any]]:
        chat_with_metadata = getattr(self.client, "chat_with_metadata", None)
        if callable(chat_with_metadata):
            completed = chat_with_metadata(messages=messages, **kwargs)
            if not isinstance(completed, tuple) or len(completed) != 2:
                raise TypeError("chat_with_metadata must return (response, metadata)")
            response, metadata = completed
            if metadata is None:
                return response, {}
            if not isinstance(metadata, Mapping):
                raise TypeError("chat_with_metadata metadata must be a mapping")
            return response, metadata
        return self.client.chat(messages=messages, **kwargs), {}
