from deterministic_verifier import (
    verify_binomial_value,
    verify_derivative,
    verify_equation_solution,
    verify_equation_solutions,
    verify_expression_value,
    verify_indefinite_integral,
    verify_limit,
    verify_matrix_determinant,
    verify_modular_power,
    verify_residue,
    verify_symbolic_equivalence,
    verify_task_plan,
)
from task_router import VerificationPlan


def test_symbolic_and_calculus_verifiers():
    assert verify_symbolic_equivalence("x+x", "2*x").status == "pass"
    assert verify_derivative("x**3", "3*x**2").status == "pass"
    assert verify_indefinite_integral("2*x", "x**2+7").status == "pass"


def test_equation_verifier_distinguishes_valid_and_invalid_roots():
    assert verify_equation_solution("x**2=4", "2").status == "pass"
    assert verify_equation_solution("x**2=4", "3").status == "fail"


def test_complete_equation_verifier_rejects_missing_and_extraneous_roots():
    assert verify_equation_solutions("x**2=4", "{-2,2}", domain="real").status == "pass"
    assert verify_equation_solutions("x**2=4", "x=-2,x=2", domain="real").status == "pass"
    assert verify_equation_solutions("x**2=4", "2", domain="real").status == "fail"
    assert verify_equation_solutions("x**2=4", "-2,2,3", domain="real").status == "fail"
    assert verify_equation_solutions("x**2+1=0", "无解", domain="real").status == "pass"
    assert verify_equation_solutions("x**2+1=0", "-I,I", domain="complex").status == "pass"


def test_discrete_deterministic_verifiers():
    assert verify_matrix_determinant("[[1,2],[3,4]]", "-2").status == "pass"
    assert verify_modular_power(3, 100, 7, "4").status == "pass"
    assert verify_binomial_value(10, 3, "120").status == "pass"


def test_expression_limit_and_residue_verifiers():
    assert verify_expression_value("1/2+1/3", "5/6").status == "pass"
    assert verify_limit("sin(x)/x", "0", "1").status == "pass"
    assert verify_residue("1/(z-1)", "1", "1").status == "pass"


def test_router_plan_dispatch_is_conservative_for_invalid_plans():
    valid = VerificationPlan("modular_power", (("base", "3"), ("exponent", "100"), ("modulus", "7")))
    invalid = VerificationPlan("unknown_operation", ())

    assert verify_task_plan(valid, "4").status == "pass"
    assert verify_task_plan(valid, "5").status == "fail"
    assert verify_task_plan(invalid, "4").status == "unknown"
