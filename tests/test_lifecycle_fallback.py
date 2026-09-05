"""R1-4 regression: graceful degradation on budget exhaustion mid-solve.

These tests fail before R1-4 lands: when the per-problem budget is exhausted
during verification, already-generated candidates must still be aggregated
(aggregation itself consumes no budget) instead of collapsing the whole
solve into 未解出.
"""


class SteadyClient:
    """稳定 fake client：候选与验证响应均可预测。"""

    def __init__(self):
        self.calls = 0

    def chat(self, messages, temperature=None, max_tokens=None):
        self.calls += 1
        system_text = "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "system"
        )
        if "数学答案验证器" in system_text:
            return "VERDICT: A"
        return "推理：1+1=2。\n最终答案：2"


def test_verification_budget_exhaustion_preserves_candidates():
    from user_agent import AgentConfig, ReasoningAgent

    client = SteadyClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=2,
        verifier_voting_times=1,
        max_model_requests=2,
        enable_critic=False,
    )
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"] != "未解出"
    assert result["final_response"].endswith("最终答案：2")
    assert any(item["step"] == "verify_budget_exhausted" for item in result["trace"])
    assert client.calls == 2


def test_generation_budget_exhaustion_still_reports_unsolved():
    from user_agent import AgentConfig, ReasoningAgent

    client = SteadyClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=2,
        max_model_requests=1,
        enable_critic=False,
    )
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"] == "未解出"
    assert any(item["step"] == "budget_exceeded" for item in result["trace"])
