"""Deterministic verification primitives for structured mathematical tasks.

These functions are intentionally conservative. They return ``unknown`` when
the supplied strings cannot be parsed or when a calculation exceeds its budget.
They are ready for the later task-routing layer but do not change candidate
selection on their own.
"""

from __future__ import annotations

import re
from typing import Any

import sympy as sp

from .agent_types import Verification
from .answer_equivalence import equivalent_answers, normalize_answer
from .math_tools import _parse_matrix, _parse_symbol, _safe_parse
from .task_router import VerificationPlan
from .tool_executor import ToolProcessError, ToolTimeoutError, run_with_timeout


DEFAULT_VERIFY_TIMEOUT_SECONDS = 5.0


def _symbolic_equal_worker(left: str, right: str) -> bool:
    return sp.simplify(_safe_parse(left) - _safe_parse(right)) == 0


def _expression_value_worker(expression: str, candidate: str) -> bool:
    expected = sp.simplify(_safe_parse(expression))
    supplied = sp.simplify(_safe_parse(candidate))
    return expected == supplied or sp.simplify(expected - supplied) == 0


def _equation_worker(equation: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    candidate_value = _safe_parse(candidate)
    if "=" in equation and "==" not in equation:
        left, right = equation.split("=", 1)
        residual = _safe_parse(left) - _safe_parse(right)
    else:
        residual = _safe_parse(equation)
    return sp.simplify(residual.subs(symbol, candidate_value)) == 0


def _split_solution_values(value: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for character in value:
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced candidate solution")
        if character in ",;" and depth == 0:
            part = "".join(current).strip()
            if not part:
                raise ValueError("empty candidate solution")
            parts.append(part)
            current = []
        else:
            current.append(character)
    if depth != 0:
        raise ValueError("unbalanced candidate solution")
    final = "".join(current).strip()
    if final:
        parts.append(final)
    return parts


def _equation_solutions_worker(
    equation: str,
    variable: str,
    candidate: str,
    domain: str,
) -> bool:
    symbol = _parse_symbol(variable)
    if "=" in equation and "==" not in equation:
        left, right = equation.split("=", 1)
        residual = _safe_parse(left) - _safe_parse(right)
    else:
        residual = _safe_parse(equation)
    domain_set = {"real": sp.S.Reals, "complex": sp.S.Complexes}.get(domain)
    if domain_set is None:
        raise ValueError("equation domain must be real or complex")
    solution_set = sp.solveset(residual, symbol, domain=domain_set)
    if solution_set is sp.S.EmptySet:
        expected = []
    elif isinstance(solution_set, sp.FiniteSet):
        expected = list(solution_set)
    else:
        raise ValueError("equation solver did not return a finite solution set")

    raw = normalize_answer(candidate).strip()
    if not expected:
        return raw.casefold() in {"无解", "emptyset", "empty set", "{}", "∅"}
    if raw.casefold() in {"无解", "emptyset", "empty set", "{}", "∅"}:
        return False

    if len(raw) >= 2 and raw[0] in "[{" and raw[-1] in "]}":
        raw = raw[1:-1].strip()
    raw = raw.replace("，", ",").replace("；", ";").replace("或", ",")
    raw = re.sub(r"\bor\b", ",", raw, flags=re.IGNORECASE)
    raw = re.sub(rf"(?<![A-Za-z0-9_]){re.escape(variable)}\s*=\s*", "", raw)
    supplied = [_safe_parse(part) for part in _split_solution_values(raw)]
    if len(supplied) != len(expected):
        return False

    unmatched = list(expected)
    for candidate_value in supplied:
        for index, expected_value in enumerate(unmatched):
            if sp.simplify(candidate_value - expected_value) == 0:
                unmatched.pop(index)
                break
        else:
            return False
    return not unmatched


def _derivative_worker(expression: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    expected = sp.diff(_safe_parse(expression), symbol)
    return sp.simplify(expected - _safe_parse(candidate)) == 0


def _integral_worker(integrand: str, variable: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    derivative = sp.diff(_safe_parse(candidate), symbol)
    return sp.simplify(derivative - _safe_parse(integrand)) == 0


def _limit_worker(expression: str, variable: str, point: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    expected = sp.limit(_safe_parse(expression), symbol, _safe_parse(point))
    supplied = _safe_parse(candidate)
    return expected == supplied or sp.simplify(expected - supplied) == 0


def _residue_worker(expression: str, variable: str, pole: str, candidate: str) -> bool:
    symbol = _parse_symbol(variable)
    expected = sp.residue(_safe_parse(expression), symbol, _safe_parse(pole))
    supplied = _safe_parse(candidate)
    return expected == supplied or sp.simplify(expected - supplied) == 0


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


def verify_expression_value(
    expression: str,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:expression",
        _expression_value_worker,
        {"expression": expression, "candidate": candidate},
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


def verify_equation_solutions(
    equation: str,
    candidate: str,
    variable: str = "x",
    domain: str = "complex",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    """Verify a complete finite solution set, including missing/extraneous roots."""
    return _run_verifier(
        "deterministic:equation_solutions",
        _equation_solutions_worker,
        {
            "equation": equation,
            "variable": variable,
            "candidate": candidate,
            "domain": domain,
        },
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


def verify_limit(
    expression: str,
    point: str,
    candidate: str,
    variable: str = "x",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:limit",
        _limit_worker,
        {
            "expression": expression,
            "variable": variable,
            "point": point,
            "candidate": candidate,
        },
        timeout_seconds,
    )


def verify_residue(
    expression: str,
    pole: str,
    candidate: str,
    variable: str = "z",
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    return _run_verifier(
        "deterministic:residue",
        _residue_worker,
        {
            "expression": expression,
            "variable": variable,
            "pole": pole,
            "candidate": candidate,
        },
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


def verify_task_plan(
    plan: VerificationPlan,
    candidate: str,
    *,
    timeout_seconds: float = DEFAULT_VERIFY_TIMEOUT_SECONDS,
) -> Verification:
    """Execute one router-produced plan without treating unsupported input as false."""
    parameters = plan.as_kwargs()
    try:
        if plan.kind == "expression":
            return verify_expression_value(
                parameters["expression"], candidate, timeout_seconds=timeout_seconds
            )
        if plan.kind == "equation_solutions":
            return verify_equation_solutions(
                parameters["equation"],
                candidate,
                parameters["variable"],
                parameters["domain"],
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "derivative":
            return verify_derivative(
                parameters["expression"],
                candidate,
                parameters["variable"],
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "integral":
            return verify_indefinite_integral(
                parameters["expression"],
                candidate,
                parameters["variable"],
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "limit":
            return verify_limit(
                parameters["expression"],
                parameters["point"],
                candidate,
                parameters["variable"],
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "residue":
            return verify_residue(
                parameters["expression"],
                parameters["pole"],
                candidate,
                parameters["variable"],
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "matrix_determinant":
            return verify_matrix_determinant(
                parameters["matrix"], candidate, timeout_seconds=timeout_seconds
            )
        if plan.kind == "modular_power":
            return verify_modular_power(
                int(parameters["base"]),
                int(parameters["exponent"]),
                int(parameters["modulus"]),
                candidate,
                timeout_seconds=timeout_seconds,
            )
        if plan.kind == "binomial":
            return verify_binomial_value(
                int(parameters["n"]),
                int(parameters["k"]),
                candidate,
                timeout_seconds=timeout_seconds,
            )
    except (KeyError, TypeError, ValueError) as exc:
        return Verification(
            source=f"deterministic:{plan.kind}",
            status="unknown",
            confidence=0.0,
            detail=f"invalid verification plan: {str(exc)[:200]}",
        )
    return Verification(
        source=f"deterministic:{plan.kind}",
        status="unknown",
        confidence=0.0,
        detail="unsupported verification plan",
    )
