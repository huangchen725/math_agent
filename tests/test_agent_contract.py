from agent_types import Candidate
from answer_equivalence import build_answer, equivalent_answers
from user_agent import ReasoningAgent


def test_active_response_keeps_reasoning_and_final_marker():
    agent = ReasoningAgent(client=object())
    content = "推理步骤\n最终答案：42"
    assert agent._build_response(content, "42") == content


def test_active_response_adds_final_marker_when_missing():
    agent = ReasoningAgent(client=object())
    assert agent._build_response("推理步骤", "42") == "推理步骤\n最终答案：42"


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
