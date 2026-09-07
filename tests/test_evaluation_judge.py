from evaluation.judge import judge_answer
from evaluation.rescore_report import rescore_report
import pytest


def test_judge_rejects_substring_false_positive():
    assert judge_answer("1", "10").status == "wrong"
    assert judge_answer("收敛", "不收敛").status == "wrong"


def test_judge_accepts_safe_notation_variants():
    assert judge_answer("3x^2 - 3", "3x² - 3").status == "correct"
    assert judge_answer("1/R", r"\(\displaystyle \frac{1}{R}$").status == "correct"
    assert judge_answer("Z", r"\mathbb{Z}").status == "correct"


def test_judge_keeps_semantic_sentence_unknown_instead_of_guessing():
    result = judge_answer("Z", "圆周 S¹ 的基本群是整数加群 ℤ。")

    assert result.status == "unknown"
    assert result.method == "semantic_review_required"


def test_judge_can_prove_symbolic_equivalence():
    assert judge_answer("2*x", "x+x", symbolic_timeout_seconds=3).status == "correct"


def test_rescore_report_rejects_legacy_substring_false_positive():
    dataset = [
        {"idx": 1, "subject": "数论", "problem": "示例", "answer": "1"},
        {"idx": 2, "subject": "拓扑", "problem": "示例", "answer": "Z"},
    ]
    legacy_report = {
        "results": [
            {"idx": 1, "extracted": "10", "verdict": "correct"},
            {"idx": 2, "extracted": "圆周的基本群是整数加群。", "verdict": "correct"},
        ]
    }

    rescored = rescore_report(dataset, legacy_report)

    assert rescored["summary"]["wrong"] == 1
    assert rescored["summary"]["unknown"] == 1
    assert rescored["summary"]["correct"] == 0


@pytest.mark.parametrize("left,right", [
    ("Positive roots: 2, 4; negative roots: 1", "正根可能为4或2个，负根为1个"),
    ("Possible roots: -2, 2, -7, 7", r"\pm 2,\pm 7"),
    ("{x+x, 7}", "{2*x, 7}"),
    ("(2,7)", "(7,2)"),
    ("2,7", "7,2"),
    ("[2,7]", "[7,2]"),
    ("{2, label}", "{2, other label}"),
])
def test_ambiguous_collection_comparison_requires_review_in_both_directions(left, right):
    assert judge_answer(left, right).status == "unknown"
    assert judge_answer(right, left).status == "unknown"


def test_numeric_sets_obey_extensional_equality_with_exact_rational_oracle():
    from fractions import Fraction
    from random import Random

    rng = Random(627)
    for _ in range(40):
        values = [Fraction(rng.randrange(-9, 10), rng.randrange(1, 7)) for _ in range(4)]
        left = "{" + ",".join(map(str, values)) + "}"
        reordered = list(reversed(values)) + values[:2]
        equivalent = "{" + ",".join(f"{v.numerator*3}/{v.denominator*3}" for v in reordered) + "}"
        different = "{" + ",".join(map(str, values + [Fraction(20)])) + "}"
        assert set(values) == set(reordered)
        assert judge_answer(left, equivalent).status == "correct"
        assert judge_answer(equivalent, left).status == "correct"
        assert judge_answer(left, different).status == "wrong"
        assert judge_answer(different, left).status == "wrong"


@pytest.mark.parametrize("left,right,status", [
    ("{}", "{}", "correct"),
    ("{}", "{2}", "wrong"),
    ("{2,2}", "{2}", "correct"),
    (r"{\frac{3}{4}, -2}", "{-2, .75}", "correct"),
    ("{2,,7}", "{2,7}", "unknown"),
    ("{2,1/0}", "{2,0}", "unknown"),
    ("{2,7}", "2,7", "unknown"),
    ("{2,7,}", "{2,7}", "unknown"),
])
def test_collection_syntax_does_not_invent_or_drop_elements(left, right, status):
    assert judge_answer(left, right).status == status


def test_collection_review_is_bounded_before_recursive_canonicalization(monkeypatch):
    import evaluation.judge as module

    def forbidden(*args, **kwargs):
        raise AssertionError("ambiguous collections must not enter recursive or symbolic parsers")

    monkeypatch.setattr(module, "equivalent_answers", forbidden)
    monkeypatch.setattr(module, "verify_symbolic_equivalence", forbidden)
    for text in ("{"*500 + "x" + "}"*500, "x,"*2000, "(2,7)"):
        assert judge_answer(text, "{2,7}").status == "unknown"
