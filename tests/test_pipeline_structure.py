from pathlib import Path

from agent import AgentConfig, ReasoningAgent
from candidate_evaluation import CandidateEvaluator
from candidate_generation import CandidateGenerator
from solver import SolveOrchestrator


def test_agent_composes_focused_pipeline_components() -> None:
    config = AgentConfig()
    agent = ReasoningAgent(client=object(), config=config)

    assert isinstance(agent._orchestrator, SolveOrchestrator)
    assert isinstance(agent._orchestrator.generator, CandidateGenerator)
    assert isinstance(agent._orchestrator.evaluator, CandidateEvaluator)
    assert agent._orchestrator.config is config
    assert agent._orchestrator.generator.config is config
    assert agent._orchestrator.evaluator.config is config
    assert config.tool_candidates == 0
    assert config.plain_candidates == 3
    assert config.verifier_voting_times == 1
    assert config.max_model_requests == 6
    assert config.max_recovery_requests == 4
    assert config.enable_tools is False
    assert config.enable_critic is False
    assert config.enable_reflection is False
    assert config.enable_deterministic_verification is False
    assert config.formal_candidate_count == 3
    assert config.formal_verifier_calls_per_candidate == 1


def test_agent_config_keeps_one_public_type_after_module_split() -> None:
    from agent import AgentConfig as AgentModuleConfig
    from agent_config import AgentConfig as ConfigModuleConfig
    from user_agent import AgentConfig as RootConfig

    assert AgentModuleConfig is ConfigModuleConfig
    assert RootConfig is ConfigModuleConfig


def test_runtime_has_no_hidden_per_problem_context_side_channel() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = ("ContextVar", "get_last_response_meta", "_ACTIVE_BUDGET", "_LAST_RESPONSE_META")

    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{marker} reintroduced in {path.name}"
