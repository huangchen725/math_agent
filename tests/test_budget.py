import pytest

from math_agent.budget import BudgetExceeded, ExecutionBudget
from user_agent import AgentConfig, ReasoningAgent


class TextClient:
    def __init__(self):
        self.calls = 0

    def chat(self, **kwargs):
        self.calls += 1
        system = kwargs["messages"][0].get("content", "")
        if "验证器" in system:
            return "VERDICT: A"
        return "推理\n最终答案：2"

    @staticmethod
    def get_last_response_meta():
        return {
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            }
        }


def test_execution_budget_enforces_request_and_tool_limits():
    budget = ExecutionBudget(
        max_model_requests=1,
        max_total_tokens=100,
        max_tool_calls=1,
        timeout_seconds=10,
    )
    budget.consume_model_request()
    budget.consume_tool_call()

    with pytest.raises(BudgetExceeded, match="model request"):
        budget.consume_model_request()
    with pytest.raises(BudgetExceeded, match="tool call"):
        budget.consume_tool_call()


def test_execution_budget_records_truncated_responses():
    budget = ExecutionBudget(timeout_seconds=10)

    budget.record_response_meta({"finish_reason": "length", "usage": {}})
    budget.record_response_meta({"finish_reason": "stop", "usage": {}})

    assert budget.snapshot()["truncated_responses"] == 1


def test_agent_records_per_problem_budget_usage():
    client = TextClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=1,
        enable_critic=False,
        max_model_requests=2,
    )
    result = ReasoningAgent(client, config).solve("1+1", {})

    assert result["final_response"].endswith("最终答案：2")
    summary = result["trace"][-1]
    assert summary["step"] == "budget_summary"
    assert summary["content"]["model_requests"] == 2
    assert summary["content"]["total_tokens"] == 30


def test_agent_stops_before_exceeding_model_request_budget():
    client = TextClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=2,
        enable_critic=False,
        max_model_requests=1,
    )
    result = ReasoningAgent(client, config).solve("1+1", {})

    assert result["final_response"] == "未解出"
    assert client.calls == 1
    assert any(item["step"] == "budget_exceeded" for item in result["trace"])


def test_agent_rejects_oversized_problem_without_calling_model():
    client = TextClient()
    config = AgentConfig(max_problem_chars=5)
    result = ReasoningAgent(client, config).solve("x" * 6, {})

    assert result["final_response"] == "未解出"
    assert result["trace"][0]["step"] == "input_error"
    assert client.calls == 0


def test_agent_rejects_invalid_or_oversized_metadata_without_calling_model():
    client = TextClient()
    agent = ReasoningAgent(client, AgentConfig(max_metadata_chars=10))

    invalid = agent.solve("1+1", {"bad": object()})
    oversized = agent.solve("1+1", {"x": "0123456789"})

    assert invalid["final_response"] == "未解出"
    assert oversized["final_response"] == "未解出"
    assert client.calls == 0
