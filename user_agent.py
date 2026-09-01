"""Competition compatibility facade.

The runtime implementation lives in :mod:`math_agent`.  This module preserves
the official ``from user_agent import ReasoningAgent`` entrypoint, including
when the platform loads this file directly from an absolute path in an
isolated per-problem worker.
"""

from pathlib import Path
import sys


# ``spec_from_file_location`` does not add this file's directory to ``sys.path``.
# The official entrypoint is path based, so make the repository-local runtime
# package importable without depending on the judge's current working directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

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
