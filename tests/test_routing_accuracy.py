"""Zero-API routing regressions and generated lexical invariants."""

import itertools
import random
import string

import pytest

from domain_prompts import detect_domain, domain_keyword_matches
from user_agent import ReasoningAgent


KEYWORDS = ReasoningAgent._DOMAIN_KEYWORDS


@pytest.mark.parametrize("problem", [
    "Express the answer in interval form.",
    "Determine all rational values.",
    "The instruction is to simplify this expression.",
    "Use properties of the natural logarithm.",
    "The experimental study measures the time in min.",
    "For F(x), find the domain and range.",
    "给定函数，求定义域。",
])
def test_historical_generic_substrings_do_not_select_a_topic(problem):
    assert detect_domain(problem, KEYWORDS) == ""


@pytest.mark.parametrize(("problem", "domain"), [
    (r"Find Res(f,0).", "复分析"),
    (r"求留数 \operatorname{Res}_{z=0} f(z)", "复分析"),
    (r"Calculate tr(A).", "线性代数"),
    (r"求矩阵的特征值", "线性代数"),
    ("Find the eigenvalues of these matrices.", "线性代数"),
    (r"Evaluate \int x^2\,dx.", "微积分"),
    ("求∫x²dx", "微积分"),
    ("Find the derivatives and antiderivatives.", "微积分"),
    ("Find the local maxima and local minima.", "微积分"),
    ("Compute the integrals using integration by parts.", "微积分"),
    (r"Compute \lim_{x\to 0} f(x).", "实分析"),
    ("Find the Taylor series. Hint: Differentiate f(x).", "实分析"),
    ("Decide whether the series converges.", "实分析"),
    ("Find the curvature.", "微分几何"),
    ("Compute the fundamental groups.", "拓扑"),
    ("Solve the PDE, a partial differential equation.", "偏微分方程"),
    ("Solve the ordinary differential equation.", "微分方程"),
    ("solve this ode with an initial value", "微分方程"),
    ("Find the probabilities and the expected value.", "概率论"),
    ("Use linear programming and the simplex method.", "运筹学"),
    ("Classify the finite groups.", "抽象代数"),
    ("Find all prime numbers satisfying this congruence.", "数论"),
    ("Let T be a compact operator on a Banach space.", "泛函分析"),
    ("Use dominated convergence for the Lebesgue integral.", "测度积分"),
    ("Compute the volume of the prism.", "几何"),
    ("Describe the affine varieties.", "代数几何"),
    ("Count permutations using inclusion-exclusion.", "组合"),
    ("Count the chromatic numbers of these graphs.", "离散数学"),
    ("使用中国剩余定理计算同余", "数论"),
    ("计算偏微分方程的解", "偏微分方程"),
    ("求群 G 的阶", "抽象代数"),
    ("讨论交换环 R", "抽象代数"),
    ("计算环面的基本群", "拓扑"),
])
def test_bilingual_topic_words_symbols_and_plurals(problem, domain):
    assert detect_domain(problem, KEYWORDS) == domain


def test_generic_ties_abstain_and_specific_phrase_wins():
    # The phrase itself belongs to both topics; dictionary order is no evidence.
    assert detect_domain("边界条件", KEYWORDS) == ""
    assert detect_domain("partial differential equation", KEYWORDS) == "偏微分方程"
    assert domain_keyword_matches("partial differential equation", KEYWORDS) == {
        "偏微分方程": ["partial differential equation"],
    }


def test_generated_english_words_cannot_gain_a_cue_from_an_embedded_abbreviation():
    # Construct the invalid lexical domain directly; no assume/filter, new
    # dependency or unrestricted parser is needed for this bounded property.
    rng = random.Random(20260910)
    custom = {"residue-topic": ["Res"], "trace-topic": ["tr"], "limit-topic": ["lim"]}
    for _ in range(200):
        prefix = "".join(rng.choices(string.ascii_letters, k=rng.randrange(1, 12)))
        suffix = "".join(rng.choices(string.ascii_letters, k=rng.randrange(1, 12)))
        for abbreviation in ("Res", "tr", "lim"):
            assert detect_domain(prefix + abbreviation + suffix, custom) == ""
            assert detect_domain(prefix + abbreviation, custom) == ""
            assert detect_domain(abbreviation + suffix, custom) == ""


def test_case_and_punctuation_preserve_isolated_mathematical_cues():
    for cue, domain in (("Res", "复分析"), ("tr", "线性代数"), ("ODE", "微分方程")):
        for left, right in itertools.product(("", " ", "$", "("), ("", " ", "$", ")")):
            for word in (cue, cue.lower(), cue.upper(), cue.swapcase()):
                assert detect_domain(left + word + right, KEYWORDS) == domain


def test_repetition_does_not_manufacture_extra_votes():
    for cue in ("series", "derivative", "matrix", "residue", "矩阵", "留数"):
        once = domain_keyword_matches(cue, KEYWORDS)
        assert once
        assert domain_keyword_matches(" ".join([cue] * 30), KEYWORDS) == once


def test_invalid_or_oversize_input_abstains():
    for value in (None, 123, {}, [], "matrix" * 20_000):
        assert detect_domain(value, KEYWORDS) == ""
