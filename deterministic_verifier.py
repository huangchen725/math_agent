"""Deterministic verification primitives for structured mathematical tasks.

These functions are intentionally conservative. They return ``unknown`` when
the supplied strings cannot be parsed or when a calculation exceeds its budget.
They are ready for the later task-routing layer but do not change candidate
selection on their own.
"""

from __future__ import annotations

from typing import Any

import sympy as sp

from agent_types import Verification
from answer_equivalence import equivalent_answers
from math_tools import _parse_matrix, _parse_symbol, _safe_parse
from tool_executor import ToolProcessError, ToolTimeoutError, run_with_timeout


DEFAULT_VERIFY_TIMEOUT_SECONDS = 5.0


def _symbolic_equal_worker(left: str, right: str) -> bool:
    return sp.simplify(_safe_parse(left) - _safe_parse(right)) == 0


def _equation_worker(equation: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    candidate_value = _safe_parse(candidate)
    if "=" in equation and "==" not in equation:
        left, right = equation.split("=", 1)
        residual = _safe_parse(left) - _safe_parse(right)
    else:
        residual = _safe_parse(equation)
    return sp.simplify(residual.subs(symbol, candidate_value)) == 0


def _derivative_worker(expression: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    expected = sp.diff(_safe_parse(expression), symbol)
    return sp.simplify(expected - _safe_parse(candidate)) == 0


def _integral_worker(integrand: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    derivative = sp.diff(_safe_parse(candidate), symbol)
    return sp.simplify(derivative - _safe_parse(integrand)) == 0


def _matrix_determinant_worker(matrix: str, candidate: str) -> bool:
    determinant = _parse_matrix(matrix).det()
    return sp.simplify(determinant - _safe_parse(candidate)) == 0


def _mod_pow_worker(base: int, exponent: int, modulus: int, candidate: str) -> bool:
    if exponent < 0 or modulus <= 0:
        raise ValueError("modular exponent requires exponent >= 0 and modulus > 0")
    return sp.Integer(pow(base, exponent, modulus)) == _safe_parse(candidate)


def _binomial_worker(n: int, k: int, candidate: str) -> bool:
    if not 0 <= k <= n:
        raise ValueError("binomial requires 0 <= k <= n")
    return sp.binomial(n, k) == _safe_parse(candidate)


def _run_verifier(
    source: str,
    worker,
    kwargs: dict[str, Any],
    timeout_seconds: float,
) -> Verification:
    try:
        passed = bool(run_with_timeout(worker, kwargs, timeout_seconds))
    except ToolTimeoutError as exc:
        return Verification(source, "unknown", 0.0, f"timeout: {exc}")
    except (ToolProcessError, ValueError, TypeError) as exc:
        return Verification(source, "unknown", 0.0, str(exc)[:300])
    return Verification(
        source=source,
        status="pass" if passed else "fail",
        confidence=1.0 if passed else 0.0,
        detail="deterministic check passed" if passed else "deterministic check failed",
    )


def verify_symbolic_equivalence(
    expected: str,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    conservative = equivalent_answers(expected, candidate)
    if conservative is not None:
        return Verification(
            "deterministic:equivalence",
            "pass" if conservative else "fail",
            1.0 if conservative else 0.0,
            "conservative canonical comparison",
        )
    return _run_verifier(
        "deterministic:symbolic",
        _symbolic_equal_worker,
        {"left": expected, "right": candidate},
        timeout_seconds,
    )


def verify_equation_solution(
    equation: str,
    candidate: str,
    variable: str = "x",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:equation",
        _equation_worker,
        {"equation": equation, "variable": variable, "candidate": candidate},
        timeout_seconds,
    )


def verify_derivative(
    expression: str,
    candidate: str,
    variable: str = "x",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:derivative",
        _derivative_worker,
        {"expression": expression, "variable": variable, "candidate": candidate},
        timeout_seconds,
    )


def verify_indefinite_integral(
    integrand: str,
    candidate: str,
    variable: str = "x",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:integral",
        _integral_worker,
        {"integrand": integrand, "variable": variable, "candidate": candidate},
        timeout_seconds,
    )


def verify_matrix_determinant(
    matrix: str,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:matrix_det",
        _matrix_determinant_worker,
        {"matrix": matrix, "candidate": candidate},
        timeout_seconds,
    )


def verify_modular_power(
    base: int,
    exponent: int,
    modulus: int,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:mod_pow",
        _mod_pow_worker,
        {
            "base": base,
            "exponent": exponent,
            "modulus": modulus,
            "candidate": candidate,
        },
        timeout_seconds,
    )


def verify_binomial_value(
    n: int,
    k: int,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:binomial",
        _binomial_worker,
        {"n": n, "k": k, "candidate": candidate},
        timeout_seconds,
    )

