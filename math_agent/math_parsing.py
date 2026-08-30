"""Restricted SymPy parsing and bounded value conversion shared by tools and verifiers."""

from __future__ import annotations

import json
import re
from typing import Any

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)


MAX_EXPRESSION_CHARS = 2048
MAX_TOOL_ARGUMENT_CHARS = 8192
MAX_TOOL_RESULT_CHARS = 8000
MAX_MATRIX_DIMENSION = 12
MAX_INTEGER_DIGITS = 1000
MAX_BINOMIAL_N = 100_000
MAX_TOOL_CALLS_PER_ROUND = 8
DEFAULT_TOOL_TIMEOUT_SECONDS = 5.0

_TRANSFORMATIONS = standard_transformations + (implicit_multiplication, convert_xor)
_SAFE_GLOBALS = {
    "__builtins__": {},
    "Symbol": sp.Symbol,
    "Integer": sp.Integer,
    "Float": sp.Float,
    "Rational": sp.Rational,
    "Function": sp.Function,
}
_SAFE_LOCALS = {
    "pi": sp.pi,
    "E": sp.E,
    "I": sp.I,
    "oo": sp.oo,
    "Eq": sp.Eq,
    "Abs": sp.Abs,
    "sqrt": sp.sqrt,
    "exp": sp.exp,
    "log": sp.log,
    "sin": sp.sin,
    "cos": sp.cos,
    "tan": sp.tan,
    "asin": sp.asin,
    "acos": sp.acos,
    "atan": sp.atan,
    "sinh": sp.sinh,
    "cosh": sp.cosh,
    "tanh": sp.tanh,
    "factorial": sp.factorial,
    "gamma": sp.gamma,
}


def bounded_result(value: Any) -> str:
    text = str(value)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        raise ValueError(f"工具结果过长（>{MAX_TOOL_RESULT_CHARS} 字符）")
    return text


def parse_symbol(name: str) -> sp.Symbol:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
        raise ValueError("变量名只能包含字母、数字和下划线，且必须以字母开头")
    return sp.Symbol(name)


def parse_integer(value: str, *, field: str) -> int:
    raw = str(value).strip()
    if not re.fullmatch(r"[+-]?\d+", raw):
        raise ValueError(f"{field} 必须是十进制整数")
    digits = raw.lstrip("+-")
    if len(digits) > MAX_INTEGER_DIGITS:
        raise ValueError(f"{field} 超过 {MAX_INTEGER_DIGITS} 位限制")
    return int(raw)


def safe_parse(expression: str):
    """Parse one expression in a no-builtins allowlist with size constraints."""
    if not isinstance(expression, str):
        raise TypeError("表达式必须是字符串")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ValueError(f"表达式超过 {MAX_EXPRESSION_CHARS} 字符限制")
    expression = expression.strip().rstrip(";")
    expression = expression.replace("\\", "")
    expression = expression.replace("{", "(").replace("}", ")")
    if not expression:
        raise ValueError("表达式不能为空")
    if "__" in expression:
        raise ValueError("表达式包含不允许的名称")
    if not re.fullmatch(r"[A-Za-z0-9_\s+\-*/^().,]+", expression):
        raise ValueError("表达式包含不允许的字符")
    if re.search(r"(?<!\d)\.|\.(?!\d)", expression):
        raise ValueError("点号只能用于十进制小数")
    if re.search(r"\d{257,}", expression):
        raise ValueError("表达式中的整数常量过长")
    for match in re.finditer(r"(?:\*\*|\^)\s*(\d+)", expression):
        if int(match.group(1)) > 10_000:
            raise ValueError("幂指数超过 10000 的安全限制")
    return parse_expr(
        expression,
        local_dict=dict(_SAFE_LOCALS),
        global_dict=dict(_SAFE_GLOBALS),
        transformations=_TRANSFORMATIONS,
        evaluate=True,
    )


def parse_matrix(matrix_text: str) -> sp.Matrix:
    """Parse a numeric JSON matrix under the shared dimension and parser limits."""
    if not isinstance(matrix_text, str) or len(matrix_text) > MAX_TOOL_ARGUMENT_CHARS:
        raise ValueError(f"矩阵参数超过 {MAX_TOOL_ARGUMENT_CHARS} 字符限制")
    payload = matrix_text.strip()
    if payload.startswith("Matrix(") and payload.endswith(")"):
        payload = payload[len("Matrix("):-1]
    data = json.loads(payload.replace(" ", ""))
    if not isinstance(data, list) or not data or not all(isinstance(row, list) for row in data):
        raise ValueError(f"矩阵格式错误: {matrix_text}")
    rows = len(data)
    columns = len(data[0]) if data[0] else 0
    if columns == 0 or any(len(row) != columns for row in data):
        raise ValueError("矩阵必须是非空的规则二维数组")
    if rows > MAX_MATRIX_DIMENSION or columns > MAX_MATRIX_DIMENSION:
        raise ValueError(f"矩阵维度不得超过 {MAX_MATRIX_DIMENSION}x{MAX_MATRIX_DIMENSION}")

    parsed = []
    for row in data:
        parsed_row = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float, str)):
                raise ValueError("矩阵元素必须是数值或数值表达式字符串")
            value = safe_parse(str(cell))
            if value.free_symbols:
                raise ValueError("矩阵工具只接受数值元素")
            parsed_row.append(value)
        parsed.append(parsed_row)
    return sp.Matrix(parsed)
