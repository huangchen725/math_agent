"""Deployment evidence and selection regressions; no provider calls."""
from dataclasses import asdict
import pytest

import user_agent as runtime


def candidate(answer, status, confidence=None):
    verification = runtime.Verification("model", status, float(status == "pass"), "fixture")
    return runtime.Candidate(content="derivation " + answer + "\n最终答案：" + answer,
        strategy="plain", answer=runtime.build_answer(answer),
        confidence=(1.3 if status == "pass" else 0.3) if confidence is None else confidence,
        raw_confidence=float(status == "pass"), verifications=[verification])


def test_ordinary_constructor_activates_named_candidate_and_explicit_baseline_is_frozen():
    default = runtime.ReasoningAgent(object())
    assert {name for name, enabled in asdict(default.local_policy).items() if enabled} == {
        "concise_recovery", "bounded_math", "evidence_selection", "reasoned_verifier",
        "answer_bank_fastpath", "answer_bank_reference", "completed_answer_repair", "solver_v2"}
    baseline = runtime.ReasoningAgent(object(), local_policy=runtime.Q1Policy())
    assert not any(asdict(baseline.local_policy).values())
    assert asdict(default.config) == asdict(baseline.config)


def test_rejected_majority_does_not_defeat_model_supported_alternative():
    pool = [candidate("7", "fail"), candidate("7", "fail"), candidate("2", "pass")]
    baseline = runtime.ReasoningAgent(object(), local_policy=runtime.Q1Policy())
    deployed = runtime.ReasoningAgent(object())
    assert baseline._aggregate(pool, [])[0] == "7"
    answer, reasoning = deployed._aggregate(pool, [])
    assert answer == "2" and reasoning == pool[-1].content


def test_unknown_votes_are_not_negative_evidence_and_no_supported_answer_is_discarded():
    deployed = runtime.ReasoningAgent(object())
    for status in ("unknown", "fail"):
        pool = [candidate("7", status), candidate("7", status), candidate("2", "unknown")]
        assert deployed._aggregate(pool, [])[0] == "7"
    # Contradictory votes do not count as all-negative.
    pool = [candidate("7", "fail"), candidate("7", "unknown"), candidate("2", "pass")]
    pool[0].verifications.append(runtime.Verification("model", "pass", 1.0, "fixture"))
    assert deployed._aggregate(pool, [])[0] == "7"


def test_disagreement_within_an_answer_group_does_not_erase_its_consensus():
    deployed = runtime.ReasoningAgent(object())
    for status in ("pass", "unknown"):
        pool = [candidate("7", "fail"), candidate("2", "pass"), candidate("7", status)]
        assert deployed._aggregate(pool, [])[0] == "7"


def test_exact_proof_overrides_false_model_votes_and_preserves_reasoning_identity():
    deployed = runtime.ReasoningAgent(object())
    pool = [candidate("7", "pass"), candidate("7", "pass"), candidate("2", "fail")]
    eligible = deployed._apply_exact_evidence("计算1+1", pool, [])
    assert len(eligible) == 1 and eligible[0] is pool[-1]
    assert deployed._aggregate(eligible, [])[0] == "2"


@pytest.mark.parametrize("legacy,expected_requests", [(False, 1), (True, 6)])
def test_default_complete_path_uses_only_public_false_protocol_and_no_reference_metadata(legacy, expected_requests):
    class StrictClient:
        def __init__(self):
            self.calls = []

        def __getattr__(self, name):
            raise AssertionError("private probe " + name)

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False and 1 <= max_tokens <= 8192
            assert "PRIVATE_LABEL_999" not in str(messages)
            self.calls.append((messages, temperature, max_tokens, thinking_mode))
            return "VERDICT: A" if "验证器" in messages[0]["content"] else "计算得到2。\n最终答案：2"

    client = StrictClient()
    # The default controller stops at a whole-task exact proof. Preserve the
    # old six-request public-contract coverage as an explicit second case.
    options = {"local_policy": runtime.legacy_deployment_policy()} if legacy else {}
    result = runtime.ReasoningAgent(client, **options).solve("计算1+1", {"answer": "PRIVATE_LABEL_999"})
    assert result["final_response"].endswith("最终答案：2")
    assert len(client.calls) == expected_requests
    assert all("PRIVATE_LABEL_999" not in str(item) for item in result["trace"])


def test_exact_refutation_gets_one_bounded_correction_even_when_model_wrongly_approves():
    class Client:
        def __init__(self, repaired):
            self.calls = []
            self.repaired = repaired

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False and max_tokens <= 8192
            self.calls.append((messages, max_tokens))
            if "验证器" in messages[0]["content"]:
                return "VERDICT: A"
            if "你之前的解答可能有误" in messages[-1]["content"]:
                return self.repaired
            return "最终答案：7"

    for reply, expected in (("最终答案：2", "最终答案：2"), ("最终答案：7", "未解出"),
                            ({"content": "最终答案：2", "finish_reason": "length"}, "未解出")):
        client = Client(reply)
        result = runtime.ReasoningAgent(client, local_policy=runtime.legacy_deployment_policy()).solve("计算1+1", {})
        assert result["final_response"].endswith(expected)
        assert len(client.calls) == 7
        assert client.calls[-1][1] == 8192


def test_exact_correction_respects_exhausted_budget_without_extra_request():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            self.calls += 1
            return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：7"

    client = Client()
    result = runtime.ReasoningAgent(client, runtime.AgentConfig(max_model_requests=6),
                                    local_policy=runtime.legacy_deployment_policy()).solve("计算1+1", {})
    assert result["final_response"] == "未解出"
    assert client.calls == 6


def test_default_fallback_really_uses_deployed_concise_prompt():
    class Client:
        def __init__(self):
            self.fallbacks = []

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            assert thinking_mode is False
            if max_tokens == 512:
                self.fallbacks.append(messages[0]["content"])
                return "最终答案：2"
            if "验证器" in messages[0]["content"]:
                return "VERDICT: A"
            return {"content": None, "finish_reason": "length"}

    client = Client()
    result = runtime.ReasoningAgent(client).solve("计算1+1", {})
    assert result["final_response"].endswith("最终答案：2")
    assert client.fallbacks and set(client.fallbacks) == {runtime.CONCISE_RECOVERY_PROMPT}


def test_reasoned_verifier_requires_one_complete_bounded_verdict_and_unchanged_protocol():
    parse = runtime.ReasoningAgent._reasoned_verdict_status
    assert parse("CHECK: derivative is 2*x.\nVERDICT: A") == "pass"
    assert parse("CHECK: x=0 gives a counterexample.\nVERDICT: B") == "fail"
    assert parse("CHECK: unable to establish all cases.\nVERDICT: UNKNOWN") == "unknown"
    for separator in ("\n", "\n\n", "\r\n \t\r\n", "\n\n\n"):
        assert parse("CHECK: differentiating gives 2*x." + separator + "VERDICT: A") == "pass"
    for text in ("VERDICT: A\nVERDICT: B", "CHECK: VERDICT: B\nVERDICT: A", "A",
                 "CHECK:\nanything\nVERDICT: A", "CHECK: correct.\nVERDICT:\nA",
                 "VERDICT:\nA", "CHECK: \nVERDICT: A",
                 "CHECK: derivative is wrong.\nVERDICT:", "CHECK: " + "x"*1100 + "\nVERDICT: A",
                 runtime._ModelText("CHECK: x=0.\nVERDICT: A", "length")):
        assert parse(text) == "unknown"

    class Client:
        def __init__(self):
            self.calls = []

        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            self.calls.append((messages, temperature, max_tokens, thinking_mode))
            return "CHECK: differentiating the answer gives 2*x.\nVERDICT: A"

    client = Client()
    score, _, votes = runtime.ReasoningAgent(client)._verify("Find an integral", "最终答案：x^2+C", 0)
    assert score == 1 and votes[0].status == "pass"
    assert len(client.calls) == 1 and client.calls[0][1:] == (0.0, 1024, False)
    assert client.calls[0][0][0]["content"] == runtime.REASONED_VERIFIER_PROMPT
