"""Tool schemas, implementation registry, and isolated dispatch."""

from __future__ import annotations

import json
from typing import Any

from math_parsing import (
    DEFAULT_TOOL_TIMEOUT_SECONDS,
    MAX_TOOL_ARGUMENT_CHARS,
    bounded_result,
)
from tool_executor import ToolProcessError, ToolTimeoutError, run_with_timeout
from tool_implementations import (
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


TOOL_IMPLEMENTATIONS = {
    "calculate": calculate,
    "solve_equation": solve_equation,
    "differentiate": differentiate,
    "integrate": integrate,
    "limit": limit,
    "residue": residue,
    "matrix_det": matrix_det,
    "matrix_eigenvals": matrix_eigenvals,
    "gcd_lcm": gcd_lcm,
    "mod_pow": mod_pow,
    "binomial": binomial,
}


def _tool_definition(
    name: str,
    description: str,
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOL_DEFINITIONS = [
    _tool_definition(
        "calculate",
        "计算或化简数学表达式。用于四则运算、数值计算、表达式化简。",
        {
            "expression": {
                "type": "string",
                "description": (
                    "SymPy可解析的数学表达式，如 '2**10', "
                    "'Rational(1,2)+Rational(1,3)', 'sin(pi/4)'"
                ),
            },
        },
        ["expression"],
    ),
    _tool_definition(
        "solve_equation",
        "解方程或方程组，返回所有解。",
        {
            "equation": {
                "type": "string",
                "description": "方程表达式，如 'x**2-5*x+6'（等于0）或 'Eq(x**2,9)'",
            },
            "variable": {
                "type": "string",
                "description": "待求变量名，默认 'x'",
                "default": "x",
            },
        },
        ["equation"],
    ),
    _tool_definition(
        "differentiate",
        "求函数的导数。",
        {
            "expression": {
                "type": "string",
                "description": "待求导的表达式，如 'x**3-3*x'",
            },
            "variable": {"type": "string", "description": "求导变量", "default": "x"},
        },
        ["expression"],
    ),
    _tool_definition(
        "integrate",
        "求不定积分。",
        {
            "expression": {
                "type": "string",
                "description": "待积分的表达式，如 '2*x+1'",
            },
            "variable": {"type": "string", "description": "积分变量", "default": "x"},
        },
        ["expression"],
    ),
    _tool_definition(
        "limit",
        "求函数在某点的极限。",
        {
            "expression": {"type": "string", "description": "表达式，如 'sin(x)/x'"},
            "variable": {"type": "string", "description": "极限变量", "default": "x"},
            "point": {
                "type": "string",
                "description": "极限点，如 '0' 或 'oo'(无穷)",
                "default": "0",
            },
        },
        ["expression"],
    ),
    _tool_definition(
        "residue",
        "求复变函数在极点处的留数（复分析专用）。",
        {
            "expression": {
                "type": "string",
                "description": "复变函数表达式，如 '1/((z-1)*(z-2)**2)'",
            },
            "variable": {"type": "string", "description": "复变量名", "default": "z"},
            "pole": {"type": "string", "description": "极点位置，如 '1'"},
        },
        ["expression", "pole"],
    ),
    _tool_definition(
        "matrix_det",
        "计算矩阵的行列式（线性代数）。",
        {
            "matrix": {
                "type": "string",
                "description": "矩阵，JSON二维数组格式，如 '[[1,2],[3,4]]'",
            },
        },
        ["matrix"],
    ),
    _tool_definition(
        "matrix_eigenvals",
        "计算矩阵的特征值及代数重数（线性代数）。",
        {
            "matrix": {
                "type": "string",
                "description": "矩阵，JSON二维数组格式，如 '[[1,2],[3,4]]'",
            },
        },
        ["matrix"],
    ),
    _tool_definition(
        "gcd_lcm",
        "计算两个整数的最大公约数 gcd 和最小公倍数 lcm（数论）。",
        {
            "a": {"type": "string", "description": "第一个整数，如 '12'"},
            "b": {"type": "string", "description": "第二个整数，如 '18'"},
        },
        ["a", "b"],
    ),
    _tool_definition(
        "mod_pow",
        "计算模幂 base^exponent mod modulus（数论，处理大指数幂）。",
        {
            "base": {"type": "string", "description": "底数，如 '3'"},
            "exponent": {"type": "string", "description": "指数，如 '100'"},
            "modulus": {"type": "string", "description": "模数，如 '7'"},
        },
        ["base", "exponent", "modulus"],
    ),
    _tool_definition(
        "binomial",
        "计算二项式系数 C(n, k) 组合数（组合数学）。",
        {
            "n": {"type": "string", "description": "总数 n，如 '10'"},
            "k": {"type": "string", "description": "选取数 k，如 '3'"},
        },
        ["n", "k"],
    ),
]


def execute_tool_call(
    tool_call: dict[str, Any],
    timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> str:
    """Validate and execute one OpenAI-compatible tool call in a child process."""
    try:
        function = tool_call["function"]
        function_name = function["name"]
        raw_arguments = function.get("arguments", {})
    except (KeyError, TypeError, AttributeError):
        return "ERROR: 工具调用格式无效"
    if not isinstance(function_name, str):
        return "ERROR: 工具名称必须是字符串"
    if len(str(raw_arguments)) > MAX_TOOL_ARGUMENT_CHARS:
        return f"ERROR: 工具参数超过 {MAX_TOOL_ARGUMENT_CHARS} 字符限制"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except (json.JSONDecodeError, TypeError):
        return "ERROR: 参数JSON解析失败"
    if not isinstance(arguments, dict):
        return "ERROR: 工具参数必须是JSON对象"

    implementation = TOOL_IMPLEMENTATIONS.get(function_name)
    if implementation is None:
        return f"ERROR: 未知工具 '{function_name}'"
    try:
        return bounded_result(run_with_timeout(implementation, arguments, timeout_seconds))
    except ToolTimeoutError:
        return f"ERROR: {function_name} 执行超时（>{timeout_seconds:g} 秒）"
    except (ToolProcessError, ValueError, TypeError) as exc:
        return f"ERROR: {function_name} 执行失败: {exc}"
