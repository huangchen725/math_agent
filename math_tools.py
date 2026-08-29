"""数学计算工具 —— 供智能体通过 tool_calling 调用，消灭算术错误。

工具定义遵循 OpenAI function calling 格式，配合 InternChatClient 的 tools 参数使用。
执行器在本地用 SymPy/NumPy 实际计算，返回精确结果。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

import sympy as sp
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication,
    parse_expr,
    standard_transformations,
)

from tool_executor import ToolProcessError, ToolTimeoutError, run_with_timeout
from agent_types import ModelCallResult

_transformations = standard_transformations + (implicit_multiplication, convert_xor)
_MAX_EXPRESSION_CHARS = 2048
_MAX_TOOL_ARGUMENT_CHARS = 8192
_MAX_TOOL_RESULT_CHARS = 8000
_MAX_MATRIX_DIMENSION = 12
_MAX_INTEGER_DIGITS = 1000
_MAX_BINOMIAL_N = 100_000
_MAX_TOOL_CALLS_PER_ROUND = 8
_DEFAULT_TOOL_TIMEOUT_SECONDS = 5.0

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


def _bounded_result(value: Any) -> str:
    text = str(value)
    if len(text) > _MAX_TOOL_RESULT_CHARS:
        raise ValueError(f"工具结果过长（>{_MAX_TOOL_RESULT_CHARS} 字符）")
    return text


def _parse_symbol(name: str) -> sp.Symbol:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name):
        raise ValueError("变量名只能包含字母、数字和下划线，且必须以字母开头")
    return sp.Symbol(name)


def _parse_integer(value: str, *, field: str) -> int:
    raw = str(value).strip()
    if not re.fullmatch(r"[+-]?\d+", raw):
        raise ValueError(f"{field} 必须是十进制整数")
    digits = raw.lstrip("+-")
    if len(digits) > _MAX_INTEGER_DIGITS:
        raise ValueError(f"{field} 超过 {_MAX_INTEGER_DIGITS} 位限制")
    return int(raw)


def _safe_parse(expr_str: str):
    """在受限命名空间中解析 SymPy 表达式，并拒绝代码语法与超大输入。"""
    if not isinstance(expr_str, str):
        raise TypeError("表达式必须是字符串")
    if len(expr_str) > _MAX_EXPRESSION_CHARS:
        raise ValueError(f"表达式超过 {_MAX_EXPRESSION_CHARS} 字符限制")
    expr_str = expr_str.strip().rstrip(";")
    expr_str = expr_str.replace("\\", "")
    expr_str = expr_str.replace("{", "(").replace("}", ")")
    if not expr_str:
        raise ValueError("表达式不能为空")
    if "__" in expr_str:
        raise ValueError("表达式包含不允许的名称")
    if not re.fullmatch(r"[A-Za-z0-9_\s+\-*/^().,]+", expr_str):
        raise ValueError("表达式包含不允许的字符")
    if re.search(r"(?<!\d)\.|\.(?!\d)", expr_str):
        raise ValueError("点号只能用于十进制小数")
    if re.search(r"\d{257,}", expr_str):
        raise ValueError("表达式中的整数常量过长")
    for match in re.finditer(r"(?:\*\*|\^)\s*(\d+)", expr_str):
        if int(match.group(1)) > 10_000:
            raise ValueError("幂指数超过 10000 的安全限制")
    return parse_expr(
        expr_str,
        local_dict=dict(_SAFE_LOCALS),
        global_dict=dict(_SAFE_GLOBALS),
        transformations=_transformations,
        evaluate=True,
    )


def calculate(expression: str) -> str:
    """计算/化简一个数学表达式。"""
    try:
        result = _safe_parse(expression)
        simplified = sp.simplify(result)
        return _bounded_result(simplified)
    except Exception as e:
        return f"ERROR: {e}"


def solve_equation(equation: str, variable: str = "x") -> str:
    """解方程。例：solve_equation('x**2 - 5*x + 6', 'x') -> '[2, 3]'"""
    try:
        var = _parse_symbol(variable)
        if "Eq(" in equation:
            expr = _safe_parse(equation)
        elif "=" in equation and "==" not in equation:
            lhs, rhs = equation.split("=", 1)
            expr = sp.Eq(_safe_parse(lhs), _safe_parse(rhs))
        else:
            expr = _safe_parse(equation)
        solutions = sp.solve(expr, var)
        return _bounded_result(solutions)
    except Exception as e:
        return f"ERROR: {e}"


def differentiate(expression: str, variable: str = "x") -> str:
    """求导数。"""
    try:
        var = _parse_symbol(variable)
        expr = _safe_parse(expression)
        result = sp.diff(expr, var)
        return _bounded_result(sp.simplify(result))
    except Exception as e:
        return f"ERROR: {e}"


def integrate(expression: str, variable: str = "x") -> str:
    """求不定积分。"""
    try:
        var = _parse_symbol(variable)
        expr = _safe_parse(expression)
        result = sp.integrate(expr, var)
        return _bounded_result(sp.simplify(result))
    except Exception as e:
        return f"ERROR: {e}"


def limit(expression: str, variable: str = "x", point: str = "0") -> str:
    """求极限。"""
    try:
        var = _parse_symbol(variable)
        expr = _safe_parse(expression)
        pt = _safe_parse(point)
        result = sp.limit(expr, var, pt)
        return _bounded_result(result)
    except Exception as e:
        return f"ERROR: {e}"


def residue(expression: str, variable: str = "z", pole: str = "0") -> str:
    """求复函数在极点处的留数。"""
    try:
        var = _parse_symbol(variable)
        expr = _safe_parse(expression)
        pole_val = _safe_parse(pole)
        result = sp.residue(expr, var, pole_val)
        return _bounded_result(result)
    except Exception as e:
        return f"ERROR: {e}"


def _parse_matrix(matrix_str: str):
    """解析矩阵字符串为 SymPy Matrix。支持 '[[1,2],[3,4]]' 或 'Matrix([[1,2],[3,4]])'。"""
    if not isinstance(matrix_str, str) or len(matrix_str) > _MAX_TOOL_ARGUMENT_CHARS:
        raise ValueError(f"矩阵参数超过 {_MAX_TOOL_ARGUMENT_CHARS} 字符限制")
    s = matrix_str.strip()
    if s.startswith("Matrix(") and s.endswith(")"):
        s = s[len("Matrix("):-1]
    s = s.replace(" ", "")
    data = json.loads(s)
    if not isinstance(data, list) or not data or not all(isinstance(row, list) for row in data):
        raise ValueError(f"矩阵格式错误: {matrix_str}")
    rows = len(data)
    cols = len(data[0]) if data[0] else 0
    if cols == 0 or any(len(row) != cols for row in data):
        raise ValueError("矩阵必须是非空的规则二维数组")
    if rows > _MAX_MATRIX_DIMENSION or cols > _MAX_MATRIX_DIMENSION:
        raise ValueError(f"矩阵维度不得超过 {_MAX_MATRIX_DIMENSION}x{_MAX_MATRIX_DIMENSION}")
    parsed = []
    for row in data:
        parsed_row = []
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float, str)):
                raise ValueError("矩阵元素必须是数值或数值表达式字符串")
            value = _safe_parse(str(cell))
            if value.free_symbols:
                raise ValueError("矩阵工具只接受数值元素")
            parsed_row.append(value)
        parsed.append(parsed_row)
    return sp.Matrix(parsed)


def matrix_det(matrix: str) -> str:
    """计算矩阵行列式。"""
    try:
        m = _parse_matrix(matrix)
        return _bounded_result(sp.simplify(m.det()))
    except Exception as e:
        return f"ERROR: {e}"


def matrix_eigenvals(matrix: str) -> str:
    """计算矩阵特征值，返回 {特征值: 代数重数}。"""
    try:
        m = _parse_matrix(matrix)
        ev = m.eigenvals()
        parts = [f"{k}: {v}" for k, v in ev.items()]
        return _bounded_result("{" + ", ".join(parts) + "}")
    except Exception as e:
        return f"ERROR: {e}"


def gcd_lcm(a: str, b: str) -> str:
    """计算两个整数的最大公约数 gcd 和最小公倍数 lcm。"""
    try:
        x = _parse_integer(a, field="a")
        y = _parse_integer(b, field="b")
        g = sp.gcd(x, y)
        l = sp.lcm(x, y)
        return f"gcd={g}, lcm={l}"
    except Exception as e:
        return f"ERROR: {e}"


def mod_pow(base: str, exponent: str, modulus: str) -> str:
    """计算模幂 base^exponent mod modulus（数论专用，处理大指数）。"""
    try:
        b = _parse_integer(base, field="base")
        e = _parse_integer(exponent, field="exponent")
        m = _parse_integer(modulus, field="modulus")
        if e < 0:
            raise ValueError("exponent 必须是非负整数")
        if m <= 0:
            raise ValueError("modulus 必须是正整数")
        return str(pow(b, e, m))
    except Exception as e:
        return f"ERROR: {e}"


def binomial(n: str, k: str) -> str:
    """计算二项式系数 C(n, k)（组合数）。"""
    try:
        n_val = _parse_integer(n, field="n")
        k_val = _parse_integer(k, field="k")
        if not 0 <= k_val <= n_val:
            raise ValueError("组合数要求 0 <= k <= n")
        if n_val > _MAX_BINOMIAL_N:
            raise ValueError(f"n 不得超过 {_MAX_BINOMIAL_N}")
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


def execute_tool_call(
    tool_call: Dict[str, Any],
    timeout_seconds: float = _DEFAULT_TOOL_TIMEOUT_SECONDS,
) -> str:
    """执行单个 tool_call，返回结果字符串。

    tool_call 格式（OpenAI兼容）：
    {"id": "...", "type": "function", "function": {"name": "calculate", "arguments": '{"expression": "1+1"}'}}
    """
    try:
        function = tool_call["function"]
        func_name = function["name"]
        raw_arguments = function.get("arguments", {})
    except (KeyError, TypeError, AttributeError):
        return "ERROR: 工具调用格式无效"
    if not isinstance(func_name, str):
        return "ERROR: 工具名称必须是字符串"
    if len(str(raw_arguments)) > _MAX_TOOL_ARGUMENT_CHARS:
        return f"ERROR: 工具参数超过 {_MAX_TOOL_ARGUMENT_CHARS} 字符限制"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except (json.JSONDecodeError, TypeError):
        return "ERROR: 参数JSON解析失败"
    if not isinstance(arguments, dict):
        return "ERROR: 工具参数必须是JSON对象"

    impl = TOOL_IMPLEMENTATIONS.get(func_name)
    if impl is None:
        return f"ERROR: 未知工具 '{func_name}'"

    try:
        return _bounded_result(run_with_timeout(impl, arguments, timeout_seconds))
    except ToolTimeoutError:
        return f"ERROR: {func_name} 执行超时（>{timeout_seconds:g} 秒）"
    except (ToolProcessError, ValueError, TypeError) as e:
        return f"ERROR: {func_name} 执行失败: {e}"


def run_tool_loop(client, messages: List[Dict], max_rounds: int = 5,
                  thinking_mode: bool = True, temperature: float = 0.6,
                  max_tokens: int = 8192,
                  tool_timeout_seconds: float = _DEFAULT_TOOL_TIMEOUT_SECONDS,
                  budget=None, *, candidate_id: int | None = None,
                  final_instruction: str = "", return_call_result: bool = False):
    """工具调用循环：调 client.chat → 若返回 tool_calls 则执行并回灌 → 直到文本回复。

    返回 (最终文本回复, 工具调用trace)
    """
    trace: List[Dict] = []
    current_messages = list(messages)

    def call_model(*, stage: str, **kwargs):
        request_id = None
        if budget is not None:
            request_id = budget.consume_model_request(
                stage=stage,
                candidate_id=candidate_id,
            )
        response = client.chat(**kwargs)
        metadata = {}
        if budget is not None and hasattr(client, "get_last_response_meta"):
            metadata = client.get_last_response_meta()
            metadata = metadata if isinstance(metadata, dict) else {}
            budget.record_response_meta(metadata, request_id)
        elif hasattr(client, "get_last_response_meta"):
            metadata = client.get_last_response_meta()
            metadata = metadata if isinstance(metadata, dict) else {}
        text = response if isinstance(response, str) else str(response.get("content", ""))
        result = ModelCallResult(
            text=text,
            stage=stage,
            finish_reason=str(metadata.get("finish_reason", "")),
            usage=metadata.get("usage", {}) if isinstance(metadata, dict) else {},
            candidate_id=candidate_id,
            request_id=request_id,
        )
        return response, result

    def finish(text: str, result: ModelCallResult):
        if return_call_result:
            return text, trace, result
        return text, trace

    for round_id in range(max_rounds):
        response, call_result = call_model(
            stage="policy_tool",
            messages=current_messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
            temperature=temperature,
            max_tokens=max_tokens,
            thinking_mode=thinking_mode,
        )

        if call_result.truncated:
            trace.append({
                "step": f"tool_round_{round_id}_truncated",
                "content": {"stage": "policy_tool", "candidate_id": candidate_id},
            })
            return finish(call_result.text, call_result)

        # 文本回复 → 结束
        if isinstance(response, str):
            trace.append({"step": f"tool_round_{round_id}_text", "content": response[:500]})
            return finish(response, call_result)

        if not isinstance(response, dict):
            raise TypeError(f"不支持的模型响应类型: {type(response).__name__}")

        tool_calls = response.get("tool_calls") or []
        if not tool_calls:
            content = response.get("content")
            if isinstance(content, str):
                trace.append({"step": f"tool_round_{round_id}_text", "content": content[:500]})
                return finish(content, call_result)
            raise ValueError("模型响应既没有文本，也没有 tool_calls")
        if not isinstance(tool_calls, list):
            raise TypeError("tool_calls 必须是列表")

        # tool_calls → 执行并回灌
        assistant_msg = response  # 完整的 assistant message dict
        current_messages.append(assistant_msg)

        tool_results = []
        for call_index, tc in enumerate(tool_calls[:_MAX_TOOL_CALLS_PER_ROUND]):
            if budget is not None:
                budget.consume_tool_call()
            result = execute_tool_call(tc, timeout_seconds=tool_timeout_seconds)
            function = tc.get("function", {}) if isinstance(tc, dict) else {}
            tool_name = function.get("name", "<invalid>") if isinstance(function, dict) else "<invalid>"
            tool_call_id = tc.get("id", f"invalid-{round_id}-{call_index}") if isinstance(tc, dict) else f"invalid-{round_id}-{call_index}"
            tool_results.append({"tool": tool_name, "result": result[:200]})
            current_messages.append({
                "role": "tool",
                "tool_call_id": str(tool_call_id),
                "content": result,
            })

        if len(tool_calls) > _MAX_TOOL_CALLS_PER_ROUND:
            for call_index, tc in enumerate(
                tool_calls[_MAX_TOOL_CALLS_PER_ROUND:],
                start=_MAX_TOOL_CALLS_PER_ROUND,
            ):
                tool_call_id = (
                    tc.get("id", f"limited-{round_id}-{call_index}")
                    if isinstance(tc, dict)
                    else f"limited-{round_id}-{call_index}"
                )
                current_messages.append({
                    "role": "tool",
                    "tool_call_id": str(tool_call_id),
                    "content": (
                        "ERROR: 本轮工具调用数量超过限制，"
                        f"仅执行前 {_MAX_TOOL_CALLS_PER_ROUND} 个"
                    ),
                })
            tool_results.append({
                "tool": "<limit>",
                "result": f"仅执行前 {_MAX_TOOL_CALLS_PER_ROUND} 个工具调用",
            })

        trace.append({"step": f"tool_round_{round_id}", "content": tool_results})

    # 超过最大轮数，强制请求一次无工具的文本回复
    if final_instruction:
        current_messages.append({"role": "user", "content": final_instruction})
    response, call_result = call_model(
        stage="tool_final",
        messages=current_messages,
        temperature=0.0,
        max_tokens=max_tokens,
        thinking_mode=False,
    )
    if isinstance(response, str):
        return finish(response, call_result)
    return finish(str(response.get("content", ""))[:500], call_result)
