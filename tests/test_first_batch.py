"""First-batch invariants with independent mathematics; no API requests."""
import copy
from dataclasses import asdict, replace
from fractions import Fraction
from itertools import permutations
import importlib.util
import json
from pathlib import Path
import random
import sys
import types

import pytest

import user_agent as r
from evaluation.q1_experiments import VARIANTS


class Client:
    def __init__(self, replies=None):
        self.calls = []
        self.replies = iter(replies) if replies is not None else None

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        assert thinking_mode is False
        assert 1 <= max_tokens <= 8192
        self.calls.append(copy.deepcopy((messages, temperature, max_tokens, thinking_mode)))
        if self.replies is not None:
            return next(self.replies)
        return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：2"

    def __getattr__(self, name):
        raise AssertionError("private probe " + name)


def determinant_oracle(matrix):
    total = Fraction(0)
    for order in permutations(range(len(matrix))):
        inversions = sum(order[i] > order[j] for i in range(len(order)) for j in range(i + 1, len(order)))
        term = Fraction((-1)**inversions)
        for i, j in enumerate(order):
            term *= Fraction(matrix[i][j])
        total += term
    return total


def test_rational_determinants_against_independent_permutation_oracle():
    rng = random.Random(908)
    for size in range(1, 6):
        for _ in range(8):
            matrix = [[str(Fraction(rng.randrange(-8, 9), rng.randrange(1, 5))) for _ in range(size)] for _ in range(size)]
            expected = determinant_oracle(matrix)
            text = json.dumps(matrix)
            assert r._bounded_determinant(text) == expected
            problem = "Compute the determinant of " + text
            assert r._bounded_task_check(problem, str(expected)) == "pass"
            assert r._bounded_task_check(problem, str(expected + 1)) == "fail"


@pytest.mark.parametrize("problem,answer", [
    (r"求矩阵 $\begin{pmatrix}1&2\\3&4\end{pmatrix}$ 的行列式", "-2"),
    (r"求函数 f(x)=$3x^{2}+\frac{x}{2}$ 的导数", "6*x+1/2"),
    (r"Differentiate $x^3/3$ with respect to x", "$x^2$"),
    (r"Find the indefinite integral of 3x^2 with respect to x", "$x^3+C$"),
    (r"计算 \binom{8}{3}", "56"),
    ("Calculate 3^5 mod 7", "5"),
])
def test_public_math_notations_are_complete_tasks(problem, answer):
    assert r._bounded_task_check(problem, answer) == "pass"


def test_polynomial_integral_derivative_inverse_properties():
    for power in range(1, 10):
        for scale in (-7, 1, 5):
            primitive = f"({scale}*x^{power+1})/{power+1}"
            assert r._bounded_task_check(f"Differentiate {primitive}", f"{scale}x^{power}") == "pass"
            assert r._bounded_task_check(f"Find the indefinite integral of {scale}x^{power}", primitive + "+C") == "pass"


@pytest.mark.parametrize("problem,answer", [
    ("求函数 f(x)=x^2 的导数，并求零点", "2x"),
    ("Differentiate x/x", "0"),
    ("Find the indefinite integral of 2*x", "x^2"),
    ("Find the indefinite integral of 2*x", "x^2+C*x+C"),
    ("Compute the determinant of [[true,0],[0,1]]", "1"),
    ("Compute the determinant of [[1.5,0],[0,1]]", "1.5"),
    ("Compute the determinant of [[1,2],[3]]", "2"),
    ("Compute the determinant of [[1,2],[3,4]] and its eigenvalues", "-2"),
    ("Differentiate x^13", "13*x^12"),
    ("Differentiate __import__('os').system('x')", "0"),
    ("求函数 f(x)=sin(x) 的导数", "cos(x)"),
    ("Calculate 1^999999999999999 mod 7", "1"),
])
def test_unsupported_conditions_and_resources_abstain(problem, answer):
    assert r._bounded_task_check(problem, answer) == "unknown"


def test_exact_complete_evidence_beats_wrong_majority_without_new_calls():
    client = Client(["最终答案：3", "最终答案：3", "最终答案：-2"] + ["VERDICT: A"]*3)
    result = r.ReasoningAgent(client, local_policy=r.Q1Policy(bounded_math=True)).solve(
        "Compute the determinant of [[1,2],[3,4]]", {"answer": "PRIVATE_ANSWER"})
    assert result["final_response"] == "最终答案：-2"
    assert len(client.calls) == 6
    assert "PRIVATE_ANSWER" not in json.dumps(client.calls)


def test_exact_recovery_cannot_pass_an_incorrect_determinant():
    client = Client(["unfinished", "最终答案：3"])
    config = r.AgentConfig(tool_candidates=0, plain_candidates=1)
    result = r.ReasoningAgent(client, config, local_policy=r.Q1Policy(bounded_math=True)).solve(
        "Compute the determinant of [[1,2],[3,4]]", {})
    assert result["final_response"] == "未解出"


def test_retrieval_only_one_generation_and_never_verifier_or_metadata():
    client = Client()
    result = r.ReasoningAgent(client, local_policy=r.Q1Policy(corpus_retrieval=True)).solve(
        "矩阵行列式在行交换后如何变化？", {"answer": "SECRET_LABEL"})
    refs = ["公开参考资料" in str(c[0]) for c in client.calls]
    assert refs == [False, False, True, False, False, False]
    assert "SECRET_LABEL" not in json.dumps(client.calls)
    assert "Hefferon" not in json.dumps(result["trace"])


@pytest.mark.parametrize("extra", [{}, {"diverse_candidates": True}, {"tool_aware_prompts": True}])
def test_condition_checks_apply_to_all_generation_without_changing_settings(extra):
    client = Client()
    r.ReasoningAgent(client, local_policy=r.Q1Policy(condition_checks=True, **extra)).solve("原题题面", {})
    assert all("解题检查" in c[0][-1]["content"] for c in client.calls[:3])
    assert all(c[0][-1]["content"].startswith("原题题面\n\n") for c in client.calls[:3])
    assert all("解题检查" not in c[0][0]["content"] for c in client.calls[3:])
    assert [c[2] for c in client.calls] == [8192]*3 + [1024]*3


@pytest.mark.parametrize("deployed", [False, True])
def test_disabled_or_unavailable_corpus_preserves_normal_path(monkeypatch, deployed):
    calls = []
    def unavailable():
        calls.append(1)
        raise ValueError("broken corpus")
    monkeypatch.setattr(r, "load_public_corpus", unavailable)
    baseline, enabled = Client(), Client()
    policy = r.legacy_deployment_policy() if deployed else r.Q1Policy()
    a = r.ReasoningAgent(baseline, local_policy=policy).solve("原题", {})
    assert not calls
    b = r.ReasoningAgent(enabled, local_policy=replace(policy, corpus_retrieval=True)).solve("原题", {})
    assert calls == [1]
    assert baseline.calls == enabled.calls
    assert a["final_response"] == b["final_response"]


def test_first_batch_defaults_and_registration():
    policy = asdict(r.Q1Policy())
    for name in ("bounded_math", "condition_checks", "corpus_retrieval"):
        assert policy[name] is False
        assert name in VARIANTS


@pytest.mark.parametrize("batch,limit", [("b1", 8192), ("b2", 512), ("conditions", 8192)])
def test_live_stage_plan_is_one_request_and_strictly_single_variable(batch, limit):
    from evaluation.xh_first_batch import stage_payload
    old, _ = stage_payload("求函数 f(x)=x^2 的导数", batch, False)
    new, _ = stage_payload("求函数 f(x)=x^2 的导数", batch, True)
    assert old != new
    assert set(old) == set(new) == {"messages", "temperature", "max_tokens", "thinking_mode"}
    assert old["thinking_mode"] is new["thinking_mode"] is False
    assert old["max_tokens"] == new["max_tokens"] == limit
    assert old["temperature"] == new["temperature"]


def test_frozen_live_controller_consumes_exact_plan_and_cannot_restart(tmp_path, monkeypatch):
    import dotenv
    from evaluation import xh_first_batch as pilot
    fixture_root = tmp_path / "fixture-root"
    inputs = fixture_root / "outputs/q0-umath-v4/dev.input.jsonl"
    inputs.parent.mkdir(parents=True)
    inputs.write_text("\n".join(json.dumps({"idx": i, "problem": f"计算{i}+1"}) for i in range(72)), encoding="utf-8")
    monkeypatch.setattr(pilot, "ROOT", fixture_root)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda _: {"INTERN_API_KEY": "fixture-key"})
    monkeypatch.delenv("INTERN_API_KEY", raising=False)
    seen = []
    def sender(payload):
        seen.append(copy.deepcopy(payload))
        assert payload["thinking_mode"] is False
        return {"response": "最终答案：2", "metadata": {"model": pilot.MODEL, "attempts": 1,
            "finish_reason": "stop", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}}
    monkeypatch.setattr(pilot.control, "make_http_sender", lambda *args: sender)
    pilot.prepare(tmp_path)
    result = pilot.execute(tmp_path)
    assert result["status"] == "completed"
    assert len(seen) == 36
    assert sum(p["max_tokens"] for p in seen) == 172032
    with pytest.raises(ValueError, match="already used"):
        pilot.execute(tmp_path)


def test_live_uncertain_transport_stops_all_later_batches(tmp_path, monkeypatch):
    import dotenv
    from evaluation import xh_first_batch as pilot
    fixture_root = tmp_path / "fixture-root"
    inputs = fixture_root / "outputs/q0-umath-v4/dev.input.jsonl"
    inputs.parent.mkdir(parents=True)
    inputs.write_text("\n".join(json.dumps({"idx": i, "problem": f"计算{i}+1"}) for i in range(72)), encoding="utf-8")
    monkeypatch.setattr(pilot, "ROOT", fixture_root)
    monkeypatch.setattr(dotenv, "dotenv_values", lambda _: {"INTERN_API_KEY": "fixture-key"})
    monkeypatch.delenv("INTERN_API_KEY", raising=False)
    def fail(payload):
        raise TimeoutError("fixture uncertain response")
    monkeypatch.setattr(pilot.control, "make_http_sender", lambda *args: fail)
    pilot.prepare(tmp_path)
    result = pilot.execute(tmp_path)
    assert result["status"] == "stopped"
    assert result["batches"]["b1"]["attempts"] == 1
    assert not (tmp_path / "b2").exists()


def test_new_features_preserve_foreign_module_ownership(monkeypatch):
    names = ("xh202627_corpus", "llm_client", "budget", "domain_prompts", "answer_equivalence", "agent_types")
    foreign = {name: types.ModuleType(name) for name in names}
    for name, module in foreign.items():
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(r.__file__)
    spec = importlib.util.spec_from_file_location("first_batch_foreign_entry", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    client = Client()
    result = module.ReasoningAgent(client, local_policy=module.Q1Policy(
        corpus_retrieval=True, condition_checks=True, bounded_math=True)).solve("计算1+1", {})
    assert result["final_response"] == "最终答案：2"
    assert all(sys.modules[name] is obj for name, obj in foreign.items())
