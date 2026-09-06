import importlib.util
from pathlib import Path
import sys
import types

import pytest

from evaluation.judge import judge_answer
from answer_equivalence import normalize_answer, equivalent_answers, numeric_value


@pytest.mark.parametrize("left,right", [("x/x", "1"), ("(x**2-1)/(x-1)", "x+1"),
    ("sqrt(x)**2", "x"), ("log(x*y)", "log(x)+log(y)")])
def test_symbolic_domain_assumptions_cannot_be_silently_discarded(left, right):
    assert judge_answer(left, right).status == "unknown"


@pytest.mark.parametrize("top,bottom", [("1+1", "2"), ("x+1", "x-1"), ("1", "2+3"), ("x*y", "z+w")])
def test_fraction_grouping_and_normalization_idempotence(top, bottom):
    raw = "\\frac{" + top + "}{" + bottom + "}"
    normalized = normalize_answer(raw)
    assert normalize_answer(normalized) == normalized
    assert equivalent_answers(raw, top+"/"+bottom) is not True


def test_compound_numeric_fraction_is_not_misgraded_as_flat_precedence():
    assert judge_answer(r"\frac{1+1}{2}", "1+1/2").status == "wrong"


@pytest.mark.parametrize("left,right", [("x", "X"), ("a+b", "A+B"), ("Z", "z"), ("C1", "c1")])
def test_symbol_case_does_not_create_false_canonical_equivalence(left, right):
    assert equivalent_answers(left, right) is not True


@pytest.mark.parametrize("text", ["1e999999999", "1e-999999999", "1e1001", "1e-1001", "9"*2049])
def test_excessive_numeric_representation_is_bounded_before_fraction_conversion(text):
    assert numeric_value(text) is None


def test_small_scientific_values_and_categorical_case_still_work():
    assert numeric_value("1e3") == 1000
    assert equivalent_answers("TRUE", "true") is True


def test_all_q1_features_survive_foreign_module_preloads(monkeypatch):
    foreign = {name: types.ModuleType(name) for name in ("llm_client", "agent_types", "budget",
        "answer_equivalence", "domain_prompts", "math_tools", "tool_executor", "local_support", "deterministic_verifier")}
    for name,module in foreign.items():
        monkeypatch.setitem(sys.modules, name, module)
    path = Path(__file__).resolve().parents[1]/"user_agent.py"
    spec = importlib.util.spec_from_file_location("q1_audit_entry", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    class Client:
        def chat(self, *, messages, temperature, max_tokens):
            return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：2"
        def __getattr__(self, name):
            raise AssertionError("unexpected client probe: " + name)
    policy = module.Q1Policy(True, True, True, True, True)
    result = module.ReasoningAgent(Client(), local_policy=policy).solve("计算1+1", {"answer": "999"})
    assert result["final_response"] == "最终答案：2"
    assert all(sys.modules[name] is original for name,original in foreign.items())
