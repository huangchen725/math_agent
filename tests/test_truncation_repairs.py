"""Fixed incident counterexamples and bounded preservation invariants; no network."""
import pytest

import user_agent as runtime
from user_agent import AgentConfig, Q1Policy, ReasoningAgent


class SequenceClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        self.calls.append(max_tokens)
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.mark.parametrize("limit", [1, 2])
@pytest.mark.parametrize("tools", [False, True])
@pytest.mark.parametrize("answer", ["2", "-7/3", r"\sqrt{2}"])
def test_generation_budget_preserves_completed_candidates(limit, tools, answer):
    client = SequenceClient(["最终答案：" + answer] * 3)
    config = AgentConfig(tool_candidates=3 if tools else 0,
                         plain_candidates=0 if tools else 3, max_model_requests=limit)
    result = ReasoningAgent(client, config).solve("synthetic independent problem", {})
    assert result["final_response"] != "未解出"
    assert ReasoningAgent._extract_answer(result["final_response"]) == answer
    assert len(client.calls) == limit
    assert any(t["step"] == "generation_budget_exhausted" for t in result["trace"])


@pytest.mark.parametrize("tools", [False, True])
def test_generation_deadline_preserves_completed_candidate(monkeypatch, tools):
    clock = [0.0]
    monkeypatch.setattr(runtime.ExecutionBudget, "elapsed_seconds", lambda self: clock[0])

    class SlowClient:
        def chat(self, *, messages, temperature, max_tokens, **kwargs):
            clock[0] = 601.0
            return "最终答案：2"

    result = ReasoningAgent(SlowClient(), AgentConfig(
        tool_candidates=2 if tools else 0, plain_candidates=0 if tools else 2)).solve("计算1+1", {})
    assert result["final_response"] == "最终答案：2"


@pytest.mark.parametrize("residue", ["推导还未完成", "", "最终答案：", r"\boxed{2",
    {"content": "最终答案：999", "finish_reason": "length"}])
def test_budget_recovery_never_revives_invalid_candidates(residue):
    client = SequenceClient([residue])
    result = ReasoningAgent(client, AgentConfig(max_model_requests=1)).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert len(client.calls) == 1


@pytest.mark.parametrize("text", ["思考中，尚未给出结论", "", "VERDICT:", "not VERDICT: A",
    "VERDICT: A because", "VERDICT: A\nVERDICT: B", "probably CORRECT"])
@pytest.mark.parametrize("calibrated", [False, True])
def test_unknown_verification_never_votes_or_triggers_critic(text, calibrated):
    client = SequenceClient(["最终答案：2", text])
    agent = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1),
                           local_policy=Q1Policy(calibrated_verifier=calibrated))
    result = agent.solve("计算1+1", {})
    assert result["final_response"] == "最终答案：2"
    assert len(client.calls) == 2
    assert any(t["step"] == "verify_unknown_0_0" for t in result["trace"])
    assert not any(t["step"] in ("critic", "reflection") for t in result["trace"])


@pytest.mark.parametrize("response_reason", ["length", "content_filter", "tool_calls"])
@pytest.mark.parametrize("metadata_reason", [None, "", "stop", "length"])
def test_any_incomplete_evidence_dominates_stop(response_reason, metadata_reason):
    first = runtime._response_text({"content": "最终答案：999", "finish_reason": response_reason},
                                   {"finish_reason": metadata_reason})
    second = runtime._response_text({"content": "最终答案：999", "finish_reason": metadata_reason},
                                    {"finish_reason": response_reason})
    assert not ReasoningAgent._extract_answer(first)
    assert not ReasoningAgent._extract_answer(second)


def test_explicit_length_with_null_content_allows_bounded_recovery():
    client = SequenceClient([{"content": None, "finish_reason": "length"}, "最终答案：2"])
    result = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1)).solve("计算1+1", {})
    assert result["final_response"] == "最终答案：2"
    assert len(client.calls) == 2


@pytest.mark.parametrize("name", ["max_tokens", "verifier_max_tokens", "critic_max_tokens", "fallback_max_tokens"])
@pytest.mark.parametrize("limit", [8193, 16384, 10**9])
def test_oversized_token_config_rejected_before_any_request(name, limit):
    config = AgentConfig()
    setattr(config, name, limit)
    client = SequenceClient(["最终答案：2"] * 16)
    assert ReasoningAgent(client, config).solve("计算1+1", {})["final_response"] == "未解出"
    assert client.calls == []


@pytest.mark.parametrize("limit", [True, 0, -1, 8193, 16384])
def test_direct_request_boundary_rejects_invalid_output_limit(limit):
    client = SequenceClient(["最终答案：2"])
    with pytest.raises(ValueError):
        ReasoningAgent(client)._chat("", "synthetic", 0.0, limit)
    assert not client.calls


def test_complete_negative_verdict_still_allows_critic():
    client = SequenceClient(["最终答案：2", "VERDICT: B", "NO ERROR"])
    result = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1)).solve("计算1+1", {})
    assert len(client.calls) == 3
    assert result["final_response"] == "最终答案：2"


def test_short_exact_label_remains_distinct_from_strict_q1():
    for calibrated in (False, True):
        client = SequenceClient(["最终答案：2", "A"])
        result = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1),
            local_policy=Q1Policy(calibrated_verifier=calibrated)).solve("计算1+1", {})
        assert result["final_response"] == "最终答案：2"
        assert any(t["step"] == ("verify_unknown_0_0" if calibrated else "verify_0_0") for t in result["trace"])
