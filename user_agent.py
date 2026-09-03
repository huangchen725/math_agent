"""Competition compatibility facade.

The runtime implementation lives in repository-root sibling modules
(``agent.py`` and friends), mirroring the flat layout of the official
baseline.  This module preserves the official
``from user_agent import ReasoningAgent`` entrypoint, including when the
platform loads this file directly from an absolute path in an isolated
per-problem worker.
"""

from pathlib import Path
import sys
import traceback


# ``spec_from_file_location`` does not add this file's directory to ``sys.path``.
# The official entrypoint is path based, so make the repository-local runtime
# modules importable without depending on the judge's current working directory.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

try:
    from agent import (
        CRITIC_PROMPT,
        POLICY_NO_TOOL_PROMPT,
        POLICY_PROMPT,
        REFLECTION_PROMPT,
        VERIFIER_PROMPT,
        AgentConfig,
        ReasoningAgent,
    )
except Exception:  # noqa: BLE001 - diagnostic probe, see below.
    # Import-time diagnostic probe.  If the runtime modules cannot be
    # imported in the judge environment, expose the real exception through
    # the public entrypoint instead of dying with ``ModuleNotFoundError``
    # and an unreadable per-problem error record.  The message stays inside
    # ``final_response`` so the platform records it verbatim.
    _IMPORT_DIAGNOSTIC = (
        f"[user_agent import failed] {traceback.format_exc(limit=8)}"
    )

    class ReasoningAgent:  # type: ignore[no-redef]
        """Diagnostic fallback that surfaces the import failure per problem."""

        def __init__(self, client, *args, **kwargs):
            self.client = client

        def solve(self, problem, metadata):
            return {
                "final_response": _IMPORT_DIAGNOSTIC[:2000],
                "trace": [
                    {
                        "step": "import_diagnostic",
                        "content": {"status": "failed"},
                    }
                ],
            }

    class AgentConfig:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            raise RuntimeError("AgentConfig unavailable: import failed")

    CRITIC_PROMPT = ""
    POLICY_NO_TOOL_PROMPT = ""
    POLICY_PROMPT = ""
    REFLECTION_PROMPT = ""
    VERIFIER_PROMPT = ""

__all__ = [
    "AgentConfig",
    "CRITIC_PROMPT",
    "POLICY_NO_TOOL_PROMPT",
    "POLICY_PROMPT",
    "REFLECTION_PROMPT",
    "ReasoningAgent",
    "VERIFIER_PROMPT",
]
