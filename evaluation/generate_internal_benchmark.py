"""Generate a deterministic 396-item internal benchmark across 18 math domains.

The benchmark is synthetic and intended for an internal, frozen comparison. It
does not claim independence from model pretraining and must not be presented as
an official competition score.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
from typing import Callable

import sympy as sp
from sympy.ntheory.modular import crt


Builder = Callable[[int], tuple[str, str, str]]
LEVELS = ("intermediate",) * 8 + ("competition",) * 10 + ("challenge",) * 4
SOURCE = "project-authored-synthetic-v1"
LICENSE = "internal-evaluation-only"
SEED = 20260829


def _text(value: object) -> str:
    if isinstance(value, Fraction):
        return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"
    return str(value).replace("**", "^").replace(" ", "")


def _divisor_count(n: int) -> int:
    return int(sp.divisor_count(n))


def _cycle_domain(
    subject: str,
    code: str,
    builders: list[tuple[str, Builder]],
) -> list[dict[str, object]]:
    if len(builders) != 6:
        raise ValueError(f"{subject} must define exactly six template families")
    records = []
    for position in range(22):
        family, builder = builders[position % 6]
        variant = position // 6
        problem, answer, task_type = builder(variant)
        records.append(
            {
                "idx": f"{code}-{position + 1:03d}",
                "problem": problem,
                "answer": answer,
                "subject": subject,
                "task_type": task_type,
                "level": LEVELS[position],
                "source": SOURCE,
                "license": LICENSE,
                "split": "test",
                "template_family": f"{code}-{family}",
                "variant": variant + 1,
            }
        )
    return records


def _abstract_algebra() -> list[dict[str, object]]:
    def additive_order(v: int) -> tuple[str, str, str]:
        n, a = [(84, 30), (90, 42), (96, 36), (105, 45)][v]
        return f"在加法群 Z/{n}Z 中，元素 [{a}] 的阶是多少？", str(n // math.gcd(n, a)), "group_order"

    def hom_count(v: int) -> tuple[str, str, str]:
        m, n = [(36, 48), (45, 60), (56, 70), (72, 90)][v]
        return f"从循环群 C_{m} 到 C_{n} 一共有多少个群同态？", str(math.gcd(m, n)), "homomorphism_count"

    def permutation_order(v: int) -> tuple[str, str, str]:
        cycles = [(6, 10, 15), (8, 9, 12), (7, 14, 18), (9, 10, 16)][v]
        answer = math.lcm(*cycles)
        return f"一个置换的不交循环长度为 {cycles[0]}、{cycles[1]}、{cycles[2]}，求该置换的阶。", str(answer), "permutation"

    def subgroup_count(v: int) -> tuple[str, str, str]:
        n = [360, 420, 504, 630][v]
        return f"循环群 C_{n} 有多少个不同子群？", str(_divisor_count(n)), "subgroup_count"

    def dihedral_center(v: int) -> tuple[str, str, str]:
        n = [15, 18, 21, 24][v]
        answer = 2 if n % 2 == 0 else 1
        return f"设 D_{{2n}} 是阶为 2n 的二面体群。取 n={n}，其中心含多少个元素？", str(answer), "group_center"

    def exact_order(v: int) -> tuple[str, str, str]:
        n, d = [(180, 12), (240, 20), (300, 25), (420, 28)][v]
        return f"在循环群 C_{n} 中，恰好有多少个元素的阶为 {d}？", str(sp.totient(d)), "element_order_count"

    return _cycle_domain("抽象代数", "alg", [("add-order", additive_order), ("hom", hom_count), ("perm", permutation_order), ("subgroups", subgroup_count), ("center", dihedral_center), ("exact-order", exact_order)])


def _number_theory() -> list[dict[str, object]]:
    def crt_problem(v: int) -> tuple[str, str, str]:
        m, n, a, b = [(11, 13, 7, 9), (13, 17, 8, 12), (17, 19, 11, 14), (19, 23, 15, 17)][v]
        value = int(crt([m, n], [a, b])[0])
        return f"求满足 x≡{a} (mod {m}) 且 x≡{b} (mod {n}) 的最小非负整数 x。", str(value), "crt"

    def modular_power(v: int) -> tuple[str, str, str]:
        a, e, m = [(7, 222, 55), (11, 345, 91), (13, 456, 85), (17, 567, 119)][v]
        return f"计算 {a}^{e} 除以 {m} 的余数。", str(pow(a, e, m)), "modular_arithmetic"

    def totient(v: int) -> tuple[str, str, str]:
        n = [756, 840, 924, 990][v]
        return f"计算 Euler 函数 phi({n})。", str(sp.totient(n)), "arithmetic_function"

    def divisor_sum(v: int) -> tuple[str, str, str]:
        n = [360, 540, 720, 900][v]
        return f"求 {n} 的所有正因子之和。", str(sp.divisor_sigma(n)), "divisor_sum"

    def linear_congruence(v: int) -> tuple[str, str, str]:
        a, b, n = [(18, 30, 42), (24, 36, 60), (35, 49, 84), (44, 66, 110)][v]
        g = math.gcd(a, n)
        answer = g if b % g == 0 else 0
        return f"同余方程 {a}x≡{b} (mod {n}) 在模 {n} 意义下有多少个不同解？", str(answer), "linear_congruence"

    def multiplicative_order(v: int) -> tuple[str, str, str]:
        a, n = [(2, 29), (3, 41), (5, 43), (7, 53)][v]
        return f"求 {a} 在模 {n} 乘法群中的阶。", str(sp.n_order(a, n)), "multiplicative_order"

    return _cycle_domain("数论", "nt", [("crt", crt_problem), ("modpow", modular_power), ("phi", totient), ("sigma", divisor_sum), ("lincong", linear_congruence), ("mult-order", multiplicative_order)])


def _linear_algebra() -> list[dict[str, object]]:
    def determinant(v: int) -> tuple[str, str, str]:
        a, b, c = [(3, 4, 5), (4, 6, 7), (5, 7, 9), (6, 8, 11)][v]
        matrix = sp.Matrix([[a, 1, 0], [2, b, 1], [0, 3, c]])
        return f"求矩阵 [[{a},1,0],[2,{b},1],[0,3,{c}]] 的行列式。", str(matrix.det()), "determinant"

    def rank(v: int) -> tuple[str, str, str]:
        a = [2, 3, 5, 7][v]
        matrix = sp.Matrix([[1, a, 0, 1], [0, 1, a, 2], [1, a + 1, a, 3], [2, 2 * a + 1, a, 4]])
        return f"求矩阵 {matrix.tolist()} 的秩。", str(matrix.rank()), "rank"

    def eigenvalues(v: int) -> tuple[str, str, str]:
        a, b = [(5, 2), (7, 3), (9, 4), (12, 5)][v]
        return f"求矩阵 [[{a},{b}],[{b},{a}]] 的两个特征值。", f"{a-b},{a+b}", "eigenvalues"

    def nullity(v: int) -> tuple[str, str, str]:
        rows, cols, rank = [(5, 8, 4), (6, 10, 5), (7, 11, 6), (8, 12, 7)][v]
        return f"线性映射 T:R^{cols}->R^{rows} 的矩阵秩为 {rank}，求 ker(T) 的维数。", str(cols - rank), "rank_nullity"

    def solve_component(v: int) -> tuple[str, str, str]:
        matrices = [sp.Matrix([[2, 1, -1], [1, 3, 2], [3, -1, 1]]), sp.Matrix([[3, 1, 2], [2, 4, -1], [1, -2, 5]]), sp.Matrix([[4, -1, 1], [2, 5, 2], [1, 1, 3]]), sp.Matrix([[5, 2, -1], [1, 4, 2], [2, -1, 6]])]
        solutions = [sp.Matrix([2, -1, 3]), sp.Matrix([-2, 3, 1]), sp.Matrix([1, 2, -2]), sp.Matrix([3, -1, 2])]
        matrix, solution = matrices[v], solutions[v]
        rhs = matrix * solution
        return f"线性方程组 A x=b 中 A={matrix.tolist()}, b={list(rhs)}。求 x 的第二个分量。", str(solution[1]), "linear_system"

    def trace_power(v: int) -> tuple[str, str, str]:
        diagonal, power = [((2, -1, 3), 4), ((1, 3, -2), 5), ((2, 4, -3), 3), ((-1, 5, 2), 4)][v]
        answer = sum(x**power for x in diagonal)
        return f"矩阵 A 可对角化且特征值为 {diagonal}。求 tr(A^{power})。", str(answer), "trace"

    return _cycle_domain("线性代数", "la", [("det", determinant), ("rank", rank), ("eigen", eigenvalues), ("nullity", nullity), ("system", solve_component), ("trace-power", trace_power)])


def _real_analysis() -> list[dict[str, object]]:
    def sequence_limit(v: int) -> tuple[str, str, str]:
        a, b = [(7, 3), (11, 5), (13, 7), (17, 9)][v]
        return f"求极限 lim_(n->∞) (n^2+{a}n+1)/({b}n^2-2n+3)。", f"1/{b}", "sequence_limit"

    def telescoping(v: int) -> tuple[str, str, str]:
        c = [2, 4, 7, 10][v]
        return f"计算级数 sum_(n=1)^∞ 1/((n+{c})(n+{c}+1))。", f"1/{c+1}", "series_sum"

    def radius(v: int) -> tuple[str, str, str]:
        a, p = [(3, 2), (4, 3), (5, 4), (7, 2)][v]
        return f"求幂级数 sum_(n=1)^∞ n^{p} x^n/{a}^n 的收敛半径。", str(a), "power_series"

    def limsup(v: int) -> tuple[str, str, str]:
        c = [3, 5, 8, 13][v]
        return f"设 a_n=(-1)^n+{c}/n，求 limsup a_n。", "1", "limsup"

    def uniform(v: int) -> tuple[str, str, str]:
        denominator = [2, 3, 4, 5][v]
        return f"函数列 f_n(x)=x^n 在闭区间 [0,1/{denominator}] 上是否一致收敛到 0？", "是", "uniform_convergence"

    def improper(v: int) -> tuple[str, str, str]:
        p = [3, 4, 6, 9][v]
        return f"计算反常积分 integral_1^∞ x^(-{p}) dx。", f"1/{p-1}", "improper_integral"

    return _cycle_domain("实分析", "ra", [("seq-limit", sequence_limit), ("telescoping", telescoping), ("radius", radius), ("limsup", limsup), ("uniform", uniform), ("improper", improper)])


def _complex_analysis() -> list[dict[str, object]]:
    def residue(v: int) -> tuple[str, str, str]:
        a, c, d = [(2, 3, -1), (-1, 5, 4), (3, -2, 7), (-2, 7, 1)][v]
        answer = 2 * a + c
        return f"函数 f(z)=(z^2+({c})z+{d})/(z-({a}))^2 在 z={a} 有二阶极点，求其留数。", str(answer), "residue"

    def cauchy_integral(v: int) -> tuple[str, str, str]:
        a, m, radius = [(2, 3, 4), (-1, 4, 3), (3, 2, 5), (1, 6, 2)][v]
        coefficient = a**m
        return f"沿圆 |z|={radius} 逆时针计算 contour_integral z^{m}/(z-({a})) dz。", f"{2*coefficient}*pi*i", "contour_integral"

    def pole_order(v: int) -> tuple[str, str, str]:
        zero, numerator_power, denominator_power = [(1, 2, 7), (-2, 1, 6), (3, 3, 8), (-1, 2, 9)][v]
        order = denominator_power - numerator_power
        return f"函数 (z-({zero}))^{numerator_power}/(z-({zero}))^{denominator_power} 在 z={zero} 处的极点阶数是多少？", str(order), "singularity"

    def zero_count(v: int) -> tuple[str, str, str]:
        n, numerator, denominator = [(7, 1, 2), (9, 1, 3), (11, 2, 5), (13, 3, 7)][v]
        return f"多项式 z^{n}-{numerator}/{denominator} 在单位圆 |z|<1 内有多少个零点（计重数）？", str(n), "zero_count"

    def mobius(v: int) -> tuple[str, str, str]:
        a, z = [(2, 3), (3, 5), (-2, 4), (-3, 2)][v]
        value = Fraction(z - a, 1 - a * z)
        return f"Möbius 变换 T(z)=(z-({a}))/(1-({a})z)，求 T({z})。", _text(value), "mobius_transform"

    def laurent(v: int) -> tuple[str, str, str]:
        m, k = [(7, -2), (8, -3), (9, -1), (10, -4)][v]
        factorial_index = m + k
        return f"求 exp(z)/z^{m} 的 Laurent 展开中 z^{k} 项的系数。", f"1/{math.factorial(factorial_index)}", "laurent_series"

    return _cycle_domain("复分析", "ca", [("residue", residue), ("cauchy", cauchy_integral), ("pole", pole_order), ("zeros", zero_count), ("mobius", mobius), ("laurent", laurent)])


def _calculus() -> list[dict[str, object]]:
    def derivative(v: int) -> tuple[str, str, str]:
        a, b, c, x = [(3, -5, 7, 2), (4, 6, -2, -1), (5, -3, 4, 3), (7, 2, -9, 2)][v]
        answer = 3 * a * x * x + 2 * b * x + c
        return f"设 f(x)={a}x^3+({b})x^2+{c}x-4，计算 f'({x})。", str(answer), "derivative"

    def definite_integral(v: int) -> tuple[str, str, str]:
        a, b, upper = [(3, 2, 2), (5, -1, 3), (2, 7, 4), (4, 3, 5)][v]
        value = Fraction(a * upper**3, 3) + Fraction(b * upper**2, 2)
        return f"计算 integral_0^{upper} ({a}x^2+({b})x) dx。", _text(value), "definite_integral"

    def double_integral(v: int) -> tuple[str, str, str]:
        a, b, c = [(2, 3, 1), (3, 4, 2), (4, 5, -1), (5, 6, 3)][v]
        value = Fraction(a * a * b, 2) + Fraction(a * b * b, 2) + c * a * b
        return f"计算矩形 0<=x<={a}, 0<=y<={b} 上二重积分 integral integral (x+y+{c}) dA。", _text(value), "multiple_integral"

    def directional(v: int) -> tuple[str, str, str]:
        point, direction = [((1, 2), (3, 4)), ((2, -1), (5, 12)), ((-1, 3), (8, 15)), ((3, 2), (7, 24))][v]
        x, y = point
        u, w = direction
        norm = math.hypot(u, w)
        value = Fraction(2 * x * u + 2 * y * w, int(norm))
        return f"f(x,y)=x^2+y^2。在点 ({x},{y}) 沿向量 ({u},{w}) 的单位方向导数是多少？", _text(value), "directional_derivative"

    def constrained(v: int) -> tuple[str, str, str]:
        total = [12, 16, 20, 28][v]
        return f"在 x>=0,y>=0 且 x+y={total} 下，求 xy 的最大值。", str(total * total // 4), "constrained_extremum"

    def taylor(v: int) -> tuple[str, str, str]:
        a, k = [(2, 5), (3, 4), (4, 6), (5, 5)][v]
        value = Fraction(a**k, math.factorial(k))
        return f"求 exp({a}x) 在 x=0 的 Taylor 展开中 x^{k} 的系数。", _text(value), "taylor_series"

    return _cycle_domain("微积分", "cal", [("derivative", derivative), ("integral", definite_integral), ("double", double_integral), ("directional", directional), ("lagrange", constrained), ("taylor", taylor)])


def _ode() -> list[dict[str, object]]:
    def exponential(v: int) -> tuple[str, str, str]:
        a, b, c = [(2, 3, 2), (3, 2, 3), (2, 5, 4), (4, 1, 2)][v]
        return f"初值问题 y'={a}y, y(0)={b}。求 y(ln({c}))。", str(b * c**a), "first_order_ode"

    def linear(v: int) -> tuple[str, str, str]:
        a, forcing, initial, q = [(2, 6, 5, 2), (3, 9, 1, 2), (2, 8, 7, 4), (4, 12, 5, 2)][v]
        steady = Fraction(forcing, a)
        value = steady + (Fraction(initial) - steady) * Fraction(1, q**a)
        return f"解 y'+{a}y={forcing}, y(0)={initial}，求 y(ln({q}))。", _text(value), "linear_ode"

    def oscillator(v: int) -> tuple[str, str, str]:
        omega, a, b = [(2, 3, 5), (3, -2, 4), (4, 1, -3), (5, 6, 2)][v]
        return f"y''+{omega**2}y=0, y(0)={a}, y'(0)={b*omega}。求 y(pi/{2*omega})。", str(b), "second_order_ode"

    def characteristic(v: int) -> tuple[str, str, str]:
        r1, r2 = [(2, -3), (4, -1), (5, 2), (7, -2)][v]
        s, p = r1 + r2, r1 * r2
        return f"微分方程 y''-({s})y'+({p})y=0 的两个特征根是什么？", f"{r1},{r2}", "characteristic_equation"

    def logistic(v: int) -> tuple[str, str, str]:
        rate, capacity, q = [(2, 100, 3), (3, 120, 2), (4, 80, 4), (5, 150, 2)][v]
        value = Fraction(capacity * q, 1 + q)
        return f"y'={rate}y(1-y/{capacity}), y(0)={capacity//2}。求 y(ln({q})/{rate})。", _text(value), "logistic_ode"

    def euler(v: int) -> tuple[str, str, str]:
        r1, r2 = [(2, 5), (-2, 3), (4, 7), (-3, 2)][v]
        a = 1 - (r1 + r2)
        b = r1 * r2
        return f"Euler 方程 x^2 y''+({a})x y'+({b})y=0 的两个幂函数指数 m 是什么？", f"{r1},{r2}", "euler_ode"

    return _cycle_domain("微分方程", "ode", [("exp", exponential), ("linear", linear), ("oscillator", oscillator), ("characteristic", characteristic), ("logistic", logistic), ("euler", euler)])


def _pde() -> list[dict[str, object]]:
    def classify(v: int) -> tuple[str, str, str]:
        a, c = [(3, 5), (4, -7), (6, 2), (-5, -3)][v]
        answer = "椭圆型" if a * c > 0 else "双曲型"
        return f"对二阶 PDE {a}u_xx+({c})u_yy=0 进行分类。", answer, "pde_classification"

    def heat(v: int) -> tuple[str, str, str]:
        n, q = [(3, 2), (5, 3), (7, 4), (9, 5)][v]
        return f"u(x,t)=sin({n}x)exp(-{n*n}t)。求 u(pi/{2*n}, ln({q})/{n*n})。", f"1/{q}", "heat_equation"

    def transport(v: int) -> tuple[str, str, str]:
        c, x, t, a = [(2, 5, 2, 3), (3, 10, 2, 1), (-2, 1, 3, 4), (4, 15, 3, 2)][v]
        value = (x - c * t) ** 2 + a
        return f"u_t+({c})u_x=0, u(x,0)=x^2+{a}。求 u({x},{t})。", str(value), "transport_equation"

    def wave_speed(v: int) -> tuple[str, str, str]:
        speed = [3, 5, 7, 11][v]
        return f"波动方程 u_tt={speed*speed}u_xx 的传播速度是多少？", str(speed), "wave_equation"

    def eigenvalue(v: int) -> tuple[str, str, str]:
        m, n = [(2, 3), (3, 5), (4, 7), (5, 8)][v]
        return f"在区域 (0,pi)^2 上，Dirichlet 算子 -Delta 对应特征函数 sin({m}x)sin({n}y) 的特征值是多少？", str(m*m+n*n), "pde_eigenvalue"

    def harmonic_parameter(v: int) -> tuple[str, str, str]:
        cross = [3, 5, 8, 13][v]
        return f"要使 u(x,y)=x^2+{cross}xy+b y^2 为调和函数，参数 b 应取何值？", "-1", "laplace_equation"

    return _cycle_domain("偏微分方程", "pde", [("classify", classify), ("heat", heat), ("transport", transport), ("wave", wave_speed), ("eigen", eigenvalue), ("harmonic", harmonic_parameter)])


def _functional_analysis() -> list[dict[str, object]]:
    def diagonal_norm(v: int) -> tuple[str, str, str]:
        diagonal = [(2, -5, 3, 1), (7, -2, 4, 6), (-8, 3, 5, 1), (4, -9, 2, 7)][v]
        return f"R^4 取 Euclidean 范数。对角算子 T=diag{diagonal} 的算子范数是多少？", str(max(abs(x) for x in diagonal)), "operator_norm"

    def functional_norm(v: int) -> tuple[str, str, str]:
        coeffs = [(3, 4), (5, 12), (8, 15), (7, 24)][v]
        answer = int(math.hypot(*coeffs))
        return f"在 Euclidean 空间 R^2 上，线性泛函 f(x,y)={coeffs[0]}x+{coeffs[1]}y 的范数是多少？", str(answer), "dual_norm"

    def projection(v: int) -> tuple[str, str, str]:
        dimension = [3, 4, 7, 10][v]
        rank = [1, 2, 3, 5][v]
        return f"Hilbert 空间 R^{dimension} 中一个非零正交投影 P 的秩为 {rank}。求 ||P||。", "1", "projection"

    def spectral_radius(v: int) -> tuple[str, str, str]:
        diagonal = [(2, -3, 5), (-7, 4, 6), (8, -2, 1), (3, -9, 7)][v]
        return f"有限维算子 A=diag{diagonal} 的谱半径是多少？", str(max(abs(x) for x in diagonal)), "spectral_radius"

    def fixed_point(v: int) -> tuple[str, str, str]:
        numerator, denominator, b = [(1, 3, 4), (2, 5, 6), (-1, 4, 5), (3, 7, 8)][v]
        value = Fraction(b * denominator, denominator - numerator)
        return f"压缩映射 T(x)=({numerator}/{denominator})x+{b} 在 R 上的唯一不动点是多少？", _text(value), "contraction_mapping"

    def vector_norm(v: int) -> tuple[str, str, str]:
        vector, p = [((2, -3, 5), 1), ((4, -7, 2), "inf"), ((3, 4, 12), 2), ((6, -2, 9), 1)][v]
        if p == 1:
            answer = sum(abs(x) for x in vector)
        elif p == "inf":
            answer = max(abs(x) for x in vector)
        else:
            answer = int(math.sqrt(sum(x*x for x in vector)))
        return f"求向量 {vector} 的 l_{p} 范数。", str(answer), "banach_norm"

    return _cycle_domain("泛函分析", "fa", [("diag-norm", diagonal_norm), ("functional", functional_norm), ("projection", projection), ("radius", spectral_radius), ("fixed-point", fixed_point), ("lp", vector_norm)])


def _measure_theory() -> list[dict[str, object]]:
    def union_measure(v: int) -> tuple[str, str, str]:
        a, b, c, d = [(0, 5, 3, 9), (-2, 4, 1, 7), (1, 8, 5, 12), (-5, 2, -1, 6)][v]
        measure = max(b, d) - min(a, c)
        return f"求区间 [{a},{b}]∪[{c},{d}] 的 Lebesgue 测度。", str(measure), "measure_union"

    def step_integral(v: int) -> tuple[str, str, str]:
        a, b, c, d = [(2, 3, -1, 5), (4, 2, 3, 4), (-2, 6, 5, 3), (7, 2, -3, 8)][v]
        value = a * b + c * d
        return f"函数 f 在集合 A 上恒为 {a}、在不交集合 B 上恒为 {c}，且 mu(A)={b}, mu(B)={d}；其他处为0。求 integral f dmu。", str(value), "lebesgue_integral"

    def indicator_norm(v: int) -> tuple[str, str, str]:
        p, root = [(2, 3), (3, 2), (4, 3), (2, 5)][v]
        measure = root**p
        return f"若 mu(E)={measure}，求指标函数 1_E 的 L^{p} 范数。", str(root), "lp_norm"

    def dominated_limit(v: int) -> tuple[str, str, str]:
        power = [2, 3, 5, 8][v]
        return f"在 [0,1] 上令 f_n(x)=x^({power}n)。求 lim_(n->∞) integral_0^1 f_n(x) dx。", "0", "dominated_convergence"

    def variation(v: int) -> tuple[str, str, str]:
        a, b, length_a, length_b = [(3, -2, 4, 5), (-4, 5, 3, 2), (6, -1, 2, 7), (-3, 8, 5, 1)][v]
        value = abs(a) * length_a + abs(b) * length_b
        return f"有符号测度的密度在不交集合 A、B 上分别为 {a}、{b}，mu(A)={length_a}, mu(B)={length_b}。求其全变差测度 |nu|(A∪B)。", str(value), "signed_measure"

    def product_measure(v: int) -> tuple[str, str, str]:
        a, b, c, d = [(2, 7, 3, 9), (-1, 5, 4, 10), (3, 11, -2, 6), (-4, 3, 2, 12)][v]
        return f"求矩形 [{a},{b}]×[{c},{d}] 的二维 Lebesgue 测度。", str((b-a)*(d-c)), "product_measure"

    return _cycle_domain("测度积分", "mi", [("union", union_measure), ("step", step_integral), ("indicator", indicator_norm), ("dct", dominated_limit), ("variation", variation), ("product", product_measure)])


def _geometry() -> list[dict[str, object]]:
    def heron(v: int) -> tuple[str, str, str]:
        ax, ay, bx, by = [(4, 2, 1, 7), (6, 1, -2, 5), (8, 3, 2, 9), (10, -2, 4, 8)][v]
        area = Fraction(abs(ax * by - ay * bx), 2)
        return f"三角形顶点为 O=(0,0), A=({ax},{ay}), B=({bx},{by})，求其面积。", _text(area), "triangle_area"

    def inradius(v: int) -> tuple[str, str, str]:
        scale = [2, 4, 6, 8][v]
        return f"直角三角形两直角边为 {3*scale} 和 {4*scale}，求内切圆半径。", str(scale), "inradius"

    def chord(v: int) -> tuple[str, str, str]:
        radius, distance, half = [(5, 3, 4), (13, 5, 12), (17, 8, 15), (25, 7, 24)][v]
        return f"半径为 {radius} 的圆中，一条弦到圆心距离为 {distance}，求弦长。", str(2*half), "circle_chord"

    def polygon_angle(v: int) -> tuple[str, str, str]:
        n = [9, 12, 15, 18][v]
        angle = Fraction((n - 2) * 180, n)
        return f"正 {n} 边形的一个内角是多少度？", _text(angle), "regular_polygon"

    def tangent(v: int) -> tuple[str, str, str]:
        tangent, secant_external = [(12, 8), (15, 9), (20, 16), (24, 18)][v]
        whole = tangent*tangent // secant_external
        return f"从圆外一点引切线和割线。切线长 {tangent}，割线外段长 {secant_external}，求割线全长。", str(whole), "power_of_point"

    def ellipse(v: int) -> tuple[str, str, str]:
        a, b, c = [(5, 3, 4), (13, 5, 12), (17, 8, 15), (25, 7, 24)][v]
        return f"椭圆 x^2/{a*a}+y^2/{b*b}=1 的离心率是多少？", f"{c}/{a}", "conic_section"

    return _cycle_domain("几何", "geo", [("heron", heron), ("inradius", inradius), ("chord", chord), ("polygon", polygon_angle), ("tangent", tangent), ("ellipse", ellipse)])


def _differential_geometry() -> list[dict[str, object]]:
    def parabola_curvature(v: int) -> tuple[str, str, str]:
        a = [2, 3, 5, 7][v]
        return f"平面曲线 y={a}x^2 在 x=0 处的曲率是多少？", str(2*a), "curve_curvature"

    def sphere_gaussian(v: int) -> tuple[str, str, str]:
        radius = [2, 3, 5, 7][v]
        return f"半径为 {radius} 的球面 Gaussian 曲率是多少？", f"1/{radius*radius}", "gaussian_curvature"

    def cylinder_mean(v: int) -> tuple[str, str, str]:
        radius = [2, 4, 5, 8][v]
        return f"取主曲率绝对值的平均，半径为 {radius} 的圆柱面平均曲率是多少？", f"1/{2*radius}", "mean_curvature"

    def helix_curvature(v: int) -> tuple[str, str, str]:
        a, b = [(3, 4), (5, 12), (8, 15), (7, 24)][v]
        return f"螺线 r(t)=({a}cos t,{a}sin t,{b}t) 的曲率是多少？", f"{a}/{a*a+b*b}", "space_curve_curvature"

    def helix_torsion(v: int) -> tuple[str, str, str]:
        a, b = [(3, 4), (5, 12), (8, 15), (7, 24)][v]
        return f"螺线 r(t)=({a}cos t,{a}sin t,{b}t) 的挠率是多少？", f"{b}/{a*a+b*b}", "torsion"

    def gauss_bonnet(v: int) -> tuple[str, str, str]:
        genus = [0, 2, 3, 5][v]
        coefficient = 4 * (1 - genus)
        return f"闭可定向曲面的亏格为 {genus}。由 Gauss-Bonnet 定理，total_integral K dA 等于多少？", f"{coefficient}*pi", "gauss_bonnet"

    return _cycle_domain("微分几何", "dg", [("parabola", parabola_curvature), ("sphere", sphere_gaussian), ("cylinder", cylinder_mean), ("helix-k", helix_curvature), ("helix-t", helix_torsion), ("gb", gauss_bonnet)])


def _topology() -> list[dict[str, object]]:
    def abelianization(v: int) -> tuple[str, str, str]:
        genus = [2, 3, 4, 5][v]
        return f"闭可定向亏格 {genus} 曲面的基本群之 Abel 化同构于 Z 的多少次直积？", str(2*genus), "fundamental_group"

    def euler(v: int) -> tuple[str, str, str]:
        genus = [2, 4, 6, 8][v]
        return f"闭可定向亏格 {genus} 曲面的 Euler 示性数是多少？", str(2-2*genus), "euler_characteristic"

    def punctured_line(v: int) -> tuple[str, str, str]:
        points = [3, 5, 8, 13][v]
        return f"从实直线 R 中删去 {points} 个互不相同的点，所得空间有多少个连通分支？", str(points+1), "connected_components"

    def wedge_homology(v: int) -> tuple[str, str, str]:
        circles = [3, 5, 7, 10][v]
        return f"{circles} 个圆在一点楔合所得空间的第一同调群 H_1 是自由 Abel 群 Z 的多少次直积？", str(circles), "homology"

    def degree(v: int) -> tuple[str, str, str]:
        degree = [-3, 4, -5, 7][v]
        return f"映射 f:S^1->S^1, f(z)=z^({degree}) 的拓扑度是多少？", str(degree), "mapping_degree"

    def surface_boundary(v: int) -> tuple[str, str, str]:
        genus, boundaries = [(2, 3), (3, 2), (4, 5), (5, 4)][v]
        return f"亏格 {genus} 且有 {boundaries} 个边界分支的紧致可定向曲面 Euler 示性数是多少？", str(2-2*genus-boundaries), "surface_classification"

    return _cycle_domain("拓扑", "top", [("abelian", abelianization), ("euler", euler), ("components", punctured_line), ("homology", wedge_homology), ("degree", degree), ("boundary", surface_boundary)])


def _algebraic_geometry() -> list[dict[str, object]]:
    def hypersurface_dimension(v: int) -> tuple[str, str, str]:
        ambient = [4, 5, 7, 9][v]
        return f"代数闭域上 A^{ambient} 中由一个非零非单位不可约多项式定义的超曲面维数是多少？", str(ambient-1), "krull_dimension"

    def bezout(v: int) -> tuple[str, str, str]:
        d, e = [(3, 5), (4, 7), (6, 8), (9, 11)][v]
        return f"P^2 中次数分别为 {d} 和 {e} 的两条平面曲线无公共分支。按重数计共有多少个交点？", str(d*e), "bezout"

    def plane_genus(v: int) -> tuple[str, str, str]:
        degree = [5, 6, 8, 10][v]
        genus = (degree-1)*(degree-2)//2
        return f"光滑射影平面曲线次数为 {degree}，求其亏格。", str(genus), "curve_genus"

    def projective_points(v: int) -> tuple[str, str, str]:
        q, dimension = [(2, 4), (3, 3), (5, 2), (7, 3)][v]
        points = (q**(dimension+1)-1)//(q-1)
        return f"有限域 F_{q} 上射影空间 P^{dimension}(F_{q}) 有多少个点？", str(points), "finite_field_points"

    def tangent_space(v: int) -> tuple[str, str, str]:
        point = [(0, 0), (1, 0), (0, 2), (0, 0)][v]
        x, y = point
        dimension = 2 if x == 0 and y == 0 else 1
        return f"仿射曲线 V(xy)⊂A^2 在点 ({x},{y}) 的 Zariski 切空间维数是多少？", str(dimension), "zariski_tangent"

    def rational_normal(v: int) -> tuple[str, str, str]:
        dimension = [3, 4, 6, 8][v]
        return f"P^{dimension} 中有理正规曲线的次数是多少？", str(dimension), "variety_degree"

    return _cycle_domain("代数几何", "ag", [("hypersurface", hypersurface_dimension), ("bezout", bezout), ("genus", plane_genus), ("points", projective_points), ("tangent", tangent_space), ("rnc", rational_normal)])


def _operations_research() -> list[dict[str, object]]:
    def lp(v: int) -> tuple[str, str, str]:
        a, b, capacity = [(5, 8, 17), (9, 4, 23), (7, 11, 19), (13, 6, 29)][v]
        optimum = max(a, b)*capacity
        return f"线性规划 max {a}x+{b}y，约束 x+y<={capacity}, x>=0,y>=0。求最优目标值。", str(optimum), "linear_programming"

    def shortest_path(v: int) -> tuple[str, str, str]:
        edges = [[3, 8, 4, 5, 11], [5, 9, 2, 7, 13], [4, 12, 6, 3, 15], [7, 10, 5, 4, 18]][v]
        sa, sb, ab, at, bt = edges
        answer = min(sa+at, sb+bt, sa+ab+bt, sb+ab+at)
        return f"无向网络边权为 s-a:{sa}, s-b:{sb}, a-b:{ab}, a-t:{at}, b-t:{bt}。求 s 到 t 的最短路长度。", str(answer), "shortest_path"

    def max_flow(v: int) -> tuple[str, str, str]:
        sa, at, sb, bt = [(8, 5, 7, 9), (10, 6, 4, 11), (12, 9, 8, 7), (15, 10, 9, 14)][v]
        answer = min(sa, at)+min(sb, bt)
        return f"网络只有两条内部点不交路径 s-a-t 与 s-b-t，容量依次为 ({sa},{at}) 和 ({sb},{bt})。求最大流。", str(answer), "max_flow"

    def assignment(v: int) -> tuple[str, str, str]:
        matrices = [[[7, 4, 8], [6, 5, 9], [8, 7, 3]], [[9, 2, 7], [6, 4, 3], [5, 8, 1]], [[4, 8, 6], [7, 3, 9], [5, 6, 2]], [[8, 5, 9], [4, 7, 6], [3, 8, 5]]][v]
        answer = min(sum(matrices[i][perm[i]] for i in range(3)) for perm in __import__("itertools").permutations(range(3)))
        return f"三人三任务的成本矩阵为 {matrices}，每人恰做一项且每项恰一人，求最小总成本。", str(answer), "assignment"

    def eoq(v: int) -> tuple[str, str, str]:
        demand, setup, holding, eoq = [(800, 18, 2, 120), (1250, 20, 4, 125), (1800, 25, 2, 300), (2450, 18, 4, 210)][v]
        if 2*demand*setup != holding*eoq*eoq:
            eoq = int(round(math.sqrt(2*demand*setup/holding)))
        return f"EOQ 模型中年需求 D={demand}、每次订购成本 S={setup}、单位年持有成本 H={holding}。求经济订购量 sqrt(2DS/H)，取最接近整数。", str(eoq), "inventory"

    def game(v: int) -> tuple[str, str, str]:
        value, spread = [(3, 5), (-2, 7), (4, 9), (1, 6)][v]
        matrix = [[value+spread, value-spread], [value-spread, value+spread]]
        return f"零和博弈行玩家收益矩阵为 {matrix}。求博弈值。", str(value), "game_theory"

    return _cycle_domain("运筹学", "or", [("lp", lp), ("shortest", shortest_path), ("flow", max_flow), ("assignment", assignment), ("eoq", eoq), ("game", game)])


def _probability() -> list[dict[str, object]]:
    def binomial(v: int) -> tuple[str, str, str]:
        n, k, p_num, p_den = [(8, 3, 1, 2), (10, 4, 1, 3), (12, 2, 1, 4), (9, 5, 2, 3)][v]
        probability = Fraction(math.comb(n,k)*p_num**k*(p_den-p_num)**(n-k), p_den**n)
        return f"X~Binomial({n},{p_num}/{p_den})，求 P(X={k})。", _text(probability), "binomial_probability"

    def hypergeometric(v: int) -> tuple[str, str, str]:
        good, bad, draws, wanted = [(7, 5, 4, 2), (8, 6, 5, 3), (10, 8, 6, 4), (9, 7, 5, 1)][v]
        probability = Fraction(math.comb(good,wanted)*math.comb(bad,draws-wanted), math.comb(good+bad,draws))
        return f"袋中有 {good} 个红球和 {bad} 个蓝球，无放回抽取 {draws} 个，恰有 {wanted} 个红球的概率是多少？", _text(probability), "hypergeometric"

    def bayes(v: int) -> tuple[str, str, str]:
        prevalence, sensitivity, false_positive = [(Fraction(1,10), Fraction(4,5), Fraction(1,5)), (Fraction(1,5), Fraction(3,4), Fraction(1,8)), (Fraction(1,4), Fraction(5,6), Fraction(1,6)), (Fraction(2,5), Fraction(7,8), Fraction(1,4))][v]
        posterior = prevalence*sensitivity/(prevalence*sensitivity+(1-prevalence)*false_positive)
        return f"事件 D 的先验概率为 {_text(prevalence)}，检测在 D 下阳性的概率为 {_text(sensitivity)}，在非 D 下阳性的概率为 {_text(false_positive)}。已知检测阳性，求 P(D|阳性)。", _text(posterior), "bayes"

    def geometric(v: int) -> tuple[str, str, str]:
        p = [Fraction(1,5), Fraction(1,8), Fraction(2,7), Fraction(3,10)][v]
        return f"每次独立试验成功概率为 {_text(p)}，令 X 为首次成功所需试验次数，求 E[X]。", _text(1/p), "geometric_distribution"

    def poisson(v: int) -> tuple[str, str, str]:
        rate = [2, 3, 5, 7][v]
        return f"X~Poisson({rate})，求 P(X=0)。", f"exp(-{rate})", "poisson_distribution"

    def variance(v: int) -> tuple[str, str, str]:
        variances, coefficients = [((2,3),(2,-1)), ((4,5),(3,2)), ((6,7),(-2,4)), ((3,8),(5,-1))][v]
        value = coefficients[0]**2*variances[0]+coefficients[1]**2*variances[1]
        return f"独立随机变量 X,Y 的方差分别为 {variances[0]},{variances[1]}。求 Var({coefficients[0]}X+({coefficients[1]})Y)。", str(value), "variance"

    return _cycle_domain("概率论", "prob", [("binomial", binomial), ("hypergeom", hypergeometric), ("bayes", bayes), ("geometric", geometric), ("poisson", poisson), ("variance", variance)])


def _combinatorics() -> list[dict[str, object]]:
    def derangement(v: int) -> tuple[str, str, str]:
        n = [6, 7, 8, 9][v]
        value = int(sp.subfactorial(n))
        return f"{n} 个元素的错排数 !{n} 是多少？", str(value), "derangement"

    def catalan(v: int) -> tuple[str, str, str]:
        n = [6, 8, 10, 12][v]
        value = math.comb(2*n,n)//(n+1)
        return f"第 {n} 个 Catalan 数 C_{n} 是多少？", str(value), "catalan"

    def onto(v: int) -> tuple[str, str, str]:
        m, k = [(7, 3), (8, 4), (9, 3), (10, 4)][v]
        value = sum((-1)**j*math.comb(k,j)*(k-j)**m for j in range(k+1))
        return f"从一个含 {m} 个元素的集合到一个含 {k} 个元素的集合有多少个满射？", str(value), "surjection"

    def composition(v: int) -> tuple[str, str, str]:
        n, k = [(15, 5), (18, 6), (20, 7), (24, 8)][v]
        return f"整数 {n} 写成 {k} 个正整数之和的有序表示有多少种？", str(math.comb(n-1,k-1)), "composition"

    def necklace(v: int) -> tuple[str, str, str]:
        p = [5, 7, 11, 13][v]
        value = (2**p+2*(p-1))//p
        return f"只考虑旋转等价，用两种颜色给正 {p} 边形顶点着色，有多少种不同项链？", str(value), "burnside"

    def lattice(v: int) -> tuple[str, str, str]:
        n = [7, 9, 11, 13][v]
        value = math.comb(2*n,n)//(n+1)
        return f"从 (0,0) 到 ({n},{n}) 只向右或向上，且路径从不越过直线 y=x 的路径数是多少？", str(value), "lattice_path"

    return _cycle_domain("组合", "comb", [("derangement", derangement), ("catalan", catalan), ("onto", onto), ("composition", composition), ("necklace", necklace), ("lattice", lattice)])


def _discrete_math() -> list[dict[str, object]]:
    def spanning_trees(v: int) -> tuple[str, str, str]:
        n = [5, 6, 7, 8][v]
        return f"完全图 K_{n} 有多少棵生成树？", str(n**(n-2)), "spanning_tree"

    def planar_faces(v: int) -> tuple[str, str, str]:
        vertices, edges = [(12, 20), (15, 27), (18, 32), (25, 44)][v]
        return f"一个连通平面图有 {vertices} 个顶点、{edges} 条边，求包括外部面在内的面数。", str(edges-vertices+2), "planar_graph"

    def bipartite_edges(v: int) -> tuple[str, str, str]:
        vertices, degree = [(14, 5), (18, 7), (24, 9), (30, 11)][v]
        return f"一个简单无向正则图有 {vertices} 个顶点，每个顶点度数为 {degree}。由握手定理求边数。", str(vertices*degree//2), "graph_edges"

    def cycle_chromatic(v: int) -> tuple[str, str, str]:
        n = [9, 12, 15, 20][v]
        return f"循环图 C_{n} 的色数是多少？", "2" if n%2==0 else "3", "graph_coloring"

    def boolean_functions(v: int) -> tuple[str, str, str]:
        n = [3, 4, 5, 6][v]
        return f"{n} 个 Boolean 变量上一共有多少个不同 Boolean 函数？", str(2**(2**n)), "boolean_function"

    def linear_extensions(v: int) -> tuple[str, str, str]:
        a, b = [(4, 5), (6, 7), (8, 9), (10, 12)][v]
        return f"一个偏序集是不相交的两条链，其长度分别为 {a} 和 {b}。共有多少个线性扩张？", str(math.comb(a+b,a)), "poset"

    return _cycle_domain("离散数学", "dm", [("trees", spanning_trees), ("faces", planar_faces), ("bipartite", bipartite_edges), ("chromatic", cycle_chromatic), ("boolean", boolean_functions), ("poset", linear_extensions)])


DOMAIN_GENERATORS = (
    _abstract_algebra,
    _number_theory,
    _linear_algebra,
    _real_analysis,
    _complex_analysis,
    _calculus,
    _ode,
    _pde,
    _functional_analysis,
    _measure_theory,
    _geometry,
    _differential_geometry,
    _topology,
    _algebraic_geometry,
    _operations_research,
    _probability,
    _combinatorics,
    _discrete_math,
)


def generate_records() -> list[dict[str, object]]:
    records = [record for generator in DOMAIN_GENERATORS for record in generator()]
    records.sort(
        key=lambda record: hashlib.sha256(
            f"{SEED}:{record['idx']}".encode("utf-8")
        ).digest()
    )
    return records


def dataset_sha256(records: list[dict[str, object]]) -> str:
    serialized = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in records)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    records = generate_records()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        for item in records:
            file.write(json.dumps(item, ensure_ascii=False) + "\n")
    digest = dataset_sha256(records)
    if args.manifest:
        manifest = {
            "name": "internal-university-math-v1",
            "description": "Synthetic internal benchmark; not an official or pretraining-independent score.",
            "items": len(records),
            "domains": len(DOMAIN_GENERATORS),
            "items_per_domain": 22,
            "template_families_per_domain": 6,
            "seed": SEED,
            "sha256": digest,
            "source": SOURCE,
            "license": LICENSE,
            "split": "test",
        }
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"items": len(records), "sha256": digest}, ensure_ascii=False))


if __name__ == "__main__":
    main()
