"""Independent exact arithmetic oracles and adversarial Q1 state regressions."""
from dataclasses import asdict
from fractions import Fraction
from itertools import combinations

import pytest

from user_agent import (AgentConfig, Candidate, Q1Policy, ReasoningAgent, _exact_problem_value,
                        _exact_answer_value, _complete_task_check, build_answer, legacy_deployment_policy)


class Client:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        self.calls.append((messages, temperature, max_tokens))
        return next(self.replies)


def solve(replies, policy=None, **config):
    client = Client(replies)
    settings = {"tool_candidates": 0, "plain_candidates": 1, "enable_critic": False, **config}
    result = ReasoningAgent(client, AgentConfig(**settings),
                            local_policy=legacy_deployment_policy() if policy is None else policy).solve("计算1+1", {})
    return client, result


@pytest.mark.parametrize("text", ["CORRECT", "A", "VERDICT: A\nVERDICT: B", "not VERDICT: A",
    "VERDICT: A because...", "", "VERDICT: C", "Probably correct", "VERDICT: B\nVERDICT: A"])
def test_uncertain_verifier_is_unknown_and_never_triggers_critic(text):
    client, result = solve(["最终答案：2", text], Q1Policy(calibrated_verifier=True), enable_critic=True)
    assert len(client.calls) == 2
    assert result["final_response"] == "最终答案：2"
    assert any(x["step"].startswith("verify_unknown") for x in result["trace"])


@pytest.mark.parametrize("text,status", [("VERDICT: A", "pass"), (" verdict：b ", "fail")])
def test_strict_verdict_states(text, status):
    assert ReasoningAgent._verdict_status(text) == status


def test_plain_candidate_recovery_with_valid_sibling_and_shared_budget():
    client, result = solve(["未完成", "最终答案：2", "最终答案：2", "VERDICT: A", "VERDICT: A"],
        Q1Policy(recover_plain=True), plain_candidates=2, max_model_requests=5)
    assert len(client.calls) == 5
    assert result["final_response"].endswith("最终答案：2")
    assert result["trace"][-1]["content"]["model_requests"] == 5


def test_recovery_rejected_by_complete_exact_evidence():
    client, result = solve(["unfinished", "最终答案：3"], Q1Policy(deterministic=True))
    assert result["final_response"] == "未解出"
    assert len(client.calls) == 2


def test_exact_evidence_overrides_wrong_majority_without_extra_calls():
    client, result = solve(["最终答案：3", "最终答案：3", "最终答案：2"] + ["VERDICT: A"]*3,
        Q1Policy(deterministic=True), plain_candidates=3)
    assert result["final_response"] == "最终答案：2"
    assert len(client.calls) == 6


def test_unknown_problem_cannot_use_partial_computation_to_change_majority():
    client = Client(["最终答案：3", "最终答案：3", "最终答案：2"] + ["VERDICT: A"]*3)
    agent = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=3, enable_critic=False),
        local_policy=Q1Policy(deterministic=True))
    result = agent.solve("计算1+1，然后把结果加一", {"answer": "2"})
    assert result["final_response"] == "最终答案：3"


@pytest.mark.parametrize("a", range(-8, 9))
def test_exact_arithmetic_cancellation_and_fraction_identities(a):
    for b in range(1, 8):
        assert _exact_problem_value(f"计算 ({a}*{b})/{b}") == a
        assert _exact_problem_value(f"计算 ({a}/{b})-({a}/{b})") == 0
        assert _exact_answer_value(f"{a}/{b}") == Fraction(a, b)


@pytest.mark.parametrize("n", range(12))
def test_binomial_independent_enumeration_oracle(n):
    for k in range(n+1):
        expected = sum(1 for _ in combinations(range(n), k))
        assert _exact_problem_value(f"计算 C({n},{k})") == expected


@pytest.mark.parametrize("base", range(-5, 6))
def test_modular_independent_repeated_multiplication_oracle(base):
    for modulus in range(1, 9):
        expected = 1 % modulus
        for exponent in range(8):
            assert _exact_problem_value(f"求整数{base}^{exponent}除以{modulus}的余数") == expected
            expected = (expected*base) % modulus


@pytest.mark.parametrize("text", ["计算 1/0", "计算 9**999999", "计算 0.1+0.2", "计算 __import__('os')",
    "计算 (1).__class__", "计算 (lambda:1)()", "计算 x-x", "计算 1+1=", "计算1+1，求其倒数",
    "求整数2^3除以0的余数", "计算 C(1001,2)", "计算 C(2,3)", "计算 -2**0.5",
    "Calculate 1+1 and then add 1", "计算 " + "("*150 + "1" + ")"*150])
def test_unsupported_or_resource_excessive_tasks_abstain(text):
    assert _exact_problem_value(text) is None


def test_all_fail_exact_evidence_cannot_revive_any_candidate():
    agent = ReasoningAgent(Client([]), local_policy=Q1Policy(deterministic=True))
    candidate = Candidate("最终答案：3", "plain", build_answer("3"), 1.3, 1)
    assert agent._apply_exact_evidence("计算1+1", [candidate], []) == []


def test_reflection_switch_is_honored():
    client, result = solve(["最终答案：2", "VERDICT: B", "请重新计算"], enable_critic=True, enable_reflection=False)
    assert len(client.calls) == 3
    assert result["final_response"] == "最终答案：2"


def test_diversity_does_not_mutate_shared_config():
    config = AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False)
    original = asdict(config)
    client = Client(["最终答案：2", "VERDICT: A"])
    agent = ReasoningAgent(client, config, local_policy=Q1Policy(diverse_candidates=True))
    assert agent.solve("计算1+1", {})["final_response"] == "最终答案：2"
    assert client.calls[0][1] == 0.8
    assert asdict(config) == original


def test_compact_route_does_not_leak_reference_metadata():
    client = Client(["最终答案：2", "VERDICT: A"])
    agent = ReasoningAgent(client, AgentConfig(tool_candidates=0, plain_candidates=1, enable_critic=False),
        local_policy=Q1Policy(compact_routing=True))
    agent.solve("计算1+1", {"answer": "PRIVATE_REFERENCE_999"})
    assert all("PRIVATE_REFERENCE" not in str(call[0]) for call in client.calls)
    assert len(client.calls[0][0][0]["content"]) < 400


@pytest.mark.parametrize("degree", range(1, 10))
def test_polynomial_derivative_antiderivative_inverse(degree):
    for coefficient in (-3, 1, 7):
        integral = f"({coefficient}*x^{degree+1})/{degree+1}+C"
        assert _complete_task_check(f"计算 {coefficient}*x^{degree} 关于x的不定积分", integral) == "pass"
        assert _complete_task_check(f"求函数 f(x)={coefficient}*x^{degree} 的导数",
            f"{coefficient*degree}*x^{degree-1}") == "pass"
        assert _complete_task_check(f"求函数 f(x)={coefficient}*x^{degree} 的导数", "0") == "fail"


@pytest.mark.parametrize("problem,answer", [
    ("计算 2*x 关于x的不定积分", "x^2"),
    ("计算 2*x 关于x的不定积分", "x^2+C*x+C"),
    ("求函数 f(x)=x^2 的导数，并求零点", "2*x"),
    ("求函数 f(x)=x^2 的导数", "2*x # arbitrary ignored suffix"),
    ("求函数 f(x)=x/x 的导数", "0"),
    ("求函数 f(x)=sin(x) 的导数", "cos(x)"),
    ("求函数 f(x)=x^100 的导数", "100*x^99"),
    ("计算矩阵 [[1,2],[3]] 的行列式", "2"),
])
def test_partial_family_unsupported_domain_or_multitask_cannot_pass(problem, answer):
    assert _complete_task_check(problem, answer) == "unknown"


@pytest.mark.parametrize("a", range(-5, 6))
def test_matrix_triangular_oracle_and_row_swap(a):
    assert _complete_task_check(f"计算矩阵 [[{a},7],[0,3]] 的行列式", str(a*3)) == "pass"
    assert _complete_task_check(f"计算矩阵 [[0,3],[{a},7]] 的行列式", str(-a*3)) == "pass"
    assert _complete_task_check(f"计算矩阵 [[{a},7,8],[0,3,5],[0,0,2]] 的行列式", str(a*6)) == "pass"
