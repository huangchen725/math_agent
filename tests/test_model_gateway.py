import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from budget import ExecutionBudget
from llm_client import InternChatClient
from model_gateway import ModelGateway


class AtomicClient(InternChatClient):
    def __init__(self) -> None:
        pass

    def chat(self, **kwargs):
        response, _ = self.chat_with_metadata(**kwargs)
        return response

    def chat_with_metadata(self, **kwargs):
        content = kwargs["messages"][-1]["content"]
        return f"reply:{content}", {
            "finish_reason": "length" if content == "A" else "stop",
            "usage": {"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        }


def test_gateway_binds_metadata_and_budget_to_the_same_request() -> None:
    budget = ExecutionBudget(timeout_seconds=10)
    result = ModelGateway(AtomicClient(), budget).chat(
        [{"role": "user", "content": "A"}],
        stage="policy_plain",
        candidate_id=7,
    )

    assert result.text == "reply:A"
    assert result.raw_response == "reply:A"
    assert result.truncated is True
    assert result.usage["total_tokens"] == 5
    assert result.request_id == 1
    snapshot = budget.snapshot()
    assert snapshot["model_requests"] == 1
    assert snapshot["total_tokens"] == 5
    assert snapshot["truncated_by_stage"] == {"policy_plain": 1}
    assert snapshot["truncation_events"][0]["candidate_id"] == 7


def test_gateway_supports_plain_chat_clients_without_metadata() -> None:
    class PlainClient:
        def chat(self, **kwargs):
            return {"content": "ok", "tool_calls": []}

    result = ModelGateway(PlainClient()).chat(
        [{"role": "user", "content": "hello"}],
        stage="policy_tool",
    )

    assert result.text == "ok"
    assert result.raw_response == {"content": "ok", "tool_calls": []}
    assert result.finish_reason == ""


def test_gateway_ignores_unadvertised_private_metadata_method() -> None:
    class OfficialLikeClient:
        def __init__(self) -> None:
            self.chat_calls = 0

        def chat(self, **kwargs):
            self.chat_calls += 1
            return "ok"

        def chat_with_metadata(self, **kwargs):
            raise AssertionError("private platform extension must not be called")

    client = OfficialLikeClient()
    result = ModelGateway(client).chat(
        [{"role": "user", "content": "hello"}],
        stage="policy_plain",
    )

    assert result.text == "ok"
    assert client.chat_calls == 1
    assert ModelGateway(client).supports_tool_calls is False


def test_gateway_never_reads_private_fields_from_an_injected_client() -> None:
    class StrictOfficialClient:
        def __init__(self) -> None:
            self.chat_calls = 0

        def chat(self, messages, temperature, max_tokens):
            self.chat_calls += 1
            return "ok"

        def __getattr__(self, name):
            if name.startswith("_"):
                raise RuntimeError("private client fields are forbidden")
            raise AttributeError(name)

    client = StrictOfficialClient()
    result = ModelGateway(client).chat(
        [{"role": "user", "content": "hello"}],
        stage="policy_plain",
        temperature=0.6,
        max_tokens=8192,
        thinking_mode=False,
        tools=[{"type": "function"}],
        tool_choice="auto",
    )

    assert result.text == "ok"
    assert client.chat_calls == 1


def test_project_client_keeps_atomic_metadata_and_extended_arguments() -> None:
    class ExtendedProjectClient(InternChatClient):
        def __init__(self) -> None:
            self.received = None

        def chat(self, **kwargs):
            return "unused"

        def chat_with_metadata(self, **kwargs):
            self.received = kwargs
            return "ok", {}

    client = ExtendedProjectClient()
    result = ModelGateway(client).chat(
        [{"role": "user", "content": "hello"}],
        stage="policy_tool",
        temperature=0.6,
        max_tokens=8192,
        thinking_mode=False,
        tools=[{"type": "function"}],
        tool_choice="auto",
    )

    assert result.text == "ok"
    assert ModelGateway(client).supports_tool_calls is True
    assert set(client.received) == {
        "messages",
        "temperature",
        "max_tokens",
        "thinking_mode",
        "tools",
        "tool_choice",
    }


@pytest.mark.parametrize("completed", ["bad", ("ok", []), ("ok", {}, "extra")])
def test_gateway_rejects_invalid_atomic_client_contract(completed) -> None:
    class InvalidClient(InternChatClient):
        def __init__(self) -> None:
            pass

        def chat(self, **kwargs):
            return "unused"

        def chat_with_metadata(self, **kwargs):
            return completed

    with pytest.raises(TypeError):
        ModelGateway(InvalidClient()).chat([], stage="test")


def test_concurrent_gateways_do_not_share_response_metadata() -> None:
    shared_client = AtomicClient()

    def run(content: str):
        budget = ExecutionBudget(timeout_seconds=10)
        if content == "A":
            time.sleep(0.01)
        result = ModelGateway(shared_client, budget).chat(
            [{"role": "user", "content": content}],
            stage="policy_plain",
        )
        return result, budget.snapshot()

    with ThreadPoolExecutor(max_workers=2) as executor:
        (result_a, snapshot_a), (result_b, snapshot_b) = executor.map(run, ["A", "B"])

    assert result_a.truncated is True
    assert result_b.truncated is False
    assert snapshot_a["truncated_responses"] == 1
    assert snapshot_b["truncated_responses"] == 0
