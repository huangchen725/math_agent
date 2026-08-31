from math_agent import AgentConfig as PackageAgentConfig
from math_agent import ReasoningAgent as PackageReasoningAgent
from user_agent import AgentConfig, ReasoningAgent


class RecordingClient:
    def __init__(self) -> None:
        self.calls = []
        self.responses = [
            "最终答案：4\n因为 2+2=4。",
            "VERDICT: A",
        ]

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def _frozen_config() -> AgentConfig:
    return AgentConfig(
        tool_candidates=0,
        plain_candidates=1,
        verifier_voting_times=1,
        enable_critic=False,
        enable_reflection=False,
        enable_fallback=False,
        enable_deterministic_verification=False,
    )


def test_root_entrypoint_is_the_package_public_api() -> None:
    assert ReasoningAgent is PackageReasoningAgent
    assert AgentConfig is PackageAgentConfig


def test_frozen_request_sequence_output_and_trace_contract() -> None:
    client = RecordingClient()

    result = ReasoningAgent(client, _frozen_config()).solve("计算 2+2", {})

    assert set(result) == {"final_response", "trace"}
    assert result["final_response"] == "因为 2+2=4。\n最终答案：4"
    assert result["final_response"].count("最终答案：") == 1
    assert result["final_response"].splitlines()[-1] == "最终答案：4"

    assert len(client.calls) == 2
    policy_call, verifier_call = client.calls
    assert [message["role"] for message in policy_call["messages"]] == ["system", "user"]
    assert policy_call["temperature"] == 0.6
    assert policy_call["max_tokens"] == 8192
    assert policy_call["thinking_mode"] is False
    assert "stream" not in policy_call and "n" not in policy_call
    assert verifier_call["temperature"] == 0.0
    assert verifier_call["max_tokens"] == 1024
    assert verifier_call["thinking_mode"] is False
    assert "stream" not in verifier_call and "n" not in verifier_call

    assert isinstance(result["trace"], list) and result["trace"]
    assert all(
        isinstance(event, dict) and "step" in event and "content" in event
        for event in result["trace"]
    )
    steps = [event["step"] for event in result["trace"]]
    assert steps == [
        "task_route",
        "reasoning_budget",
        "policy_plain_0",
        "verify_0_0",
        "select_final",
        "final_answer_source",
        "budget_summary",
    ]
    summary = result["trace"][-1]["content"]
    assert summary["model_requests"] == 2
    assert summary["recovery_requests"] == 0


def test_agent_uses_only_the_injected_clients_public_chat_contract() -> None:
    class OfficialLikeClient(RecordingClient):
        def chat_with_metadata(self, **kwargs):
            raise AssertionError("private platform extension must not be called")

    client = OfficialLikeClient()

    result = ReasoningAgent(client, _frozen_config()).solve("计算 2+2", {})

    assert result["final_response"].splitlines()[-1] == "最终答案：4"
    assert len(client.calls) == 2
