"""Answer delivery contracts: syntax changes preserve complete mathematical content."""
from itertools import product

import pytest
import user_agent as runtime

Agent = runtime.ReasoningAgent


@pytest.mark.parametrize("text,expected", [
    ("最终答案：\n1. x=2\n2. y=3", "1. x=2; 2. y=3"),
    ("最终答案：1. x=2\n2. y=3", "1. x=2; 2. y=3"),
    ("## 最终答案\n\n1. x=2\n2. y=3", "1. x=2; 2. y=3"),
    ("**最终答案**：7", "7"),
    ("**最终答案：** 7", "7"),
    ("__最终答案：__ 7", "7"),
    ("3. 最终答案：\n7", "7"),
    ("最终答案：\nf(x)=|x|\ng(x)=x^2", "f(x)=|x|; g(x)=x^2"),
    (r"中间值 \boxed{999}" + "\n最终答案：\n1. x=2\n2. y=3", "1. x=2; 2. y=3"),
    ("最终答案：\n1. x=2\n2. y=3\n## 验证\n代入成立", "1. x=2; 2. y=3"),
    ("<final_answer>\n最终答案：7\n</final_answer>", "7"),
    ("Let's write the result.最终答案：7", "7"),
    ("```The tool returned a result.\n最终答案：7", "7"),
    ("最终答案：7\n\nOr maybe separate lines? It says single line.\nLet's produce the final answer.", "7"),
    ("最终答案：\\[\nx^2+C\n\\]", r"\[ x^2+C \]"),
    ("最终答案：1。最终答案：2", "2"),
    (r"最终答案：\[\begin{aligned}x&=1\\[4pt]y&=2\end{aligned}\]",
     r"\[\begin{aligned}x&=1\\[4pt]y&=2\end{aligned}\]"),
])
def test_complete_explicit_blocks(text, expected):
    assert Agent._extract_answer(text) == expected


@pytest.mark.parametrize("text", [
    "最终答案：7\n最终答案：", "最终答案：7\n## 最终答案",
    r"\boxed{7}" + "\n最终答案：", "最终答案：\n1. x=2\n2. y=",
    "最终答案：\n1. x=2\n3. y=3", "最终答案：\n1. x=2\n2.",
    "最终答案：1. x=2\n2. y=3\n还需要检查其他解", "最终答案：\n7\n8",
    'The requested format is "最终答案：7"', '```python\nprint("最终答案：7")\n```',
    "最终答案：\n" + "x" * 2049,
    "最终答案：\\[", "最终答案：\\[\nx^2+C",
    "最终答案：7\n\nOr maybe separate lines? It says single line.\nx>0",
    "最终答案：1。最终答案：",
    "```python\n" + r"print('\\boxed{7}')" + "\n```",
    "````python\n~~~\n" + r"\boxed{7}" + "\n````",
    "最终答案：\\[\n7\n\\]\n\\[\n8",
    "最终答案：$$x^2+C",
])
def test_ambiguous_incomplete_or_example_blocks_abstain(text):
    assert Agent._extract_answer(text) == ""


def test_explicit_length_veto_survives_all_heading_variants():
    for heading in ("最终答案：", "**最终答案：**", "## 最终答案"):
        text = runtime._response_text(heading + "\n1. x=2\n2. y=3", {"finish_reason": "length"})
        assert Agent._extract_answer(text) == ""


def test_format_transformations_preserve_answer_and_are_idempotent():
    agent = Agent(None)
    for heading, space, body in product(
        ("最终答案：", "**最终答案：**", "**最终答案**：", "## 最终答案："),
        ("", " ", "\n"), ("7", "x**2", "1/(40*abs(sin(t/2)))", "x=2, x>0", r"\frac{1}{2}"),
    ):
        answer = Agent._extract_answer(heading + space + body)
        assert answer == body
        formatted = agent._build_response("", answer)
        assert formatted == agent._build_response("", Agent._extract_answer(formatted))
        assert formatted.count("最终答案：") == 1
        assert not formatted.endswith("最终答案：^ 7")


def test_numbered_parts_preserve_order_and_exact_values():
    for count in range(1, 20):
        parts = [f"{i}. x{i}={i}/{i+1}" for i in range(1, count+1)]
        assert Agent._extract_answer("最终答案：\n" + "\n".join(parts)) == "; ".join(parts)


class Sequence:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens, **kwargs):
        self.calls.append((messages, temperature, max_tokens))
        return next(self.values)


def test_complete_multiline_candidate_does_not_trigger_another_model_request():
    client = Sequence(["最终答案：\n1. x=2\n2. y=3", "VERDICT: A"])
    config = runtime.AgentConfig(tool_candidates=1, plain_candidates=0, enable_critic=False)
    result = Agent(client, config).solve("分别给出 x 和 y。", {})
    assert result["final_response"].endswith("最终答案：1. x=2;2. y=3")
    assert len(client.calls) == 2


@pytest.mark.parametrize("answer", ["7", "sqrt(2)", "tan^2(alpha)"])
@pytest.mark.parametrize("branch", ["tool", "plain", "final"])
def test_valid_recovery_survives_candidate_handoff(answer, branch):
    values = ["未完成的候选", "最终答案：" + answer]
    if branch != "final":
        values.append("VERDICT: A")
    client = Sequence(values)
    config = runtime.AgentConfig(tool_candidates=int(branch == "tool"), plain_candidates=int(branch != "tool"),
                                 enable_critic=False)
    policy = runtime.Q1Policy(recover_plain=branch == "plain")
    result = Agent(client, config, local_policy=policy).solve("给出精确结果。", {})
    assert result["final_response"].endswith("最终答案：" + answer)
    assert not any(row["step"].startswith("truncated_isolated") for row in result["trace"])
    assert len(client.calls) == len(values)


@pytest.mark.parametrize("reason", [None, "stop", "length", "tool_calls", "content_filter"])
def test_recovery_conversion_preserves_completion_evidence(reason):
    text = runtime._ModelText("sqrt(2)", reason)
    candidate = Agent._candidate_from_recovery(text)
    if reason in (None, "stop"):
        assert candidate == "最终答案：sqrt(2)"
        assert candidate.finish_reason == reason
    else:
        assert candidate == ""


@pytest.mark.parametrize("invalid", ["", "x=", "还需要推导", r"\sqrt{2", "x" * 2049])
def test_invalid_recovery_cannot_be_wrapped_as_complete(invalid):
    assert Agent._candidate_from_recovery(invalid) == ""
