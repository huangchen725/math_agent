import pytest

from task_router import analyze_task


@pytest.mark.parametrize(
    ("problem", "kind"),
    [
        ("计算 1+1", "expression"),
        ("计算 3^100 除以 7 的余数", "modular_power"),
        ("计算组合数 C(10,3)", "binomial"),
        ("求矩阵 [[1,2],[3,4]] 的行列式", "matrix_determinant"),
        ("求函数 f(x)=x^3 的导数", "derivative"),
        ("计算不定积分 ∫ 2*x dx", "integral"),
        ("求 lim_{x->0} sin(x)/x", "limit"),
        ("求函数 f(z)=1/(z-1) 在 z=1 处的留数", "residue"),
        ("解方程 x^2=4 的所有实根", "equation_solutions"),
    ],
)
def test_strict_direct_tasks_receive_a_verification_plan(problem, kind):
    analysis = analyze_task(problem)

    assert analysis.confidence == 1.0
    assert analysis.verification_plan is not None
    assert analysis.verification_plan.kind == kind


@pytest.mark.parametrize(
    "problem",
    [
        "证明 C(10,3)=120",
        "解方程 x^2=4",
        "解方程 x^2=4 的所有整数解",
        r"Find the maximum value of $\int_0^y x^2\,dx$ for 0 <= y <= 1.",
        "计算 integral_0^2 (3*x^2+2*x) dx",
        "计算 x+x",
        "已知矩阵 [[1,2],[3,4]] 的行列式为 -2，求它的特征值。",
    ],
)
def test_ambiguous_proof_or_constrained_tasks_do_not_receive_a_plan(problem):
    assert analyze_task(problem).verification_plan is None


def test_router_reports_multiple_broad_labels_without_forcing_a_verifier():
    analysis = analyze_task("证明这个概率极限存在")

    assert analysis.task_types == ("proof", "limit", "probability")
    assert analysis.reason == "proof_blocked"
    assert not analysis.deterministically_verifiable
