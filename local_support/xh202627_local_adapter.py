"""Explicit local transport: response and metadata belong to the same request.

This module stays outside the official entry import graph. No last-response
state, thread-local state, client capability probing or implicit usage getter.
"""
from typing import Any


class LocalToolAdapter:
    """包装 InternChatClient 的显式本地适配器。"""

    def __init__(self, client: Any) -> None:
        self._client = client

    def complete(self, messages, temperature, max_tokens):
        metadata = {}
        response = self._client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            meta_sink=metadata.update,
        )
        return {"response": response, "metadata": metadata}

    def complete_with_tools(self, messages, temperature, max_tokens, tools,
                        tool_choice: str = "auto"):
        """本地工具增强请求（仅在显式注入本适配器时使用）。"""
        metadata = {}
        response = self._client.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            meta_sink=metadata.update,
        )
        return {"response": response, "metadata": metadata}

    def run_tools(self, messages, temperature, max_tokens, max_rounds,
                  tool_timeout_seconds, budget):
        # Local-only import preserves the existing spawnable SymPy workers.
        from math_tools import run_tool_loop

        return run_tool_loop(
            self._client, messages, max_rounds=max_rounds,
            temperature=temperature, max_tokens=max_tokens,
            tool_timeout_seconds=tool_timeout_seconds, budget=budget,
            tool_client=self, return_metadata=True,
        )
