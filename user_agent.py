"""Competition compatibility facade.

The runtime implementation lives in :mod:`math_agent`.  This module preserves
the official ``from user_agent import ReasoningAgent`` entrypoint.
"""

from math_agent.agent import (
    CRITIC_PROMPT,
    POLICY_NO_TOOL_PROMPT,
    POLICY_PROMPT,
    REFLECTION_PROMPT,
    VERIFIER_PROMPT,
    AgentConfig,
    ReasoningAgent,
)

__all__ = [
    "AgentConfig",
    "CRITIC_PROMPT",
    "POLICY_NO_TOOL_PROMPT",
    "POLICY_PROMPT",
    "REFLECTION_PROMPT",
    "ReasoningAgent",
    "VERIFIER_PROMPT",
]
