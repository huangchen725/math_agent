"""The eleven bounded mathematical tool implementations."""

from __future__ import annotations

import sympy as sp

from math_parsing import (
    MAX_BINOMIAL_N,
    bounded_result,
    parse_integer,
    parse_matrix,
    parse_symbol,
    safe_parse,
)


def calculate(expression: str) -> str:
    try:
        return bounded_result(sp.simplify(safe_parse(expression)))
    except Exception as exc:
        return f"ERROR: {exc}"


def solve_equation(equation: str, variable: str = "x") -> str:
    try:
        symbol = parse_symbol(variable)
        if "Eq(" in equation:
            expression = safe_parse(equation)
        elif "=" in equation and "==" not in equation:
            left, right = equation.split("=", 1)
            expression = sp.Eq(safe_parse(left), safe_parse(right))
        else:
            expression = safe_parse(equation)
        return bounded_result(sp.solve(expression, symbol))
    except Exception as exc:
        return f"ERROR: {exc}"


def differentiate(expression: str, variable: str = "x") -> str:
    try:
        result = sp.diff(safe_parse(expression), parse_symbol(variable))
        return bounded_result(sp.simplify(result))
    except Exception as exc:
        return f"ERROR: {exc}"


def integrate(expression: str, variable: str = "x") -> str:
    try:
        result = sp.integrate(safe_parse(expression), parse_symbol(variable))
        return bounded_result(sp.simplify(result))
    except Exception as exc:
        return f"ERROR: {exc}"


def limit(expression: str, variable: str = "x", point: str = "0") -> str:
    try:
        result = sp.limit(safe_parse(expression), parse_symbol(variable), safe_parse(point))
        return bounded_result(result)
    except Exception as exc:
        return f"ERROR: {exc}"


def residue(expression: str, variable: str = "z", pole: str = "0") -> str:
    try:
        result = sp.residue(safe_parse(expression), parse_symbol(variable), safe_parse(pole))
        return bounded_result(result)
    except Exception as exc:
        return f"ERROR: {exc}"


def matrix_det(matrix: str) -> str:
    try:
        return bounded_result(sp.simplify(parse_matrix(matrix).det()))
    except Exception as exc:
        return f"ERROR: {exc}"


def matrix_eigenvals(matrix: str) -> str:
    try:
        eigenvalues = parse_matrix(matrix).eigenvals()
        parts = [f"{value}: {multiplicity}" for value, multiplicity in eigenvalues.items()]
        return bounded_result("{" + ", ".join(parts) + "}")
    except Exception as exc:
        return f"ERROR: {exc}"


def gcd_lcm(a: str, b: str) -> str:
    try:
        left = parse_integer(a, field="a")
        right = parse_integer(b, field="b")
        return f"gcd={sp.gcd(left, right)}, lcm={sp.lcm(left, right)}"
    except Exception as exc:
        return f"ERROR: {exc}"


def mod_pow(base: str, exponent: str, modulus: str) -> str:
    try:
        base_value = parse_integer(base, field="base")
        exponent_value = parse_integer(exponent, field="exponent")
        modulus_value = parse_integer(modulus, field="modulus")
        if exponent_value < 0:
            raise ValueError("exponent 必须是非负整数")
        if modulus_value <= 0:
            raise ValueError("modulus 必须是正整数")
        return str(pow(base_value, exponent_value, modulus_value))
    except Exception as exc:
        return f"ERROR: {exc}"


def binomial(n: str, k: str) -> str:
    try:
        n_value = parse_integer(n, field="n")
        k_value = parse_integer(k, field="k")
        if not 0 <= k_value <= n_value:
            raise ValueError("组合数要求 0 <= k <= n")
        if n_value > MAX_BINOMIAL_N:
            raise ValueError(f"n 不得超过 {MAX_BINOMIAL_N}")
        return str(sp.binomial(n_value, k_value))
    except Exception as exc:
        return f"ERROR: {exc}"
