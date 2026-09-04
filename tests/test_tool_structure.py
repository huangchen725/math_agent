from pathlib import Path

from math_agent import math_tools
from math_agent.tool_implementations import calculate
from math_agent.tool_loop import run_tool_loop
from math_agent.tool_registry import TOOL_DEFINITIONS, TOOL_IMPLEMENTATIONS


def test_math_tools_is_a_compatibility_facade_for_focused_modules() -> None:
    assert math_tools.calculate is calculate
    assert math_tools.run_tool_loop is run_tool_loop
    assert math_tools.TOOL_DEFINITIONS is TOOL_DEFINITIONS
    assert math_tools.TOOL_IMPLEMENTATIONS is TOOL_IMPLEMENTATIONS


def test_tool_schemas_and_implementations_have_one_to_one_names() -> None:
    schema_names = [definition["function"]["name"] for definition in TOOL_DEFINITIONS]

    assert len(schema_names) == len(set(schema_names)) == 11
    assert set(schema_names) == set(TOOL_IMPLEMENTATIONS)


def test_deterministic_verifier_uses_public_math_parser_boundary() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "math_agent"
        / "deterministic_verifier.py"
    ).read_text(encoding="utf-8")

    assert "from .math_parsing import" in source
    assert "from .math_tools import _" not in source
