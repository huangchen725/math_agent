from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from math_agent.budget import BudgetExceeded, ExecutionBudget
from user_agent import AgentConfig, ReasoningAgent


class SequenceClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, **kwargs):
        response, _ = self.chat_with_metadata(**kwargs)
        return response

    def chat_with_metadata(self, **kwargs):
        self.calls.append(kwargs)
        text, finish_reason = self.responses.pop(0)
        metadata = {
            "finish_reason": finish_reason,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        return text, metadata


def config(**overrides):
    values = {
        "tool_candidates": 0,
        "plain_candidates": 1,
        "verifier_voting_times": 0,
        "enable_critic": False,
    }
    values.update(overrides)
    return AgentConfig(**values)


def budget_summary(result):
    return next(
        event["content"]
        for event in reversed(result["trace"])
        if event["step"] == "budget_summary"
    )


def assert_valid_final_response(response: str):
    lines = [line for line in response.splitlines() if line.strip()]
    assert response.count("最终答案：") == 1
    assert lines[-1].startswith("最终答案：")
    assert lines[-1] != "最终答案："


def test_plain_truncation_is_recovered_without_leaking_partial_reasoning():
    client = SequenceClient([
        ("最终答案：999\n残缺推理不应出现", "length"),
        ("最终答案：2\n独立核验：1+1=2。", "stop"),
    ])

    result = ReasoningAgent(client, config()).solve("计算 1+1", {})

    assert result["final_response"].endswith("最终答案：2")
    assert "残缺推理" not in result["final_response"]
    assert_valid_final_response(result["final_response"])
    summary = budget_summary(result)
    assert summary["model_requests"] == 2
    assert summary["recovery_requests"] == 1
    assert summary["truncation_recovery"]["handled"] == 1
    assert summary["truncation_recovery"]["succeeded"] == 1
    assert summary["final_answer_source"] == "recovery"


def test_reasoning_targets_are_adaptive_but_api_cap_stays_8192():
    calculation_client = SequenceClient([("最终答案：2", "stop")])
    proof_client = SequenceClient([("最终答案：1", "stop")])

    ReasoningAgent(calculation_client, config()).solve("计算 1+1", {})
    ReasoningAgent(proof_client, config()).solve("证明这个恒等式成立", {})

    assert "1800 输出 token" in calculation_client.calls[0]["messages"][-1]["content"]
    assert "3500 输出 token" in proof_client.calls[0]["messages"][-1]["content"]
    assert calculation_client.calls[0]["max_tokens"] == 8192
    assert proof_client.calls[0]["max_tokens"] == 8192


def test_truncated_recovery_is_quarantined_and_emergency_answer_is_used():
    client = SequenceClient([
        ("最终答案：3\n原始残句", "length"),
        ("最终答案：2\n恢复残句", "length"),
        ("最终答案：2", "stop"),
    ])

    result = ReasoningAgent(client, config()).solve("计算 1+1", {})

    assert result["final_response"] == "最终答案：2"
    assert "残句" not in result["final_response"]
    summary = budget_summary(result)
    assert summary["truncated_responses"] == 2
    assert summary["truncation_recovery"]["handled"] == 2
    assert summary["truncated_fragments_in_final"] == 0
    assert summary["final_answer_source"] == "emergency"


def test_three_truncated_candidates_share_three_recoveries_and_reserve_emergency():
    responses = []
    for value in ("1", "2", "3"):
        responses.extend([
            (f"最终答案：{value}\n原始残句{value}", "length"),
            (f"最终答案：{value}\n恢复残句{value}", "length"),
        ])
    responses.append(("最终答案：2", "stop"))
    client = SequenceClient(responses)

    result = ReasoningAgent(
        client,
        config(plain_candidates=3, max_recovery_requests=4),
    ).solve("求解一个需要分类讨论的方程", {})

    assert result["final_response"] == "最终答案：2"
    summary = budget_summary(result)
    assert summary["model_requests"] == 7
    assert summary["recovery_requests"] == 4
    assert summary["truncated_responses"] == 6
    assert summary["truncation_recovery"]["handled"] == 6
    assert_valid_final_response(result["final_response"])


def test_emergency_truncation_salvages_only_first_line_answer():
    client = SequenceClient([
        ("没有显式答案", "stop"),
        ("最终答案：2\n紧急残句", "length"),
    ])

    result = ReasoningAgent(client, config()).solve("计算 1+1", {})

    assert result["final_response"] == "最终答案：2"
    summary = budget_summary(result)
    assert summary["truncation_events"][0]["recovery_status"] == "answer_salvaged"
    assert summary["final_answer_source"] == "emergency_truncated_answer_only"


def test_tool_candidate_truncation_uses_same_recovery_state_machine():
    client = SequenceClient([
        ("最终答案：3\n工具候选残句", "length"),
        ("最终答案：2\n短核验", "stop"),
    ])
    agent_config = config(tool_candidates=1, plain_candidates=0, enable_tools=True)

    result = ReasoningAgent(client, agent_config).solve("计算 1+1", {})

    assert result["final_response"].endswith("最终答案：2")
    summary = budget_summary(result)
    assert summary["truncated_by_stage"] == {"policy_tool": 1}


def test_verifier_truncation_retries_once_and_keeps_unknown_neutral():
    client = SequenceClient([
        ("最终答案：2\n推理", "stop"),
        ("VER", "length"),
        ("仍无法给出判定", "stop"),
    ])
    agent_config = config(verifier_voting_times=1)

    result = ReasoningAgent(client, agent_config).solve("计算 1+1", {})

    assert result["final_response"].endswith("最终答案：2")
    assert any(
        event["step"] == "verifier_recovery"
        and event["content"]["result"] == "unknown"
        for event in result["trace"]
    )
    summary = budget_summary(result)
    assert summary["truncation_recovery"]["handled"] == 1


def test_critic_truncation_is_discarded_without_reflection():
    client = SequenceClient([
        ("最终答案：2\n推理", "stop"),
        ("VERDICT: B", "stop"),
        ("这里可能有", "length"),
    ])
    agent_config = config(verifier_voting_times=1, enable_critic=True, enable_reflection=True)

    result = ReasoningAgent(client, agent_config).solve("计算 1+1", {})

    assert len(client.calls) == 3
    assert any(event["step"] == "critic_truncated" for event in result["trace"])
    assert not any(event["step"] == "reflection" for event in result["trace"])


def test_reflection_truncation_is_recovered_before_aggregation():
    client = SequenceClient([
        ("最终答案：1\n旧推理", "stop"),
        ("VERDICT: B", "stop"),
        ("首个错误在计算；应得到 2。", "stop"),
        ("最终答案：9\n反思残句", "length"),
        ("最终答案：2\n修正推理", "stop"),
        ("VERDICT: A", "stop"),
    ])
    agent_config = config(verifier_voting_times=1, enable_critic=True, enable_reflection=True)

    result = ReasoningAgent(client, agent_config).solve("计算 1+1", {})

    assert result["final_response"].endswith("最终答案：2")
    assert "反思残句" not in result["final_response"]
    assert budget_summary(result)["truncated_by_stage"] == {"reflection": 1}


def test_recovery_requests_obey_their_own_limit_and_shared_token_budget():
    budget = ExecutionBudget(
        max_model_requests=1,
        max_recovery_requests=1,
        max_total_tokens=20,
        timeout_seconds=10,
    )
    normal_id = budget.consume_model_request(stage="policy_plain")
    budget.record_response_meta(
        {"finish_reason": "length", "usage": {"total_tokens": 10}},
        normal_id,
    )
    recovery_id = budget.consume_model_request(stage="recovery", recovery=True)
    budget.record_response_meta(
        {"finish_reason": "stop", "usage": {"total_tokens": 10}},
        recovery_id,
    )

    with pytest.raises(BudgetExceeded, match="recovery request"):
        budget.consume_model_request(stage="emergency", recovery=True)
    with pytest.raises(BudgetExceeded, match="model request|token budget"):
        budget.consume_model_request(stage="verifier")


class ConcurrentClient:
    def chat(self, **kwargs):
        response, _ = self.chat_with_metadata(**kwargs)
        return response

    def chat_with_metadata(self, **kwargs):
        content = kwargs["messages"][-1]["content"]
        if "题A" in content and "上一次解答被截断" not in content and "截断回复" not in content:
            finish_reason = "length"
            text = "最终答案：1\n题A残句"
            time.sleep(0.02)
        elif "题A" in content:
            finish_reason = "stop"
            text = "最终答案：1\n题A恢复"
        else:
            finish_reason = "stop"
            text = "最终答案：2\n题B完整"
            time.sleep(0.01)
        return text, {"finish_reason": finish_reason, "usage": {"total_tokens": 5}}


def test_concurrent_solves_on_same_agent_do_not_cross_contaminate():
    shared_client = ConcurrentClient()
    shared_agent = ReasoningAgent(shared_client, config())

    def run(problem):
        return shared_agent.solve(problem, {})

    with ThreadPoolExecutor(max_workers=2) as executor:
        result_a, result_b = list(executor.map(run, ["题A：计算", "题B：计算"]))

    assert budget_summary(result_a)["truncated_responses"] == 1
    assert budget_summary(result_b)["truncated_responses"] == 0
    assert result_a["final_response"].endswith("最终答案：1")
    assert result_b["final_response"].endswith("最终答案：2")
