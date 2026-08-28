from deterministic_verifier import (
    verify_binomial_value,
    verify_derivative,
    verify_equation_solution,
    verify_indefinite_integral,
    verify_matrix_determinant,
    verify_modular_power,
    verify_symbolic_equivalence,
)


def test_symbolic_and_calculus_verifiers():
    assert verify_symbolic_equivalence("x+x", "2*x").status == "pass"
    assert verify_derivative("x**3", "3*x**2").status == "pass"
    assert verify_indefinite_integral("2*x", "x**2+7").status == "pass"


def test_equation_verifier_distinguishes_valid_and_invalid_roots():
    assert verify_equation_solution("x**2=4", "2").status == "pass"
    assert verify_equation_solution("x**2=4", "3").status == "fail"


def test_discrete_deterministic_verifiers():
    assert verify_matrix_determinant("[[1,2],[3,4]]", "-2").status == "pass"
    assert verify_modular_power(3, 100, 7, "4").status == "pass"
    assert verify_binomial_value(10, 3, "120").status == "pass"

