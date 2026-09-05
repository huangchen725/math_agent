"""R1-5 regression: truncated responses are isolated from aggregation.

These tests fail before R1-5 lands: a candidate whose response lacks the
answer marker and reaches truncation-scale length must not contribute its
trailing residue as an answer, and an all-truncated candidate set must
trigger the direct-answer fallback.
"""


class TruncationClient:
    """第 1 个候选返回超长截断残文，第 2 个候选正常。"""

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
            return "VERDICT: B"
        if "直接给出最终答案" in "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "user"
        ):
            return "最终答案：2"
        if self.calls == 1:
            return "开始推导" + "详细步骤" * 1000 + "因此我们得到"
        return "推理：1+1=2。\n最终答案：2"


class AllTruncatedClient:
    """所有候选均为超长截断残文；fallback 直答正常。"""

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
            return "VERDICT: B"
        if "直接给出最终答案" in "\n".join(
            message.get("content", "")
            for message in messages
            if message.get("role") == "user"
        ):
            return "最终答案：2"
        return "开始推导" + "详细步骤" * 1000 + "因此我们得到"


def test_truncated_residue_does_not_enter_aggregation():
    from user_agent import AgentConfig, ReasoningAgent

    client = TruncationClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=2,
        verifier_voting_times=1,
        enable_critic=False,
    )
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"].endswith("最终答案：2")
    assert "详细步骤" not in result["final_response"].split("最终答案：")[-1]
    assert any(item["step"].startswith("truncated_isolated") for item in result["trace"])


def test_all_truncated_candidates_trigger_fallback():
    from user_agent import AgentConfig, ReasoningAgent

    client = AllTruncatedClient()
    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=2,
        verifier_voting_times=1,
        enable_critic=False,
    )
    result = ReasoningAgent(client, config).solve("计算 1+1。", {})

    assert result["final_response"] != "未解出"
    assert result["final_response"].endswith("最终答案：2")
    assert any(item["step"] == "truncated_fallback" for item in result["trace"])
