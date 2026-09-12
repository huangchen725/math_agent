"""New deployment behavior, independent routes and bounded decision invariants."""
import copy
from dataclasses import asdict, replace
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

import user_agent as r


def route(answer=None, *, tasks=(), goals=("requested object",), conditions=("all stated conditions",), obligations=()):
    plan = {"goals": list(goals), "conditions": list(conditions), "method": "independent derivation",
            "calculations": list(tasks), "obligations": list(obligations)}
    return "<solver_plan>" + json.dumps(plan) + "</solver_plan>\nDerivation of the requested result." + (
        "\n最终答案：" + answer if answer is not None else "")


def selection(chosen=2, statuses=("refuted", "supported"), *, calculations=(), repair=False):
    data = {"checks": [{"candidate": i, "status": status, "reason": f"Substitution into condition gives {i}+1={i+1}.",
                        "missing_goals": [], "condition_errors": []} for i, status in enumerate(statuses, 1)],
            "selected": chosen, "disagreement": "The candidates differ in the evaluated boundary term.",
            "repair": repair, "calculations": list(calculations)}
    return "<selection>" + json.dumps(data) + "</selection>"


class StrictClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def __getattr__(self, name):
        raise AssertionError("private access: " + name)

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        assert thinking_mode is False and 1 <= max_tokens <= 8192
        self.calls.append(copy.deepcopy(dict(messages=messages, temperature=temperature,
                                              max_tokens=max_tokens, thinking_mode=thinking_mode)))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture(autouse=True)
def empty_retrieval(monkeypatch):
    # This suite tests the controller; retrieval has separate real-resource tests.
    monkeypatch.setattr(r._dependencies["xh202627_corpus"], "build_evidence_plan", lambda problem: {
        "status": "miss", "reference": "", "methods": "", "exact_record": None, "counters": {}})


def run(responses, problem="Find the requested mathematical object.", config=None):
    client = StrictClient(responses)
    result = r.ReasoningAgent(client, config).solve(problem, {"answer": "PRIVATE_LABEL_SENTINEL"})
    return client, result


def steps(result):
    return [item["step"] for item in result["trace"]]


def test_named_default_and_old_baselines_are_explicit():
    assert r.ReasoningAgent(object()).local_policy.solver_v2 is True
    assert not any(asdict(r.Q1Policy()).values())
    legacy = r.legacy_deployment_policy()
    assert legacy.solver_v2 is False
    assert replace(r.deployment_policy(), solver_v2=False) == legacy


def test_exact_whole_question_stops_before_unnecessary_routes_or_votes():
    client, result = run([route("2")], "计算1+1")
    assert result["final_response"].endswith("最终答案：2")
    assert len(client.calls) == 1
    assert "deterministic_pass" in steps(result)


def test_routes_are_independent_and_final_choice_uses_dispute_evidence(monkeypatch):
    monkeypatch.setattr(r._dependencies["xh202627_corpus"], "build_evidence_plan", lambda problem: {
        "status": "ready", "reference": "REFERENCE_ANSWER_SENTINEL", "methods": "APPLICABLE_METHOD_SENTINEL"})
    client, result = run([route("17"), route("23"), selection()])
    first, second, review = [call["messages"][-1]["content"] for call in client.calls]
    assert "REFERENCE_ANSWER_SENTINEL" in first and "APPLICABLE_METHOD_SENTINEL" in first
    assert "REFERENCE_ANSWER_SENTINEL" not in second and "APPLICABLE_METHOD_SENTINEL" in second
    assert "最终答案：17" not in second and "待审候选" not in second
    assert '"answer": "17"' in review and '"answer": "23"' in review
    assert result["final_response"].endswith("最终答案：23")
    assert len(client.calls) == 3
    assert "PRIVATE_LABEL_SENTINEL" not in json.dumps(client.calls)
    assert "REFERENCE_ANSWER_SENTINEL" not in json.dumps(result["trace"])
    assert "deterministic_pass" not in steps(result)


def test_actual_computation_is_fed_back_before_completion():
    task = {"id": "c1", "task": {"op": "evaluate", "expr": {"op": "div", "args": [17, 60]}}, "expected": "68/120"}
    client, result = run([route(None, tasks=[task]), route("17/60"), route("17/60"),
                          selection(1, ("supported", "supported"))])
    assert result["final_response"].endswith("最终答案：17/60")
    feedback = client.calls[1]["messages"][-1]["content"]
    assert '"value": "17/60"' in feedback and '"matches_expected": false' in feedback
    assert "v2_math_ok" in steps(result)
    summary = next(item["content"] for item in result["trace"] if item["step"] == "budget_summary")
    assert summary["tool_calls"] == 1 and summary["model_requests"] == 4


def test_review_requested_computation_changes_choice_only_after_results_are_seen():
    task = {"id": "critical", "task": {"op": "evaluate", "expr": {"op": "div", "args": [17, 60]}}}
    client, result = run([route("68/120"), route("17/60"), selection(1, ("supported", "unknown"), calculations=[task]), selection()])
    assert len(client.calls) == 4
    assert '"value": "17/60"' in client.calls[-1]["messages"][-1]["content"]
    assert result["final_response"].endswith("最终答案：17/60")


def test_model_subtask_does_not_create_whole_question_proof():
    task = {"id": "irrelevant", "task": {"op": "evaluate", "expr": 2}, "expected": "2"}
    client, result = run([route("999", tasks=[task]), route("23"), selection()])
    assert len(client.calls) == 3 and result["final_response"].endswith("最终答案：23")
    assert "deterministic_pass" not in steps(result)


def test_model_support_cannot_outrank_a_concrete_arithmetic_mismatch():
    task = {"id": "c1", "task": {"op": "evaluate", "expr": {"op": "div", "args": [17, 60]}}, "expected": "68/120"}
    # The first solution has a demonstrably wrong step. Its correction and an
    # independent route remain viable despite the reviewer's mistaken support.
    _, result = run([route("68/120", tasks=[task]), route("17/60"), route("17/60"),
                     selection(1, ("supported", "unknown", "unknown"))])
    assert result["final_response"].endswith("最终答案：17/60")


def test_conflicting_final_markers_do_not_select_the_last_assertion():
    client, result = run(["最终答案：7\n最终答案：2", route("2")], "计算1+1")
    assert len(client.calls) == 2 and result["final_response"].endswith("最终答案：2")
    assert "v2_plan_invalid" in steps(result)


@pytest.mark.parametrize("failure", [RuntimeError("PRIVATE_TRANSPORT_SENTINEL"), {"content": None}, []])
def test_later_transport_failure_stops_calls_and_keeps_complete_candidate(failure):
    client, result = run([route("23"), failure, route("999")])
    assert len(client.calls) == 2
    assert result["final_response"].endswith("最终答案：23")
    assert "v2_transport_stop" in steps(result)
    assert "PRIVATE_TRANSPORT_SENTINEL" not in json.dumps(result)


def test_first_transport_failure_does_not_retry():
    client, result = run([PermissionError("private"), route("23")])
    assert len(client.calls) == 1 and result["final_response"] == "未解出"


@pytest.mark.parametrize("reason", ["length", "tool_calls", "content_filter"])
def test_truncated_correct_looking_answer_never_qualifies(reason):
    client, result = run([{"content": route("999"), "finish_reason": reason}, route("2")], "计算1+1")
    assert len(client.calls) == 2 and result["final_response"].endswith("最终答案：2")
    assert "999" not in result["final_response"]


@pytest.mark.parametrize("limit", [1, 2, 3, 4, 5, 16])
def test_all_routes_review_and_repair_share_original_request_budget(limit):
    client, result = run([route("7"), route("9"), selection(repair=True), route("11"), route("13")],
                         config=r.AgentConfig(max_model_requests=limit))
    assert 1 <= len(client.calls) <= min(limit, 16)
    assert result["final_response"] != "未解出"
    assert result["final_response"].count("最终答案：") == 1


def test_whole_question_refutation_excludes_wrong_model_consensus():
    client, result = run([route("7"), route("7"), route("2")], "计算1+1")
    assert len(client.calls) == 3
    assert result["final_response"].endswith("最终答案：2")
    assert "deterministic_fail" in steps(result)


def test_multivariate_historical_correct_answer_wins_with_no_model_verifier():
    problem = r"Evaluate \int\int\int_E (x+2*y*z) dV, E={(x,y,z)|0<=x<=1,0<=y<=x,0<=z<=5-x-y}."
    client, result = run([route("41/30"), route("439/120")], problem)
    assert result["final_response"].endswith("最终答案：439/120")
    assert len(client.calls) == 2


@pytest.mark.parametrize("answer", ["60°", "x_1", "(1) 2; (2) 3", "[1,2)"])
def test_delivery_preserves_semantic_symbols_and_part_order(answer):
    client, result = run([route(answer), route(answer), selection(1, ("supported", "supported"))])
    assert result["final_response"].splitlines()[-1] == "最终答案：" + answer
    assert "<solver_plan>" not in result["final_response"]


@pytest.mark.parametrize("bad", [
    '<solver_plan>{"a":1,"a":2}</solver_plan>',
    '<solver_plan>{"a":NaN}</solver_plan>',
    '<solver_plan>{"a":1}</solver_plan><solver_plan>{"a":2}</solver_plan>',
    '<solver_plan>' + '[' * 40 + '0' + ']' * 40 + '</solver_plan>',
    '<solver_plan>{"a":"\u202eevil"}</solver_plan>',
])
def test_untrusted_json_protocol_rejects_duplicate_conflicting_or_unbounded_data(bad):
    assert r._v2_json_block(bad, "solver_plan") is None


def test_unknown_review_does_not_erase_all_complete_answers():
    _, result = run([route("17"), route("23"), selection(None, ("unknown", "unknown"))])
    assert result["final_response"] != "未解出"
    assert "deterministic_pass" not in steps(result)


def test_false_exact_resource_match_never_triggers_copy(monkeypatch):
    monkeypatch.setattr(r._dependencies["xh202627_corpus"], "build_evidence_plan", lambda problem: {
        "status": "ready", "exact_record": {"problem": "计算1+2", "answer": "3", "trust": "source_verified"}})
    client, result = run([route("2")], "计算1+1")
    assert result["final_response"].endswith("最终答案：2")
    assert client.calls[0]["messages"][0]["content"].startswith(r.V2_ROUTE_PROMPT)


def test_optional_retrieval_failure_still_enters_new_solver(monkeypatch):
    def broken(problem):
        raise ValueError("PRIVATE_RESOURCE_SENTINEL")
    monkeypatch.setattr(r._dependencies["xh202627_corpus"], "build_evidence_plan", broken)
    client, result = run([route("2")], "计算1+1")
    assert len(client.calls) == 1 and result["final_response"].endswith("最终答案：2")
    assert "v2_retrieval_unavailable" in steps(result)
    assert "PRIVATE_RESOURCE_SENTINEL" not in json.dumps(result)


def test_concurrent_solves_do_not_share_candidates_or_budget():
    def one(n):
        client, result = run([route(str(n + 1))], f"计算{n}+1")
        return len(client.calls), result["final_response"].splitlines()[-1]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(one, range(12)))
    assert results == [(1, f"最终答案：{n + 1}") for n in range(12)]
    assert r._ACTIVE_BUDGET.get() is None


def test_exact_value_comparison_preserves_types_and_multipart_order():
    for n in range(-20, 21):
        assert r._v2_same_value(f"{n * 3}/21", f"{n}/7")
        assert not r._v2_same_value(f"{n}/7", f"{n + 1}/7")
    assert not r._v2_same_value(True, 1)
    assert not r._v2_same_value(["1", "2"], ["2", "1"])
    assert not r._v2_same_value("60°", "60")


@pytest.mark.parametrize("representation", ["0.5", "2/4", r"\frac{1}{2}", r"$\frac{1}{2}$", r"\(1/2\)"])
def test_subtask_comparison_proves_equivalent_rational_notations(representation):
    assert r._v2_same_value("1/2", representation) is True
    assert r._v2_same_value("2/3", representation) is False


@pytest.mark.parametrize("representation", ["sin(pi/6)", "0.500...", "50%", "pi", "60°"])
def test_unrecognized_subtask_representation_is_unknown_not_a_mathematical_refutation(representation):
    assert r._v2_same_value("1/2", representation) is None
    assert r._v2_same_value(["1/2"], [representation]) is None
    assert r._v2_same_value({"value": "1/2"}, {"value": representation}) is None


def test_computation_only_repair_is_completed_with_actual_results_under_same_budget():
    task = {"id": "fix", "task": {"op": "evaluate", "expr": {"op": "div", "args": [17, 60]}}}
    client, result = run([route("3"), route("4"), selection(None, ("refuted", "refuted"), repair=True),
                          route(None, tasks=[task]), route("17/60")])
    assert len(client.calls) == 5
    assert result["final_response"].endswith("最终答案：17/60")
    assert '"value": "17/60"' in client.calls[-1]["messages"][-1]["content"]
    budget = next(item["content"] for item in result["trace"] if item["step"] == "budget_summary")
    assert budget["model_requests"] == 5 and budget["tool_calls"] == 1


def test_computation_only_repair_does_not_exceed_exhausted_budget():
    task = {"id": "fix", "task": {"op": "evaluate", "expr": 2}}
    client, result = run([route("3"), route("4"), selection(None, ("refuted", "refuted"), repair=True),
                          route(None, tasks=[task])], config=r.AgentConfig(max_model_requests=4))
    assert len(client.calls) == 4 and result["final_response"] != "未解出"
    assert result["final_response"].endswith("最终答案：3")


def test_invalid_review_calculation_does_not_activate_its_uninformed_choice():
    client, result = run([route("17"), route("23"), selection(2, ("refuted", "supported"),
                                                              calculations=[{"id": "missing_task"}])])
    assert len(client.calls) == 3 and "v2_plan_invalid" in steps(result)
    assert result["final_response"].endswith("最终答案：17")
    assert "v2_math_ok" not in steps(result)
