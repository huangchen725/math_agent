"""数学计算工具 —— 供智能体通过 tool_calling 调用，消灭算术错误。

工具定义遵循 OpenAI function calling 格式，配合 InternChatClient 的 tools 参数使用。
执行器在本地用 SymPy/NumPy 实际计算，返回精确结果。
"""
from __future__ import annotations

import json
import traceback
from typing import Any, Dict, List

import sympy as sp
from sympy.parsing.sympy_parser import parse_expr, standard_transformations, implicit_multiplication

_transformations = standard_transformations + (implicit_multiplication,)


def _safe_parse(expr_str: str):
    """安全解析 SymPy 表达式，处理常见格式问题。"""
    expr_str = expr_str.strip().rstrip(";")
    expr_str = expr_str.replace("\\", "")
    expr_str = expr_str.replace("{", "(").replace("}", ")")
    return parse_expr(expr_str, transformations=_transformations)


def calculate(expression: str) -> str:
    """计算/化简一个数学表达式。"""
    try:
        result = _safe_parse(expression)
        simplified = sp.simplify(result)
        return str(simplified)
    except Exception as e:
        return f"ERROR: {e}"


def solve_equation(equation: str, variable: str = "x") -> str:
    """解方程。例：solve_equation('x**2 - 5*x + 6', 'x') -> '[2, 3]'"""
    try:
        var = sp.Symbol(variable)
        if "Eq(" in equation:
            expr = _safe_parse(equation)
        elif "=" in equation and "==" not in equation:
            lhs, rhs = equation.split("=", 1)
            expr = sp.Eq(_safe_parse(lhs), _safe_parse(rhs))
        else:
            expr = _safe_parse(equation)
        solutions = sp.solve(expr, var)
        return str(solutions)
    except Exception as e:
        return f"ERROR: {e}"


def differentiate(expression: str, variable: str = "x") -> str:
    """求导数。"""
    try:
        var = sp.Symbol(variable)
        expr = _safe_parse(expression)
        result = sp.diff(expr, var)
        return str(sp.simplify(result))
    except Exception as e:
        return f"ERROR: {e}"


def integrate(expression: str, variable: str = "x") -> str:
    """求不定积分。"""
    try:
        var = sp.Symbol(variable)
        expr = _safe_parse(expression)
        result = sp.integrate(expr, var)
        return str(sp.simplify(result))
    except Exception as e:
        return f"ERROR: {e}"


def limit(expression: str, variable: str = "x", point: str = "0") -> str:
    """求极限。"""
    try:
        var = sp.Symbol(variable)
        expr = _safe_parse(expression)
        pt = _safe_parse(point)
        result = sp.limit(expr, var, pt)
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"


def residue(expression: str, variable: str = "z", pole: str = "0") -> str:
    """求复函数在极点处的留数。"""
    try:
        var = sp.Symbol(variable)
        expr = _safe_parse(expression)
        pole_val = _safe_parse(pole)
        result = sp.residue(expr, var, pole_val)
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"


def _parse_matrix(matrix_str: str):
    """解析矩阵字符串为 SymPy Matrix。支持 '[[1,2],[3,4]]' 或 'Matrix([[1,2],[3,4]])'。"""
    s = matrix_str.strip()
    if s.startswith("Matrix(") and s.endswith(")"):
        s = s[len("Matrix("):-1]
    s = s.replace(" ", "")
    data = json.loads(s)
    if not isinstance(data, list) or not data:
        raise ValueError(f"矩阵格式错误: {matrix_str}")
    return sp.Matrix(data)


def matrix_det(matrix: str) -> str:
    """计算矩阵行列式。"""
    try:
        m = _parse_matrix(matrix)
        return str(sp.simplify(m.det()))
    except Exception as e:
        return f"ERROR: {e}"


def matrix_eigenvals(matrix: str) -> str:
    """计算矩阵特征值，返回 {特征值: 代数重数}。"""
    try:
        m = _parse_matrix(matrix)
        ev = m.eigenvals()
        parts = [f"{k}: {v}" for k, v in ev.items()]
        return "{" + ", ".join(parts) + "}"
    except Exception as e:
        return f"ERROR: {e}"


def gcd_lcm(a: str, b: str) -> str:
    """计算两个整数的最大公约数 gcd 和最小公倍数 lcm。"""
    try:
        x = int(_safe_parse(a))
        y = int(_safe_parse(b))
        g = sp.gcd(x, y)
        l = sp.lcm(x, y)
        return f"gcd={g}, lcm={l}"
    except Exception as e:
        return f"ERROR: {e}"


def mod_pow(base: str, exponent: str, modulus: str) -> str:
    """计算模幂 base^exponent mod modulus（数论专用，处理大指数）。"""
    try:
        b = int(_safe_parse(base))
        e = int(_safe_parse(exponent))
        m = int(_safe_parse(modulus))
        return str(pow(b, e, m))
    except Exception as e:
        return f"ERROR: {e}"


def binomial(n: str, k: str) -> str:
    """计算二项式系数 C(n, k)（组合数）。"""
    try:
        n_val = int(_safe_parse(n))
        k_val = int(_safe_parse(k))
        return str(sp.binomial(n_val, k_val))
    except Exception as e:
        return f"ERROR: {e}"


# ========== 工具注册表 ==========

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

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算或化简数学表达式。用于四则运算、数值计算、表达式化简。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "SymPy可解析的数学表达式，如 '2**10', 'Rational(1,2)+Rational(1,3)', 'sin(pi/4)'"
                    },
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "solve_equation",
            "description": "解方程或方程组，返回所有解。",
            "parameters": {
                "type": "object",
                "properties": {
                    "equation": {
                        "type": "string",
                        "description": "方程表达式，如 'x**2-5*x+6'（等于0）或 'Eq(x**2,9)'"
                    },
                    "variable": {
                        "type": "string",
                        "description": "待求变量名，默认 'x'",
                        "default": "x",
                    },
                },
                "required": ["equation"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "differentiate",
            "description": "求函数的导数。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "待求导的表达式，如 'x**3-3*x'"},
                    "variable": {"type": "string", "description": "求导变量", "default": "x"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "integrate",
            "description": "求不定积分。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "待积分的表达式，如 '2*x+1'"},
                    "variable": {"type": "string", "description": "积分变量", "default": "x"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "limit",
            "description": "求函数在某点的极限。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "表达式，如 'sin(x)/x'"},
                    "variable": {"type": "string", "description": "极限变量", "default": "x"},
                    "point": {"type": "string", "description": "极限点，如 '0' 或 'oo'(无穷)", "default": "0"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "residue",
            "description": "求复变函数在极点处的留数（复分析专用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "复变函数表达式，如 '1/((z-1)*(z-2)**2)'"},
                    "variable": {"type": "string", "description": "复变量名", "default": "z"},
                    "pole": {"type": "string", "description": "极点位置，如 '1'"},
                },
                "required": ["expression", "pole"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "matrix_det",
            "description": "计算矩阵的行列式（线性代数）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "matrix": {"type": "string", "description": "矩阵，JSON二维数组格式，如 '[[1,2],[3,4]]'"},
                },
                "required": ["matrix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "matrix_eigenvals",
            "description": "计算矩阵的特征值及代数重数（线性代数）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "matrix": {"type": "string", "description": "矩阵，JSON二维数组格式，如 '[[1,2],[3,4]]'"},
                },
                "required": ["matrix"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "gcd_lcm",
            "description": "计算两个整数的最大公约数 gcd 和最小公倍数 lcm（数论）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "string", "description": "第一个整数，如 '12'"},
                    "b": {"type": "string", "description": "第二个整数，如 '18'"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mod_pow",
            "description": "计算模幂 base^exponent mod modulus（数论，处理大指数幂）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "base": {"type": "string", "description": "底数，如 '3'"},
                    "exponent": {"type": "string", "description": "指数，如 '100'"},
                    "modulus": {"type": "string", "description": "模数，如 '7'"},
                },
                "required": ["base", "exponent", "modulus"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "binomial",
            "description": "计算二项式系数 C(n, k) 组合数（组合数学）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "n": {"type": "string", "description": "总数 n，如 '10'"},
                    "k": {"type": "string", "description": "选取数 k，如 '3'"},
                },
                "required": ["n", "k"],
            },
        },
    },
]


def execute_tool_call(tool_call: Dict[str, Any]) -> str:
    """执行单个 tool_call，返回结果字符串。

    tool_call 格式（OpenAI兼容）：
    {"id": "...", "type": "function", "function": {"name": "calculate", "arguments": '{"expression": "1+1"}'}}
    """
    func_name = tool_call["function"]["name"]
    try:
        arguments = json.loads(tool_call["function"]["arguments"]) if isinstance(
            tool_call["function"]["arguments"], str
        ) else tool_call["function"]["arguments"]
    except json.JSONDecodeError:
        return "ERROR: 参数JSON解析失败"

    impl = TOOL_IMPLEMENTATIONS.get(func_name)
    if impl is None:
        return f"ERROR: 未知工具 '{func_name}'"

    try:
        return impl(**arguments)
    except Exception as e:
        return f"ERROR: {func_name} 执行失败: {e}"


def run_tool_loop(client, messages: List[Dict], max_rounds: int = 5,
                  thinking_mode: bool = True, temperature: float = 0.6,
                  max_tokens: int = 8192) -> tuple[str, List[Dict]]:
    """工具调用循环：调 client.chat → 若返回 tool_calls 则执行并回灌 → 直到文本回复。

    返回 (最终文本回复, 工具调用trace)
    """
    trace: List[Dict] = []
    current_messages = list(messages)

    for round_id in range(max_rounds):
        response = client.chat(
            messages=current_messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )

        # 文本回复 → 结束
        if isinstance(response, str):
            trace.append({"step": f"tool_round_{round_id}_text", "content": response[:500]})
            return response, trace

        # tool_calls → 执行并回灌
        assistant_msg = response  # 完整的 assistant message dict
        current_messages.append(assistant_msg)

        tool_results = []
        for tc in assistant_msg.get("tool_calls", []):
            result = execute_tool_call(tc)
            tool_results.append({"tool": tc["function"]["name"], "result": result[:200]})
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

        trace.append({"step": f"tool_round_{round_id}", "content": tool_results})

    # 超过最大轮数，强制请求一次无工具的文本回复
    response = client.chat(
        messages=current_messages,
        temperature=0.0,
        max_tokens=1024,
        thinking_mode=False,
    )
    if isinstance(response, str):
        return response, trace
    return str(response)[:500], trace
