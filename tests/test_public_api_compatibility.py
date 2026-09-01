import json
from pathlib import Path
import subprocess
import sys
import textwrap

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
    assert set(policy_call) == {"messages", "temperature", "max_tokens"}
    assert verifier_call["temperature"] == 0.0
    assert verifier_call["max_tokens"] == 1024
    assert set(verifier_call) == {"messages", "temperature", "max_tokens"}

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


def test_agent_does_not_probe_strict_injected_client_private_fields() -> None:
    class StrictOfficialClient:
        def __init__(self) -> None:
            self.calls = []
            self.responses = [
                "最终答案：4\n因为 2+2=4。",
                "VERDICT: A",
            ]

        def chat(self, messages, temperature, max_tokens):
            self.calls.append({
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            return self.responses.pop(0)

        def __getattr__(self, name):
            if name.startswith("_"):
                raise RuntimeError("private client fields are forbidden")
            raise AttributeError(name)

    client = StrictOfficialClient()

    result = ReasoningAgent(client, _frozen_config()).solve("计算 2+2", {})

    assert result["final_response"].splitlines()[-1] == "最终答案：4"
    assert len(client.calls) == 2
    assert all(
        set(call) == {"messages", "temperature", "max_tokens"}
        for call in client.calls
    )


def test_tool_candidate_degrades_to_text_for_minimum_contract_client() -> None:
    class MinimumContractClient:
        def __init__(self) -> None:
            self.calls = []

        def chat(self, messages, temperature, max_tokens):
            self.calls.append({
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            serialized = json.dumps(messages, ensure_ascii=False)
            return "VERDICT: A" if "VERDICT" in serialized else "最终答案：4\n短解。"

    config = AgentConfig(
        verifier_voting_times=1,
        enable_critic=False,
        enable_reflection=False,
        enable_fallback=False,
        enable_deterministic_verification=False,
    )
    client = MinimumContractClient()

    result = ReasoningAgent(client, config).solve("计算 2+2", {})

    assert result["final_response"].splitlines()[-1] == "最终答案：4"
    assert len(client.calls) == 6
    assert all(
        set(call) == {"messages", "temperature", "max_tokens"}
        for call in client.calls
    )
    first_user_message = client.calls[0]["messages"][-1]["content"]
    assert "请调用工具" not in first_user_message
    assert sum(
        event["step"] == "tool_capability_fallback"
        and event["content"]["status"] == "fallback"
        for event in result["trace"]
    ) == 2


def test_root_entrypoint_loads_by_absolute_path_outside_project_sys_path() -> None:
    root_entrypoint = Path(__file__).resolve().parents[1] / "user_agent.py"
    probe = textwrap.dedent(
        """
        import importlib.util
        import json
        from pathlib import Path
        import sys

        entrypoint = Path(sys.argv[1]).resolve()
        project_root = str(entrypoint.parent)
        sys.path = [item for item in sys.path if item not in {"", project_root}]
        spec = importlib.util.spec_from_file_location("_official_user_agent_probe", entrypoint)
        if spec is None or spec.loader is None:
            raise RuntimeError("unable to create entrypoint spec")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(json.dumps({"agent": module.ReasoningAgent.__name__}))
        """
    )

    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe, str(root_entrypoint)],
        cwd=root_entrypoint.parent.parent,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"agent": "ReasoningAgent"}
