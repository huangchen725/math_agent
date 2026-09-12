"""Independent exact oracles and adversarial bounds for solver-v2 arithmetic."""

from fractions import Fraction
import itertools
import json
import math
import random

import pytest

import user_agent


execute = user_agent._v2_execute_calculation
complete = user_agent._v2_complete_task_check


def var(name):
    return {"var": name}


def expr(op, *args):
    return {"op": op, "args": list(args)}


def ok(task):
    result = execute(task)
    assert result["status"] == "ok", result
    assert result["scope"] == "subtask"
    assert result["detail"] == "exact_declared_task_only"
    # Results must actually survive plain JSON, including booleans and families.
    assert json.loads(json.dumps(result)) == result
    return result["value"]


def polynomial_at(value, values):
    if isinstance(value, str):
        return Fraction(value)
    result = Fraction(0)
    for term in value["terms"]:
        result += Fraction(term["coefficient"]) * math.prod(
            Fraction(values[name]) ** power
            for name, power in zip(value["variables"], term["powers"])
        )
    return result


def test_exact_historical_integral_and_whole_task_binding():
    integrand = expr("add", var("x"), expr("mul", 2, var("y"), var("z")))
    task = {
        "op": "integrate_polynomial", "variables": ["x", "y", "z"], "expr": integrand,
        "bounds": [
            {"var": "z", "lower": 0, "upper": expr("sub", expr("sub", 5, var("x")), var("y"))},
            {"var": "y", "lower": 0, "upper": var("x")},
            {"var": "x", "lower": 0, "upper": 1},
        ],
    }
    assert ok(task) == "439/120"
    problem = r"Evaluate \int\int\int_E (x+2*y*z) dV, E={(x,y,z)|0<=x<=1,0<=y<=x,0<=z<=5-x-y}."
    assert complete(problem, "439/120") == "pass"
    assert complete(problem, "41/30") == "fail"
    assert complete(problem, "473/120") == "fail"
    assert complete(problem.replace("5-x-y", "6-x-y"), "439/120") == "fail"
    assert complete(problem + " Also find the centroid.", "439/120") == "unknown"
    assert complete(problem.replace("5-x-y", "x-y-1"), "439/120") == "unknown"
    assert complete(problem.replace("0<=y<=x", "0<=y<=x*x"), "439/120") == "unknown"
    assert complete(problem.replace("0<=x<=1", "2<=x<=1"), "0") == "unknown"


def test_actual_historical_tex_problem_is_bound_without_dropping_conditions():
    problem = r"Evaluate $\int\int\int_{E}{(x+2 \cdot y \cdot z) \, dV}$, where $E = \left\{(x,y,z) | 0 \le x \le 1, 0 \le y \le x, 0 \le z \le 5-x-y \right\}$."
    assert complete(problem, "439/120") == "pass"
    assert complete(problem, "473/120") == "fail"
    assert complete(problem, "41/30") == "fail"
    assert complete(problem.replace("5-x-y", "6-x-y"), "439/120") == "fail"
    assert complete(problem.replace("5-x-y", "5-x-y, x+y+z<=1"), "439/120") == "unknown"
    assert complete(problem + " Find the centroid also.", "439/120") == "unknown"
    assert complete(problem.replace(r"\cdot", r"\wrong"), "439/120") == "unknown"
    assert complete(problem.replace(r"\le", "<"), "439/120") == "unknown"


@pytest.mark.parametrize("answer", [
    r"\frac{439}{120}", "$439/120$", r"\(439/120\)", r"\[439/120\]", "$$439/120$$",
    r"$\frac{439}{120}$", r"\(\frac{439}{120}\)", r"\dfrac{439}{120}",
    r"\tfrac{ 439 }{ 120 }", "(700-295+34)/120", r"-\frac{-439}{120}",
])
def test_complete_historical_integral_accepts_only_complete_exact_answer_wrappers(answer):
    problem = r"Evaluate $\int\int\int_{E}{(x+2 \cdot y \cdot z) \, dV}$, where $E = \left\{(x,y,z) | 0 \le x \le 1, 0 \le y \le x, 0 \le z \le 5-x-y \right\}$."
    assert complete(problem, answer) == "pass"
    assert complete(problem, r"\frac{473}{120}") == "fail"
    assert complete(problem, r"$\frac{41}{30}$") == "fail"
    assert complete(problem, answer + "; x>0") == "unknown"
    assert complete(problem, answer + "; second answer=7") == "unknown"


@pytest.mark.parametrize("answer", [r"\frac{439}{0}", r"\(439/120$", "$439/120", r"\frac{439}{120}+C", "439/120 or 17", r"\frac{439}{120} for x>0"])
def test_malformed_or_conditioned_numeric_answers_do_not_become_whole_task_certificates(answer):
    assert complete("Calculate 439/120", answer) == "unknown"


@pytest.mark.parametrize("powers", list(itertools.product(range(3), repeat=3)))
def test_simplex_integrals_against_factorial_volume_oracle(powers):
    # Dirichlet simplex moment: integral x^a y^b z^c = a!b!c!/(a+b+c+3)!.
    terms = [expr("pow", var(name), power) for name, power in zip("xyz", powers)]
    value = ok({
        "op": "integrate_polynomial", "variables": list("xyz"), "expr": expr("mul", *terms),
        "bounds": [
            {"var": "z", "lower": 0, "upper": expr("sub", expr("sub", 1, var("x")), var("y"))},
            {"var": "y", "lower": 0, "upper": expr("sub", 1, var("x"))},
            {"var": "x", "lower": 0, "upper": 1},
        ],
    })
    expected = Fraction(math.prod(math.factorial(n) for n in powers), math.factorial(sum(powers) + 3))
    assert Fraction(value) == expected


def test_oriented_integral_is_distinct_from_geometric_region_certificate():
    task = {"op": "integrate_polynomial", "variables": ["x"], "expr": 1,
            "bounds": [{"var": "x", "lower": 2, "upper": -3}]}
    assert ok(task) == "-5"
    assert complete(r"Evaluate \int\int\int_E 1 dV, E={(x,y,z)|2<=x<=1,0<=y<=1,0<=z<=1}.", "-1") == "unknown"


def test_polynomial_integral_additivity_and_fundamental_theorem():
    random_source = random.Random(461)
    for _ in range(40):
        coefficients = [random_source.randrange(-5, 6) for _ in range(4)]
        original = expr("add", *[expr("mul", coefficient, expr("pow", var("x"), i)) for i, coefficient in enumerate(coefficients)])
        antiderivative = expr("add", *[expr("mul", str(Fraction(coefficient, i + 1)), expr("pow", var("x"), i + 1)) for i, coefficient in enumerate(coefficients)])
        derivative = ok({"op": "differentiate", "variables": ["x"], "expr": antiderivative, "var": "x"})
        lower, middle, upper = sorted(random_source.sample(range(-4, 5), 3))
        def integrate(a, b):
            return Fraction(ok({"op": "integrate_polynomial", "variables": ["x"], "expr": original,
                                "bounds": [{"var": "x", "lower": a, "upper": b}]}))
        assert integrate(lower, upper) == integrate(lower, middle) + integrate(middle, upper)
        for point in (-2, 0, 3):
            assert polynomial_at(derivative, {"x": point}) == sum(c * point ** i for i, c in enumerate(coefficients))


def test_polynomial_bounds_are_subtask_capability_without_region_proof():
    task = {"op": "integrate_polynomial", "variables": ["x", "y"], "expr": 1,
            "bounds": [{"var": "y", "lower": 0, "upper": expr("pow", var("x"), 2)},
                       {"var": "x", "lower": 0, "upper": 1}]}
    assert ok(task) == "1/3"
    task["bounds"] = task["bounds"][:1]
    value = ok(task)
    assert polynomial_at(value, {"x": -3, "y": 7}) == 9


def test_unknown_denominator_domains_are_never_cancelled_into_certificates():
    cancellation = expr("div", var("x"), var("x"))
    for operation in ("polynomial", "evaluate", "root_check"):
        task = {"op": operation, "variables": ["x"], "expr": cancellation}
        if operation == "root_check":
            task["values"] = {"x": 0}
        assert execute(task)["status"] == "unknown"


def test_simultaneous_substitution_does_not_rewrite_replacements():
    value = ok({"op": "substitute", "variables": ["x", "y"],
                "expr": expr("sub", var("x"), var("y")),
                "values": {"x": var("y"), "y": var("x")}})
    assert polynomial_at(value, {"x": 2, "y": 7}) == 5


def test_root_check_keeps_partial_binding_unknown():
    task = {"op": "root_check", "variables": ["x", "y"], "expr": expr("sub", var("x"), var("y")), "values": {"x": 2}}
    assert execute(task)["status"] == "unknown"
    task["values"]["y"] = 2
    assert ok(task) == {"is_root": True}
    task["values"]["y"] = 3
    assert ok(task) == {"is_root": False}


def test_polynomial_identity_has_zero_representation_and_scalar_evaluation():
    identity = expr("sub", expr("pow", expr("add", var("x"), var("y")), 2),
                    expr("add", expr("pow", var("x"), 2), expr("mul", 2, var("x"), var("y")), expr("pow", var("y"), 2)))
    assert ok({"op": "polynomial", "variables": ["x", "y"], "expr": identity}) == "0"
    assert ok({"op": "evaluate", "variables": ["x"], "expr": expr("add", var("x"), "1/2"), "values": {"x": 2}}) == "5/2"


def determinant_by_permutations(matrix):
    size = len(matrix)
    total = Fraction(0)
    for permutation in itertools.permutations(range(size)):
        inversions = sum(permutation[i] > permutation[j] for i in range(size) for j in range(i + 1, size))
        total += (-1) ** inversions * math.prod(Fraction(matrix[i][permutation[i]]) for i in range(size))
    return total


@pytest.mark.parametrize("size", range(1, 6))
def test_matrix_determinant_against_permutation_oracle(size):
    source = random.Random(701 + size)
    for _ in range(15):
        matrix = [[source.randrange(-3, 4) for _ in range(size)] for _ in range(size)]
        expected = determinant_by_permutations(matrix)
        assert Fraction(ok({"op": "matrix_det", "matrix": matrix})) == expected
        rank = ok({"op": "matrix_rank", "matrix": matrix})
        assert (rank == size) == bool(expected)


def test_linear_solve_certificates_cover_unique_affine_and_inconsistent():
    for matrix, rhs in [([[2, 1], [1, -1]], [5, 1]), ([[1, 2, 3], [2, 4, 6]], [4, 8]), ([[1, 0], [0, 1], [1, 1]], [2, 3, 5])]:
        value = ok({"op": "matrix_solve", "matrix": matrix, "rhs": rhs})
        particular = list(map(Fraction, value["particular"]))
        for row, expected in zip(matrix, rhs):
            assert sum(a * b for a, b in zip(row, particular)) == expected
        for vector in value["nullspace_basis"]:
            numbers = list(map(Fraction, vector))
            assert any(numbers)
            assert all(sum(a * b for a, b in zip(row, numbers)) == 0 for row in matrix)
        rank = ok({"op": "matrix_rank", "matrix": matrix})
        assert len(value["nullspace_basis"]) == len(matrix[0]) - rank
    assert ok({"op": "matrix_solve", "matrix": [[1, 2], [2, 4]], "rhs": [3, 7]}) == {"solution": "inconsistent"}
    assert ok({"op": "matrix_solve", "matrix": [[0, 0]], "rhs": [0]}) == {
        "solution": "affine_family", "particular": ["0", "0"], "nullspace_basis": [["1", "0"], ["0", "1"]],
    }


def test_rational_linear_solutions_match_constructed_rhs_and_row_invariants():
    source = random.Random(5713)
    for _ in range(35):
        # Upper triangular nonzero diagonal yields a known unique solution.
        matrix = [[Fraction(source.randrange(-4, 5), source.randrange(1, 8)) if column >= row else Fraction(0)
                   for column in range(4)] for row in range(4)]
        for row in range(4):
            if not matrix[row][row]:
                matrix[row][row] = Fraction(1, 3)
        solution = [Fraction(source.randrange(-7, 8), source.randrange(1, 7)) for _ in range(4)]
        rhs = [sum(a * b for a, b in zip(row, solution)) for row in matrix]
        # Add a multiple of one row to another, preserving both rank and solution.
        matrix[3] = [a + 2 * b for a, b in zip(matrix[3], matrix[0])]
        rhs[3] += 2 * rhs[0]
        wire = [[str(value) for value in row] for row in matrix]
        result = ok({"op": "matrix_solve", "matrix": wire, "rhs": list(map(str, rhs))})
        assert result["solution"] == "unique"
        assert list(map(Fraction, result["particular"])) == solution
        assert ok({"op": "matrix_rank", "matrix": wire}) == 4
        assert Fraction(ok({"op": "matrix_det", "matrix": wire})) == determinant_by_permutations(matrix)


def test_eigenpair_requires_nonzero_vector_and_checks_all_components():
    task = {"op": "matrix_eigenpair", "matrix": [[2, 0], [0, 3]], "vector": [1, 0], "eigenvalue": 2}
    assert ok(task) == {"valid": True, "residual": ["0", "0"]}
    task["vector"] = [0, 0]
    assert ok(task)["valid"] is False
    task["vector"] = [1, 1]
    assert ok(task) == {"valid": False, "residual": ["0", "1"]}


def test_finite_sum_and_integer_root_enumeration_have_precise_scope():
    for upper in range(15):
        value = ok({"op": "finite_sum", "variables": ["k"], "expr": expr("pow", var("k"), 3), "var": "k", "lower": 0, "upper": upper})
        assert Fraction(value) == (upper * (upper + 1) // 2) ** 2
    task = {"op": "enumerate_polynomial_roots", "variables": ["x"], "expr": expr("sub", expr("pow", var("x"), 2), 4), "var": "x", "lower": -3, "upper": 3}
    assert ok(task) == {"integer_roots_in_interval": [-2, 2], "lower": -3, "upper": 3}
    task["expr"] = expr("sub", expr("pow", var("x"), 2), 2)
    assert ok(task)["integer_roots_in_interval"] == []  # Does not claim no real roots.


def test_binomial_modular_and_gcd_lcm_number_theory_properties():
    for n in range(1, 25):
        for k in range(1, n):
            actual = int(ok({"op": "binomial", "n": n, "k": k}))
            left = int(ok({"op": "binomial", "n": n - 1, "k": k - 1}))
            right = int(ok({"op": "binomial", "n": n - 1, "k": k}))
            assert actual == left + right
    for a in range(-8, 9):
        for b in range(-8, 9):
            result = ok({"op": "gcd_lcm", "a": a, "b": b})
            gcd, lcm = int(result["gcd"]), int(result["lcm"])
            assert gcd * lcm == abs(a * b)
            assert gcd >= 0 and lcm >= 0
            if gcd:
                assert a % gcd == b % gcd == 0
    for exponent in range(30):
        assert ok({"op": "mod_pow", "base": -7, "exponent": exponent, "modulus": 13}) == str((-7) ** exponent % 13)


@pytest.mark.parametrize("task", [
    {"op": "evaluate", "expr": "__import__('os')"},
    {"op": "evaluate", "expr": {"op": "call", "args": []}},
    {"op": "evaluate", "expr": {"var": "x"}},
    {"op": "evaluate", "expr": True},
    {"op": "evaluate", "expr": 1.5},
    {"op": "evaluate", "expr": "1/0"},
    {"op": "evaluate", "expr": "1e1000000"},
    {"op": "evaluate", "expr": "2**1000000000"},
    {"op": "evaluate", "expr": expr("pow", 2, 1000000000)},
    {"op": "evaluate", "expr": 2 ** 300},
    {"op": "evaluate", "expr": 2, "source_answer": "42"},
    {"op": "polynomial", "variables": ["x", "x"], "expr": var("x")},
    {"op": "polynomial", "variables": ["x", "y", "z", "w"], "expr": 1},
    {"op": "polynomial", "variables": ["__import__"], "expr": 1},
    {"op": "matrix_det", "matrix": [[1, 2], [3]]},
    {"op": "matrix_det", "matrix": [[1, 2]]},
    {"op": "matrix_det", "matrix": [[1] * 9] * 9},
    {"op": "matrix_rank", "matrix": []},
    {"op": "matrix_solve", "matrix": [[1, 2]], "rhs": [1, 2]},
    {"op": "binomial", "n": 1000000, "k": 500000},
    {"op": "mod_pow", "base": 1, "exponent": 2, "modulus": 0},
    {"op": "mod_pow", "base": 1, "exponent": -1, "modulus": 2},
    {"op": "finite_sum", "variables": ["k"], "expr": var("k"), "var": "k", "lower": 0, "upper": 10000000},
    {"op": "integrate_polynomial", "variables": ["x"], "expr": var("x"), "bounds": [{"var": "x", "lower": 0, "upper": var("x")}]},
    {"op": "integrate_polynomial", "variables": ["x", "y"], "expr": var("x"), "bounds": [{"var": "x", "lower": 0, "upper": 1}, {"var": "y", "lower": 0, "upper": var("x")}]},
    {"op": "integrate_polynomial", "variables": ["x"], "expr": var("x"), "bounds": [{"var": "x", "lower": 0, "upper": 1}, {"var": "x", "lower": 0, "upper": 1}]},
])
def test_unsupported_or_oversized_tasks_fail_closed(task):
    result = execute(task)
    assert result == {"status": "unknown", "scope": "subtask", "value": None, "detail": "unsupported_or_resource_bound"}


def test_division_by_zero_is_an_arithmetic_error_without_raw_input_echo():
    assert execute({"op": "evaluate", "expr": expr("div", 1, 0)}) == {
        "status": "error", "scope": "subtask", "value": None, "detail": "undefined_arithmetic",
    }


def test_deep_cyclic_wide_and_combinatorial_inputs_are_bounded():
    cyclic = {"op": "evaluate"}
    cyclic["expr"] = cyclic
    assert execute(cyclic)["status"] == "unknown"
    deep = 1
    for _ in range(100):
        deep = expr("neg", deep)
    assert execute({"op": "evaluate", "expr": deep})["status"] == "unknown"
    assert execute({"op": "evaluate", "expr": expr("add", *([1] * 10000))})["status"] == "unknown"
    exploding = expr("pow", expr("add", var("x"), var("y"), var("z"), 1), 12)
    assert execute({"op": "polynomial", "variables": list("xyz"), "expr": exploding})["status"] == "unknown"
    assert execute({"op": "evaluate", "expr": expr("pow", 2 ** 250, 12)})["status"] == "unknown"


def test_custom_objects_are_rejected_before_methods_are_invoked():
    class Trap(dict):
        def items(self):
            raise AssertionError("untrusted method invoked")
    assert execute(Trap(op="evaluate", expr=1))["status"] == "unknown"
    assert execute({"op": "evaluate", "expr": Trap()})["status"] == "unknown"


@pytest.mark.parametrize("problem,answer", [
    ("Calculate 2^3 + 1/2", "17/2"),
    ("计算 2*(3+4)", "14"),
    ("Evaluate -3/2 + 2/3", "-5/6"),
])
def test_complete_arithmetic_rejects_unbound_extra_requirements(problem, answer):
    assert complete(problem, answer) == "pass"
    assert complete(problem, "0") == "fail"
    assert complete(problem + "; then prove the general case", answer) == "unknown"
    assert complete("Find a number such that " + problem, answer) == "unknown"


def test_complete_checker_never_uses_json_as_original_problem_binding():
    task = {"op": "evaluate", "expr": 42}
    assert ok(task) == "42"
    assert complete(json.dumps(task), "42") == "unknown"
    assert complete("Compute the answer to this hard theorem.", "42") == "unknown"
