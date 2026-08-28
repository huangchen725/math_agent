import json
import os
import time
from contextvars import ContextVar
from typing import Any, Dict, List, Mapping, Optional, Union

import requests


DEFAULT_API_BASE = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
DEFAULT_MODEL = "intern-s2-preview"
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4096

ChatMessage = Dict[str, Any]
ChatResponse = Union[str, ChatMessage]
_LAST_RESPONSE_META: ContextVar[Dict[str, Any]] = ContextVar(
    "last_intern_response_meta",
    default={},
)


class InternChatClient:
    """Small OpenAI-compatible chat client for the competition sample."""

    def __init__(
        self,
        timeout: int = 120,
        retry: int = 3,
        default_args: Optional[Mapping[str, Any]] = None,
        **request_args: Any,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if retry <= 0:
            raise ValueError("retry must be positive")
        raw_api_key = (os.environ.get("INTERN_API_KEY") or "").strip()
        if not raw_api_key:
            raise RuntimeError("Missing API key. Set INTERN_API_KEY.")
        self.authorization = (
            raw_api_key if raw_api_key.startswith("Bearer ") else f"Bearer {raw_api_key}"
        )
        self.api_base = os.environ.get("INTERN_API_BASE", DEFAULT_API_BASE)
        self.model = os.environ.get("INTERN_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.retry = retry
        self.default_args = dict(default_args or {})
        self.default_args.update(request_args)

    def chat(
        self,
        messages: List[ChatMessage],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        *,
        thinking_mode: Optional[bool] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **request_args: Any,
    ) -> ChatResponse:
        """Create a chat completion.

        Extra request arguments are passed through to the HTTP API. Arguments
        supplied to ``chat`` override client-wide ``default_args``.

        Text completions are returned as strings for backwards compatibility.
        When the model requests a tool call, the complete assistant message is
        returned so that callers can read ``tool_calls`` and append the message
        to the next request.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
        }
        payload.update(self.default_args)
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if thinking_mode is not None:
            payload["thinking_mode"] = thinking_mode
        if tools is not None:
            payload["tools"] = tools
        payload.update(request_args)
        payload["messages"] = messages
        if payload.get("stream"):
            raise ValueError("stream=True is not supported by the competition endpoint")
        if payload.get("n", 1) != 1:
            raise ValueError("n must be 1 for the competition endpoint")

        headers = {
            "Content-Type": "application/json",
            "Authorization": self.authorization,
        }

        last_error = None
        request_started = time.monotonic()
        for attempt in range(self.retry):
            try:
                response = requests.post(
                    self.api_base,
                    headers=headers,
                    data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                message = data["choices"][0]["message"]
                usage = data.get("usage")
                _LAST_RESPONSE_META.set({
                    "id": data.get("id"),
                    "model": data.get("model", self.model),
                    "usage": usage if isinstance(usage, dict) else {},
                    "elapsed_ms": round((time.monotonic() - request_started) * 1000),
                    "attempts": attempt + 1,
                })
                if message.get("tool_calls"):
                    return message
                return message["content"]
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retry and self._is_retryable(exc):
                    time.sleep(2**attempt)
                else:
                    break

        raise RuntimeError(f"Chat completion failed: {last_error}") from last_error

    @staticmethod
    def get_last_response_meta() -> Dict[str, Any]:
        """Return response metadata for the current thread/context without secrets."""
        return dict(_LAST_RESPONSE_META.get())

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            status = exc.response.status_code
            return status in {408, 409, 425, 429} or status >= 500
        return False
