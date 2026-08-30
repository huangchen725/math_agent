"""Compatibility facade for the split mathematical tool subsystem."""

from .math_parsing import (
    bounded_result as _bounded_result,
    parse_integer as _parse_integer,
    parse_matrix as _parse_matrix,
    parse_symbol as _parse_symbol,
    safe_parse as _safe_parse,
)
from .tool_implementations import (
    binomial,
    calculate,
    differentiate,
    gcd_lcm,
    integrate,
    limit,
    matrix_det,
    matrix_eigenvals,
    mod_pow,
    residue,
    solve_equation,
)
from .tool_loop import run_tool_loop
from .tool_registry import TOOL_DEFINITIONS, TOOL_IMPLEMENTATIONS, execute_tool_call


__all__ = [
    "TOOL_DEFINITIONS",
    "TOOL_IMPLEMENTATIONS",
    "binomial",
    "calculate",
    "differentiate",
    "execute_tool_call",
    "gcd_lcm",
    "integrate",
    "limit",
    "matrix_det",
    "matrix_eigenvals",
    "mod_pow",
    "residue",
    "run_tool_loop",
    "solve_equation",
]
