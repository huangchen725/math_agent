from agent_types import Candidate, Verification
from answer_equivalence import build_answer, equivalent_answers, format_answer_for_output
from user_agent import AgentConfig, POLICY_PROMPT, ReasoningAgent


def test_active_response_keeps_reasoning_and_final_marker():
    agent = ReasoningAgent(client=object())
    content = "推理步骤\n最终答案：42"
    assert agent._build_response(content, "42") == content


def test_active_response_adds_final_marker_when_missing():
    agent = ReasoningAgent(client=object())
    assert agent._build_response("推理步骤", "42") == "推理步骤\n最终答案：42"


def test_answer_first_candidate_is_rendered_with_one_final_answer_at_tail():
    agent = ReasoningAgent(client=object())
    content = "最终答案：42\n推理步骤"

    response = agent._build_response(content, agent._extract_answer(content))

    assert response == "推理步骤\n最终答案：42"
    assert response.count("最终答案：") == 1


def test_active_response_rewrites_final_line_to_stable_answer_body():
    agent = ReasoningAgent(client=object())
    content = "推理步骤\n3. 最终答案：圆周 S¹ 的基本群是整数加群 ℤ。"

    response = agent._build_response(content, r"\(\displaystyle \frac{1}{R}$")

    assert response == "推理步骤\n最终答案：1/R"
    assert response.count("最终答案：") == 1


def test_active_response_removes_noncanonical_answer_sentence():
    agent = ReasoningAgent(client=object())

    response = agent._build_response("推理步骤\n因此答案是 10。", "10")

    assert response == "推理步骤\n最终答案：10"


def test_active_response_keeps_reasoning_that_mentions_answer_quality():
    agent = ReasoningAgent(client=object())

    response = agent._build_response("检查候选答案的正确性。", "10")

    assert response == "检查候选答案的正确性。\n最终答案：10"


def test_output_formatter_uses_ascii_safe_math_notation():
    assert format_answer_for_output("3x² - 3") == "3x^2 - 3"
    assert format_answer_for_output(r"\mathbb{Z}") == "Z"
    assert format_answer_for_output("16πi") == "16*pi*i"
    assert format_answer_for_output("160°") == "160"
    assert "只写答案本体" in POLICY_PROMPT
    assert "第一行先写" in POLICY_PROMPT


def test_extractor_does_not_treat_truncated_reasoning_tail_as_answer():
    assert ReasoningAgent._extract_answer("解题思路\n所以还需要继续计算") == ""
    assert ReasoningAgent._extract_answer("当前答案尚未计算完成") == ""


def test_output_formatter_keeps_exact_form_and_removes_root_labels():
    assert format_answer_for_output("4480/19683 ≈ 0.2276") == "4480/19683"
    assert format_answer_for_output("m = 4, 7") == "4,7"
    assert format_answer_for_output("r1 = -2, r2 = 7") == "-2,7"


def test_fallback_response_adds_final_marker():
    agent = ReasoningAgent(client=object())
    assert agent._build_response("", "42") == "最终答案：42"


def test_normalize_equivalent_numeric_forms():
    assert ReasoningAgent._normalize(r"\(\frac{1}{2}\)") == "1/2"
    assert ReasoningAgent._numeric("1/2") == 0.5


def test_aggregate_returns_content_from_majority_answer_group():
    agent = ReasoningAgent(client=object())
    scored = [
        Candidate("候选 A\n最终答案：1", "tool", build_answer("1"), 1.3, 1.0),
        Candidate("候选 B\n最终答案：2", "tool", build_answer("2"), 0.3, 0.0),
        Candidate("候选 C\n最终答案：2", "plain", build_answer("2"), 0.3, 0.0),
    ]

    answer, content = agent._aggregate(scored, [])

    assert answer == "2"
    assert "最终答案：2" in content


def test_aggregate_never_selects_candidate_marked_as_truncated():
    agent = ReasoningAgent(client=object())
    scored = [
        Candidate(
            "截断残句\n最终答案：999",
            "plain",
            build_answer("999"),
            9.0,
            1.0,
            metadata={"truncated": True},
        ),
        Candidate("完整推理\n最终答案：2", "plain", build_answer("2"), 0.3, 0.0),
    ]

    answer, content = agent._aggregate(scored, [])

    assert answer == "2"
    assert "截断残句" not in content


def test_deterministic_pass_overrides_a_wrong_model_majority_for_direct_task():
    class SequenceClient:
        def __init__(self):
            self.responses = [
                "最终答案：5\n错误候选一",
                "最终答案：5\n错误候选二",
                "最终答案：4\n正确候选",
            ]

        def chat(self, **kwargs):
            return self.responses.pop(0)

    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=3,
        verifier_voting_times=0,
        enable_critic=False,
        enable_reflection=False,
    )
    result = ReasoningAgent(SequenceClient(), config).solve("计算 3^100 除以 7 的余数", {})

    assert result["final_response"].endswith("最终答案：4")
    assert any(event["step"] == "deterministic_selection" for event in result["trace"])
    summary = next(
        event["content"] for event in result["trace"] if event["step"] == "budget_summary"
    )
    assert summary["tool_calls"] == 3


def test_deterministic_verification_has_a_full_rollback_switch():
    class SequenceClient:
        def __init__(self):
            self.responses = ["最终答案：5", "最终答案：5", "最终答案：4"]

        def chat(self, **kwargs):
            return self.responses.pop(0)

    config = AgentConfig(
        tool_candidates=0,
        plain_candidates=3,
        verifier_voting_times=0,
        enable_critic=False,
        enable_reflection=False,
        enable_deterministic_verification=False,
    )
    result = ReasoningAgent(SequenceClient(), config).solve("计算 3^100 除以 7 的余数", {})

    assert result["final_response"].endswith("最终答案：5")
    assert not any(event["step"] == "deterministic_selection" for event in result["trace"])


def test_conflicting_deterministic_passes_fall_back_to_original_selector():
    evidence = [Verification("deterministic:test", "pass", 1.0)]
    candidates = [
        Candidate("候选 A", "plain", build_answer("1"), 0.8, 0.8, evidence),
        Candidate("候选 B", "plain", build_answer("2"), 0.7, 0.7, evidence),
        Candidate("候选 C", "plain", build_answer("2"), 0.6, 0.6),
    ]
    trace = []

    answer, content = ReasoningAgent(client=object())._aggregate(candidates, trace)

    assert answer == "2"
    assert content == "候选 B"
    assert any(
        event["step"] == "deterministic_selection"
        and event["content"]["status"] == "conflict_fallback"
        for event in trace
    )


def test_review_excerpt_keeps_final_answer_at_tail():
    candidate = "开头" + "x" * 4000 + "\n最终答案：42"
    excerpt = ReasoningAgent._review_excerpt(candidate, limit=100)

    assert excerpt.startswith("开头")
    assert excerpt.endswith("最终答案：42")


def test_domain_detection_is_case_insensitive_for_ascii_keywords():
    agent = ReasoningAgent(client=object())
    assert agent._detect_domain("solve this ode with an initial value") == "微分方程"


def test_conservative_equivalence_handles_exact_numbers_and_unordered_answers():
    assert equivalent_answers("0.5", "1/2") is True
    assert equivalent_answers("1,3", "3,1") is True
    assert equivalent_answers("1", "10") is False
    assert equivalent_answers("x+1", "1+x") is None


def test_conservative_equivalence_normalizes_ab_report_format_variants():
    assert equivalent_answers("3x² - 3", "3x^2 - 3") is True
    assert equivalent_answers(r"\(\displaystyle \frac{1}{R}$", "1/R") is True
    assert equivalent_answers(r"\mathbb{Z}", "ℤ") is True
    assert equivalent_answers("160°", "160") is True
    assert equivalent_answers("16πi", "16*pi*i") is True
    assert equivalent_answers("圆周 S¹ 的基本群是整数加群 ℤ。", "Z") is None
