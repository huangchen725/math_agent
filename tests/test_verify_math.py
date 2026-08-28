from domain_prompts import DOMAIN_PROMPTS
import verify_math
from verify_math import parse_fewshot_examples, run_verification, verify_answer, verify_string


def test_parse_fewshot_examples_reads_every_declared_example():
    examples = parse_fewshot_examples()

    assert len(examples) == 21
    assert {example["domain"] for example in examples} == set(DOMAIN_PROMPTS)
    assert next(
        example["expected_answer"]
        for example in examples
        if example["domain"] == "抽象代数"
    ) == "72"


def test_text_verification_does_not_accept_substrings_or_negated_claims():
    assert verify_string("1", "10") is False
    assert verify_answer("收敛", "不收敛")[0] is False


def test_verification_accepts_safe_unicode_and_latex_variants():
    assert verify_answer("3x^2 - 3", "3x² - 3")[0] is True
    assert verify_answer("1/R", r"\(\displaystyle \frac{1}{R}$")[0] is True


def test_wave_equation_example_has_the_condition_needed_for_its_answer():
    assert "u_t(x,0)=0" in DOMAIN_PROMPTS["偏微分方程"]


def test_domain_prompts_require_compact_final_answer_body():
    assert all("只写答案本体" in prompt for prompt in DOMAIN_PROMPTS.values())


def test_verification_defaults_to_dry_run_without_constructing_client(monkeypatch):
    def fail_if_called():
        raise AssertionError("dry-run must not construct an API client")

    monkeypatch.setattr(verify_math, "InternChatClient", fail_if_called)

    examples = run_verification()

    assert len(examples) == 21


def test_verification_rejects_non_positive_request_budget():
    try:
        run_verification(max_requests=0)
    except ValueError as exc:
        assert "positive integer" in str(exc)
    else:
        raise AssertionError("expected a ValueError")
