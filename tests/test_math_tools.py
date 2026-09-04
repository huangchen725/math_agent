import json

import pytest

from math_agent.budget import ExecutionBudget
from math_agent.math_tools import (
    binomial,
    calculate,
    differentiate,
    execute_tool_call,
    gcd_lcm,
    integrate,
    limit,
    matrix_det,
    matrix_eigenvals,
    mod_pow,
    residue,
    run_tool_loop,
    solve_equation,
)
from math_agent.model_gateway import ModelGateway


def test_calculate_supports_common_math_syntax():
    assert calculate("2^10") == "1024"
    assert calculate("sin(pi/2)") == "1"


def test_registered_math_tools_cover_their_documented_examples():
    assert solve_equation("x**2 - 5*x + 6", "x") == "[2, 3]"
    assert differentiate("x**3", "x") == "3*x**2"
    assert integrate("2*x + 1", "x") == "x*(x + 1)"
    assert limit("sin(x)/x", "x", "0") == "1"
    assert residue("1/(z-1)", "z", "1") == "1"
    assert matrix_det("[[1,2],[3,4]]") == "-2"
    eigenvalues = matrix_eigenvals("[[2,1],[1,2]]")
    assert "1: 1" in eigenvalues and "3: 1" in eigenvalues
    assert gcd_lcm("12", "18") == "gcd=6, lcm=36"
    assert mod_pow("3", "100", "7") == "4"
    assert binomial("10", "3") == "120"


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os').system('echo unsafe')",
        "(1).__class__",
        "2**10001",
        "x" * 2049,
    ],
)
def test_calculate_rejects_code_syntax_and_excessive_input(expression: str):
    assert calculate(expression).startswith("ERROR:")


def test_integer_tool_does_not_evaluate_expressions():
    assert mod_pow("3", "100", "7") == "4"
    assert mod_pow("3", "2**10", "7").startswith("ERROR:")


def test_matrix_tool_rejects_oversized_matrix():
    matrix = json.dumps([[1] * 13 for _ in range(13)])
    assert matrix_det(matrix).startswith("ERROR:")


def test_execute_tool_call_handles_malformed_payload():
    assert execute_tool_call({}).startswith("ERROR:")
    assert execute_tool_call({"function": {"name": "calculate", "arguments": "[]"}}).startswith(
        "ERROR:"
    )


def test_execute_tool_call_has_a_killable_hard_timeout():
    result = execute_tool_call(
        {
            "function": {
                "name": "calculate",
                "arguments": '{"expression": "1+1"}',
            }
        },
        timeout_seconds=0.001,
    )
    assert "执行超时" in result


def test_tool_loop_accepts_dict_text_response():
    class Client:
        def chat(self, **kwargs):
            return {"role": "assistant", "content": "最终答案：2"}

    response, trace = run_tool_loop(Client(), [{"role": "user", "content": "1+1"}])
    assert response == "最终答案：2"
    assert trace[-1]["step"].endswith("_text")


def test_tool_loop_replies_to_calls_over_the_execution_limit():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"call-{index}",
                            "type": "function",
                            "function": {
                                "name": "calculate",
                                "arguments": '{"expression": "1+1"}',
                            },
                        }
                        for index in range(9)
                    ],
                }
            tool_messages = [m for m in kwargs["messages"] if m.get("role") == "tool"]
            assert len(tool_messages) == 9
            assert tool_messages[-1]["tool_call_id"] == "call-8"
            assert tool_messages[-1]["content"].startswith("ERROR:")
            return "最终答案：2"

    response, _ = run_tool_loop(
        Client(),
        [{"role": "user", "content": "1+1"}],
        max_rounds=2,
    )

    assert response == "最终答案：2"


def test_tool_loop_uses_the_budget_bound_to_model_gateway():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": "calculate",
                            "arguments": '{"expression": "1+1"}',
                        },
                    }],
                }
            return "最终答案：2"

    budget = ExecutionBudget(timeout_seconds=10)
    gateway = ModelGateway(Client(), budget)

    response, _ = run_tool_loop(
        gateway,
        [{"role": "user", "content": "1+1"}],
        max_rounds=2,
    )

    assert response == "最终答案：2"
    assert budget.snapshot()["tool_calls"] == 1
