from pathlib import Path

from math_agent import AgentConfig, ReasoningAgent
from math_agent.candidate_evaluation import CandidateEvaluator
from math_agent.candidate_generation import CandidateGenerator
from math_agent.solver import SolveOrchestrator


def test_agent_composes_focused_pipeline_components() -> None:
    config = AgentConfig()
    agent = ReasoningAgent(client=object(), config=config)

    assert isinstance(agent._orchestrator, SolveOrchestrator)
    assert isinstance(agent._orchestrator.generator, CandidateGenerator)
    assert isinstance(agent._orchestrator.evaluator, CandidateEvaluator)
    assert agent._orchestrator.config is config
    assert agent._orchestrator.generator.config is config
    assert agent._orchestrator.evaluator.config is config


def test_agent_config_keeps_one_public_type_after_module_split() -> None:
    from math_agent.agent import AgentConfig as AgentModuleConfig
    from math_agent.agent_config import AgentConfig as ConfigModuleConfig
    from user_agent import AgentConfig as RootConfig

    assert AgentModuleConfig is ConfigModuleConfig
    assert RootConfig is ConfigModuleConfig


def test_runtime_has_no_hidden_per_problem_context_side_channel() -> None:
    root = Path(__file__).resolve().parents[1] / "math_agent"
    forbidden = ("ContextVar", "get_last_response_meta", "_ACTIVE_BUDGET", "_LAST_RESPONSE_META")

    for path in root.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in source, f"{marker} reintroduced in {path.name}"
