from evaluation.scoring.judge import judge_answer
from evaluation.scoring.rescore_report import rescore_report


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
