"""Bounded model tool-calling loop."""

from __future__ import annotations

from typing import Any

from .agent_types import ModelCallResult
from .math_parsing import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    MAX_TOOL_CALLS_PER_ROUND,
)
from .model_gateway import ModelGateway
from .tool_registry import TOOL_DEFINITIONS, execute_tool_call


def run_tool_loop(
    client,
    messages: list[dict],
    max_rounds: int = 5,
    thinking_mode: bool = True,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    tool_timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
    budget=None,
    *,
    candidate_id: int | None = None,
    final_instruction: str = "",
    return_call_result: bool = False,
):
    """Call through ``ModelGateway`` and feed back bounded tool results."""
    trace: list[dict] = []
    current_messages = list(messages)
    if isinstance(client, ModelGateway):
        gateway = client
        if budget is not None and gateway.budget is not budget:
            raise ValueError("gateway and explicit budget must reference the same object")
        tool_budget = gateway.budget if budget is None else budget
    else:
        gateway = ModelGateway(client, budget)
        tool_budget = budget

    def call_model(*, stage: str, **kwargs: Any):
        result = gateway.chat(
            stage=stage,
            candidate_id=candidate_id,
            **kwargs,
        )
        return result.raw_response, result

    def finish(text: str, result: ModelCallResult):
        if return_call_result:
            return text, trace, result
        return text, trace

    for round_id in range(max_rounds):
        response, call_result = call_model(
            stage="policy_tool",
            messages=current_messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )
        if call_result.truncated:
            trace.append({
                "step": f"tool_round_{round_id}_truncated",
                "content": {"stage": "policy_tool", "candidate_id": candidate_id},
            })
            return finish(call_result.text, call_result)
        if isinstance(response, str):
            trace.append({"step": f"tool_round_{round_id}_text", "content": response[:500]})
            return finish(response, call_result)
        if not isinstance(response, dict):
            raise TypeError(f"不支持的模型响应类型: {type(response).__name__}")

        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            content = response.get("content")
            if isinstance(content, str):
                trace.append({
                    "step": f"tool_round_{round_id}_text",
                    "content": content[:500],
                })
                return finish(content, call_result)
            raise ValueError("模型响应既没有文本，也没有 tool_calls")
        if not isinstance(tool_calls, list):
            raise TypeError("tool_calls 必须是列表")

        current_messages.append(response)
        tool_results = []
        for call_index, tool_call in enumerate(tool_calls[:MAX_TOOL_CALLS_PER_ROUND]):
            if tool_budget is not None:
                tool_budget.consume_tool_call()
            result = execute_tool_call(tool_call, timeout_seconds=tool_timeout_seconds)
            function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
            tool_name = (
                function.get("name", "<invalid>")
                if isinstance(function, dict)
                else "<invalid>"
            )
            tool_call_id = (
                tool_call.get("id", f"invalid-{round_id}-{call_index}")
                if isinstance(tool_call, dict)
                else f"invalid-{round_id}-{call_index}"
            )
            tool_results.append({"tool": tool_name, "result": result[:200]})
            current_messages.append({
                "role": "tool",
                "tool_call_id": str(tool_call_id),
                "content": result,
            })

        if len(tool_calls) > MAX_TOOL_CALLS_PER_ROUND:
            for call_index, tool_call in enumerate(
                tool_calls[MAX_TOOL_CALLS_PER_ROUND:],
                start=MAX_TOOL_CALLS_PER_ROUND,
            ):
                tool_call_id = (
                    tool_call.get("id", f"limited-{round_id}-{call_index}")
                    if isinstance(tool_call, dict)
                    else f"limited-{round_id}-{call_index}"
                )
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": str(tool_call_id),
                    "content": (
                        "ERROR: 本轮工具调用数量超过限制，"
                        f"仅执行前 {MAX_TOOL_CALLS_PER_ROUND} 个"
                    ),
                })
            tool_results.append({
                "tool": "<limit>",
                "result": f"仅执行前 {MAX_TOOL_CALLS_PER_ROUND} 个工具调用",
            })
        trace.append({"step": f"tool_round_{round_id}", "content": tool_results})

    if final_instruction:
        current_messages.append({"role": "user", "content": final_instruction})
    response, call_result = call_model(
        stage="tool_final",
        messages=current_messages,
        temperature=0.0,
        max_tokens=max_tokens,
        thinking_mode=False,
    )
    if isinstance(response, str):
        return finish(response, call_result)
    return finish(str(response.get("content", ""))[:500], call_result)
