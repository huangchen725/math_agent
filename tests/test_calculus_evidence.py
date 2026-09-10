"""Bounded exact calculus proofs; generated tests and public historical cases.

The two fixed U-MATH inputs already occur in the licensed public development
receipts. No hidden evaluator question or answer is used, and no API is called.
"""
from fractions import Fraction
import random

import pytest

import user_agent as r


RADICAL_PROBLEM = r"Calculate the indefinite integral: $\int \frac{x+2}{\sqrt{25x^2+10x+6}} \, dx$."
RADICAL_GOOD = r"\frac{1}{25}\sqrt{25x^2+10x+6}+\frac{9}{25}\ln\left(5x+1+\sqrt{25x^2+10x+6}\right)+C"
RADICAL_BAD = r"\frac{1}{5}\sqrt{25x^2+10x+6}+\frac{1}{5}\ln\left(5x+1+\sqrt{25x^2+10x+6}\right)+C"
RATIONAL_PROBLEM = r"Calculate the indefinite integral: $\int \frac{4x+5}{(x^2+2x+9)^2} \, dx$."
RATIONAL_GOOD = r"\frac{x-31}{16(x^2+2x+9)}+\frac{\sqrt{2}}{64}\arctan\frac{x+1}{2\sqrt{2}}+C"
RATIONAL_BAD = r"-\frac{2x+9}{16(x^2+2x+9)}+\frac{7\sqrt{2}}{64}\arctan\frac{x+1}{2\sqrt{2}}+C"
ORIGINAL_RADICAL = "Compute the integral:\n$$\n\\int \\frac{ x+2 }{ \\sqrt{6+10 \\cdot x+25 \\cdot x^2} } \\, dx\n$$"
ORIGINAL_RATIONAL = "Calculate the integral:\n$$\n\\int \\frac{ M \\cdot x + N }{ \\left( x^2 + p \\cdot x + q \\right)^m } \\, dx\n$$\nwhere $M = 4$, $N = 5$, $p = 2$, $q = 9$, and $m = 2$."


@pytest.mark.parametrize("problem,good,bad", [
    (RADICAL_PROBLEM, RADICAL_GOOD, RADICAL_BAD),
    (RATIONAL_PROBLEM, RATIONAL_GOOD, RATIONAL_BAD),
])
def test_historical_integral_candidates_are_proved_not_sampled(problem, good, bad):
    assert r._calculus_task_check(problem, good) == "pass"
    assert r._calculus_task_check(problem, bad) == "fail"
    assert r._bounded_task_check(problem, good) == "pass"
    assert r._bounded_task_check(problem, bad) == "fail"
    assert r._calculus_task_check(problem, good[:-2]) == "unknown"


def test_changed_problem_parameter_cannot_reuse_other_integral_answer():
    assert r._calculus_task_check(RADICAL_PROBLEM.replace("x+2", "x+3"), RADICAL_GOOD) == "fail"
    assert r._calculus_task_check(RATIONAL_PROBLEM.replace("4x+5", "4x+6"), RATIONAL_GOOD) == "fail"
    # The public source's disputed answer used an inconsistent inner radical.
    source_bad = RADICAL_GOOD.replace(r"\ln\left(5x+1+\sqrt{25x^2+10x+6}", r"\ln\left(5x+1+\sqrt{(5x+1)^2+1}")
    assert r._calculus_task_check(RADICAL_PROBLEM, source_bad) == "unknown"


def test_original_public_multiline_and_parameterized_inputs_are_bound_in_full():
    assert r._bounded_task_check(ORIGINAL_RADICAL, RADICAL_GOOD) == "pass"
    assert r._bounded_task_check(ORIGINAL_RADICAL, RADICAL_BAD) == "fail"
    assert r._bounded_task_check(ORIGINAL_RATIONAL, RATIONAL_GOOD) == "pass"
    unicode_bad = "- (2x + 9)/(16(x^2 + 2x + 9)) + (7√2/64) arctan((x + 1)/(2√2)) + C"
    assert r._bounded_task_check(ORIGINAL_RATIONAL, unicode_bad) == "fail"
    for old, new in (("M = 4", "M = 3"), ("N = 5", "N = 6"), ("q = 9", "q = 10")):
        assert r._bounded_task_check(ORIGINAL_RATIONAL.replace(old, new), RATIONAL_GOOD) == "fail"


@pytest.mark.parametrize("changed", [
    ORIGINAL_RATIONAL.replace("$M = 4$", "$M > 4$"),
    ORIGINAL_RATIONAL.replace("$M = 4$", "$M = a$"),
    ORIGINAL_RATIONAL.replace(", $N = 5$", ""),
    ORIGINAL_RATIONAL.replace("$N = 5$", "$M = 5$"),
    ORIGINAL_RATIONAL.replace("$m = 2$.", "$m = 2$, $x = 3$."),
    ORIGINAL_RATIONAL.replace("$m = 2$.", "$m = 2$, $z = 3$."),
    ORIGINAL_RATIONAL + " Also find its zero.",
    ORIGINAL_RATIONAL.replace("$m = 2$.", "$m = 2$, x > 0."),
    ORIGINAL_RATIONAL.replace("$m = 2$.", "$m = 2$, where x > 0."),
])
def test_parameter_blocks_must_be_complete_unique_and_only_integer_bindings(changed):
    assert r._bounded_task_check(changed, RATIONAL_GOOD) == "unknown"


@pytest.mark.parametrize("problem,answer", [
    (RADICAL_PROBLEM + " Also find its minimum.", RADICAL_GOOD),
    (RADICAL_PROBLEM + " where x > 0", RADICAL_GOOD),
    (RADICAL_PROBLEM.replace(r"\int ", r"\int_0^1 "), RADICAL_GOOD),
    (RADICAL_PROBLEM.replace("dx", "dy"), RADICAL_GOOD),
    (RADICAL_PROBLEM, RADICAL_GOOD + " for x > 0"),
    (RADICAL_PROBLEM, RADICAL_GOOD.replace("+C", "+C*x+C")),
    ("Find the indefinite integral of 1/x", "ln(x)+C"),
    ("Find the indefinite integral of 1/x", "ln|x|+C"),
    ("Find the indefinite integral of x/sqrt(x^2)", "sqrt(x^2)+C"),
    ("Find the indefinite integral of 1/sqrt(x)", "2*sqrt(x)+C"),
    ("Find the indefinite integral of 0", "ln(-1)+C"),
    ("Find the indefinite integral of 0", "ln(x)-ln(x)+C"),
    ("Find the indefinite integral of 0", "x/x+C"),
    ("Find the indefinite integral of sin(x)", "-cos(x)+C"),
    ("Find the indefinite integral of 1/(x^2-1)", "atan(x)+C"),
    ("Find the indefinite integral of a*x", "a*x^2/2+C"),
    ("Find the indefinite integral of 1", "__import__('os').system('x')+C"),
    ("Find the indefinite integral of 1", "x.__class__+C"),
    ("Find the indefinite integral of 1", "(lambda: 1)()+C"),
    ("Find the indefinite integral of 1", "x^999999+C"),
    ("Find the indefinite integral of 1", "9^9^9+C"),
    ("Find the indefinite integral of 6", "2 3*x+C"),
    ("Find the indefinite integral of 1", "√2x+C"),
    ("Find the indefinite integral of 1", "("*100+"x"+")"*100+"+C"),
    ("Find the indefinite integral of 1", "x"*1201),
])
def test_partial_conditions_domains_and_unsafe_grammar_abstain(problem, answer):
    assert r._calculus_task_check(problem, answer) == "unknown"


def test_rational_derivative_inverse_for_generated_positive_quadratics():
    # F=(a*x+b)/((x+h)^2+k). Its derivative is constructed independently
    # by the quotient rule as a closed polynomial numerator.
    rng = random.Random(910)
    for _ in range(24):
        a, b, h, k = rng.randint(1, 5), rng.randint(-4, 4), rng.randint(-3, 3), rng.randint(1, 8)
        q = f"((x+({h}))^2+{k})"
        numerator = f"-{a}*x^2-{2*b}*x+({a*(h*h+k)-2*b*h})"
        problem = f"Find the indefinite integral of ({numerator})/{q}^2"
        primitive = f"({a}*x+({b}))/{q}"
        assert r._calculus_task_check(problem, primitive + "+C") == "pass"
        # Adding a nonconstant term cannot preserve an antiderivative.
        assert r._calculus_task_check(problem, primitive + "+x+C") == "fail"
        # An arbitrary constant must preserve it exactly.
        assert r._calculus_task_check(problem, primitive + "+17/3+C") == "pass"


def test_generated_radical_and_logarithm_chain_rule():
    for h in (-3, 0, 2):
        for k in (1, 3, 7):
            q = f"((x+({h}))^2+{k})"
            root = f"sqrt({q})"
            assert r._calculus_task_check(f"Find the indefinite integral of (x+({h}))/{root}", root + "+C") == "pass"
            problem = f"Find the indefinite integral of 1/{root}"
            answer = f"ln(x+({h})+{root})+C"
            assert r._calculus_task_check(problem, answer) == "pass"
            assert r._calculus_task_check(problem, "2*" + answer) == "fail"


def test_generated_atan_chain_rule_with_equivalent_constant_radicals():
    for n in (2, 3, 5, 8):
        for h in (-2, 1):
            problem = f"Find the indefinite integral of 1/((x+({h}))^2+{n})"
            answer = f"atan((x+({h}))/sqrt({n}))/sqrt({n})+C"
            assert r._calculus_task_check(problem, answer) == "pass"
    assert r._calculus_task_check("Find the indefinite integral of 1/(x^2+8)", "atan(x/(2*sqrt(2)))/sqrt(8)+C") == "pass"


def test_sturm_proof_rejects_real_zeros_including_repeated_roots():
    for coefficients in ((0, 0, 1), (-1, 0, 1), (1, -2, 1), (0, 0, 0, 0, 1)):
        algebra = r._CalcAlgebra()
        assert algebra.signp(tuple(Fraction(x) for x in coefficients)) == 0
    for coefficients in ((1, 0, 1), (2, 2, 1), (1, 0, 0, 0, 1)):
        algebra = r._CalcAlgebra()
        assert algebra.signp(tuple(Fraction(x) for x in coefficients)) == 1


def test_resource_caps_apply_before_large_expansion():
    algebra = r._CalcAlgebra()
    with pytest.raises(ValueError, match="polynomial bound"):
        algebra.poly([Fraction(1)]*34)
    with pytest.raises(ValueError, match="polynomial bound"):
        algebra.poly([Fraction(2**1025)])
    algebra.operations = 20000
    with pytest.raises(ValueError, match="operation bound"):
        algebra.tick()


def test_small_constant_radical_normalization_is_exact():
    for numerator in range(1, 18):
        for denominator in range(1, 10):
            algebra = r._CalcAlgebra()
            value = algebra.constant(Fraction(numerator, denominator))
            root = algebra.root(value)
            assert algebra.iszero(algebra.add(algebra.multiply(root, root), algebra.neg(value)))
            assert algebra.sign(root) == 1
