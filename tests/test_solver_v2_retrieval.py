"""Whole-flow retrieval: identity, independent evidence, faults and hard bounds."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path

import pytest

import xh202627_corpus as corpus
from evaluation.xh_answer_bank import build_answer_bank
from evaluation.solver_v2_retrieval_audit import extract_methods


def _record(problem, index=0, answer="-2"):
    return {"id": f"v2-fixture-{index}", "problem": problem, "answer": answer,
            "solution": "Use cofactor expansion: multiply diagonals then subtract. Since this is a two by two matrix, its determinant is the product of the diagonal entries minus the product of the other two entries. Therefore the result is " + answer,
            "source": "Synthetic test fixture", "source_url": "https://example.org/fixture",
            "source_revision": "fixture-1", "source_sha256": "1" * 64, "license": "CC0-1.0",
            "split": "public_corpus", "domain": "linear_algebra", "trust": "source_verified"}


@pytest.fixture
def fixture_bank(tmp_path, monkeypatch):
    question = "Use cofactor expansion to find the determinant of the matrix [[1,2],[3,4]]."
    rows = [_record(question)]
    report = build_answer_bank(rows, tmp_path)
    bank = corpus.AnswerBank(tmp_path, report["manifest_sha256"])
    monkeypatch.setattr(corpus, "load_answer_bank", lambda: bank)
    return bank, rows


def test_exact_identity_and_separate_method_channel(fixture_bank):
    _, rows = fixture_bank
    plan = corpus.build_evidence_plan(rows[0]["problem"])
    assert plan["status"] == "ready"
    assert plan["exact_record"] == rows[0]
    assert "same_full_question" in plan["reference"]
    assert "source_answer" not in plan["methods"]
    assert "v2-fixture" not in plan["methods"]
    assert plan["counters"]["exact_matches"] == 1
    assert plan["counters"]["bank_records"] == 1


def test_parameter_sign_domain_and_subquestion_mutations_cannot_fast_match(tmp_path, monkeypatch):
    originals, mutations = [], []
    for i in range(20):
        question = f"For x in (0,{i+2}], A=[[{i},2],[3,4]], A is not singular. Find det(A); then rank(A)."
        originals.append(_record(question, i))
        mutations.extend((question.replace(f"(0,{i+2}]", f"[0,{i+2}]"),
                          question.replace(f"[[{i},2]", f"[[-{i+1},2]"),
                          question.replace("not singular", "singular"),
                          question.replace("then rank(A)", "then rank(a)"),
                          question.replace("; then rank(A)", "")))
    report = build_answer_bank(originals, tmp_path)
    bank = corpus.AnswerBank(tmp_path, report["manifest_sha256"])
    monkeypatch.setattr(corpus, "load_answer_bank", lambda: bank)
    monkeypatch.setattr(corpus, "_v2_methods", lambda *args: "")
    assert all(corpus.build_evidence_plan(row["problem"])["exact_record"] == row for row in originals)
    for question in mutations:
        plan = corpus.build_evidence_plan(question)
        assert plan["exact_record"] is None
        assert "same_full_question" not in plan["reference"]


def test_bilingual_methods_retrieval_preserves_conditions():
    for question in ("矩阵的秩与零空间维数有什么关系？", "What is the relation between matrix rank and nullity?"):
        plan = corpus.build_evidence_plan(question)
        assert plan["methods"]
        assert "conditions" in plan["methods"]
        assert "license" in plan["methods"]
        assert "nullity" in plan["methods"].lower()
        assert plan["counters"]["resource_errors"] == 0


def test_latex_task_recall_does_not_relax_identity(fixture_bank):
    assert "integration" in corpus.evidence_terms(r"Evaluate $\int x^2 dx$.")
    changed = "用余子式展开求矩阵 [[1,2],[3,4]] 的行列式。"
    plan = corpus.build_evidence_plan(changed)
    assert plan["exact_record"] is None


def test_near_reference_explicitly_keeps_original_conditions(fixture_bank):
    _, rows = fixture_bank
    query = rows[0]["problem"].replace("[[1,2],[3,4]]", "[[9,2],[3,4]]")
    plan = corpus.build_evidence_plan(query)
    assert plan["exact_record"] is None
    assert "different_question_reference_only" in plan["reference"]
    assert "[[1,2],[3,4]]" in plan["reference"]
    assert "applicability" in plan["reference"]


def test_weak_generic_integral_and_function_conflicts_rejected():
    query = "Evaluate the integral of sin(x)."
    row = _record("Evaluate the integral of exp(x).")
    assert corpus._v2_reference_score(query, row, corpus.evidence_terms(query)) == 0
    row = _record("Evaluate the integral of a function.")
    assert corpus._v2_reference_score("Evaluate the integral.", row, corpus.evidence_terms("Evaluate the integral.")) == 0
    assert corpus.build_evidence_plan("求积分 x^2 dx。")["methods"] == ""


def test_unrelated_linear_algebra_methods_not_injected_into_counting():
    result = corpus.build_evidence_plan("有多少种从 n 个不同元素中选 k 个的方法？")
    assert result["methods"]
    assert "Jim Hefferon" not in result["methods"]


def test_healthy_miss_distinguished_from_unavailable(fixture_bank, monkeypatch):
    monkeypatch.setattr(corpus, "_v2_methods", lambda *args: "")
    query = "zzqxv unrelatedword"
    assert corpus.build_evidence_plan(query)["status"] == "miss"
    bank, _ = fixture_bank
    (bank.root / "manifest.json").write_text("damaged", encoding="utf-8")
    result = corpus.build_evidence_plan(query)
    assert result["status"] == "unavailable"
    assert result["counters"]["resource_errors"] == 1
    assert result["exact_record"] is None


def test_broken_method_resource_keeps_valid_qa(fixture_bank, monkeypatch):
    def broken():
        raise OSError("secret path should never escape")
    monkeypatch.setattr(corpus, "load_method_cards", broken)
    result = corpus.build_evidence_plan(fixture_bank[1][0]["problem"])
    assert result["status"] == "ready"
    assert result["exact_record"] is not None
    assert result["counters"]["resource_errors"] == 1
    assert "secret path" not in json.dumps(result)


@pytest.mark.parametrize("query", [None, {}, 0, [], "", " \n", "q" * 20001, "x\x00y"])
def test_invalid_input_is_bounded_without_resource_reads(query, monkeypatch):
    def forbidden():
        raise AssertionError("invalid input caused I/O")
    monkeypatch.setattr(corpus, "load_answer_bank", forbidden)
    monkeypatch.setattr(corpus, "load_method_cards", forbidden)
    result = corpus.build_evidence_plan(query)
    assert result["status"] == "miss"
    assert result["counters"]["invalid_input"] == 1
    assert result["counters"]["resource_errors"] == 0


def test_reference_and_read_budgets(fixture_bank):
    for question in (fixture_bank[1][0]["problem"], "Find eigenvalues, rank, determinant and inverse of a matrix.", "积分 " * 5000):
        plan = corpus.build_evidence_plan(question)
        counters = plan["counters"]
        assert len(plan["reference"]) <= corpus.MAX_REFERENCE_CHARS
        assert len(plan["methods"]) <= corpus.MAX_REFERENCE_CHARS
        assert counters["bank_bytes"] <= corpus.ANSWER_BANK_MAX_BYTES
        assert counters["bank_bodies"] <= corpus.ANSWER_BANK_MAX_BODIES
        assert counters["bank_postings"] <= corpus.ANSWER_BANK_MAX_POSTINGS
        assert counters["method_references"] <= 3
        assert all(type(value) is int and value >= 0 for value in counters.values())


def test_concurrent_queries_do_not_retain_answers(fixture_bank):
    bank, rows = fixture_bank
    questions = [rows[0]["problem"], "Unmatched private fixture marker 817391"] * 6
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(corpus.build_evidence_plan, questions))
    for question, result in zip(questions, results):
        assert (result["exact_record"] is not None) == (question == rows[0]["problem"])
    assert set(bank.__dict__) == {"root", "expected_sha256"}
    assert "817391" not in repr(bank.__dict__)
    results[0]["exact_record"]["answer"] = "changed"
    assert corpus.build_evidence_plan(rows[0]["problem"])["exact_record"] == rows[0]


def test_frozen_bank_and_new_method_source_integrity():
    root = Path(__file__).resolve().parents[1]
    assert sha256((root / "resources/answer_bank/manifest.json").read_bytes()).hexdigest() == corpus.ANSWER_BANK_SHA256
    rows = corpus.load_method_cards()
    assert len(rows) == 88
    assert all(row["license"] == "CC-BY-SA-4.0" for row in rows)
    assert all(row["kind"] not in {"answer", "solution", "example", "exercise"} for row in rows)
    assert not any("Brooks" in row["title"] for row in rows)
    assert not any(row["title"] == "Euler Paths and Circuits" for row in rows)
    assert not any(row["title"] == "Ratio and root tests for power series" for row in rows)


@pytest.mark.parametrize("problem,reference", [
    ("Solve the real equation x^2+3*x=7.", "Solve the differential equation y''+3*y=7."),
    ("Solve the absolute value equation x^2-|x|=7.", "Find integer solutions of x^2-y^2=7."),
    ("Find the radius and center of convergence of the power series.", "Find the radius and interval of convergence of the power series."),
    ("Find the partial sum with error below 0.001 for the series.", "Find the sum of the series."),
    ("Find an integral for the region common to r=3 and r=6*cos(theta).", "Find an integral for one petal of r=cos(3*theta)."),
    (r"For which p does the series $\sum p^{n^2}/3^n$ converge?", r"For which x does the series $\sum x^n/n^2$ converge?"),
])
def test_task_domain_and_target_mutations_never_authorize_qa_reference(problem, reference):
    assert not corpus._v2_task_compatible(problem, reference)
    row = _record(reference)
    assert corpus._v2_reference_score(problem, row, corpus.evidence_terms(problem)) == 0


def test_wrong_domain_methods_rejected_for_equations_and_nonplanar_unknown():
    for problem in ("Find all real solutions of the equation x/(x+2)=3.",
                    "Solve the absolute value equation x^2-2*|x|-3=0."):
        assert corpus.build_evidence_plan(problem)["methods"] == ""
    plan = corpus.build_evidence_plan("Find the chromatic number of the graph K_4,7.")
    assert "Four Color Theorem" not in plan["methods"]
    assert "Vizing" not in plan["methods"]
    assert "Handshake" not in plan["methods"]
    assert "Spanning tree" not in plan["methods"]


def test_methods_remain_available_for_explicit_relevant_tasks():
    cases = {"Explain existence and uniqueness of a first order differential equation initial value problem.": "existence",
             "State the congruence arithmetic rules modulo a positive integer n.": "Congruence",
             "Explain mathematical induction proof structure for a sequence.": "Induction",
             "State the rank nullity theorem for a matrix.": "Rank--Nullity"}
    for problem, title in cases.items():
        assert title.casefold() in corpus.build_evidence_plan(problem)["methods"].casefold()


def test_similar_question_bare_answer_is_not_a_worked_reference():
    row = _record("Use cofactor expansion to find determinant of matrix [[8,2],[3,4]].")
    row["solution"] = "The final answer: 26"
    row["answer"] = "26"
    assert not corpus._v2_worked_reference(row)


def test_method_channel_excludes_hefferon_example_cards(monkeypatch):
    example = {"id": "ex-fixture", "title": "Linear maps: ex:Test", "text": "SECRET_EXAMPLE_ANSWER", "source": "fixture", "license": "CC-BY-SA-2.5"}
    class TheoryFixture:
        cards = [example]
    monkeypatch.setattr(corpus, "load_corpus", TheoryFixture)
    monkeypatch.setattr(corpus, "load_method_cards", lambda: [])
    counters = {"resource_errors": 0, "method_references": 0}
    assert corpus._v2_methods("Linear maps and matrix", counters) == ""
    assert counters["method_cards"] == 0


def _source_fixture(root, xml):
    for name, license_name, marker in (("diffyqs", "LICENSE.md", "Attribution-Share Alike 4.0"),
                                       ("dmoi3", "LICENSE", "Attribution-ShareAlike 4.0")):
        directory = root / name
        directory.mkdir()
        (directory / license_name).write_text(marker, encoding="utf-8")
        files = []
        if name == "dmoi3":
            raw = xml.encode("utf-8")
            (directory / "source.ptx").write_bytes(raw)
            files = [{"path": "source.ptx", "url": "https://example.org/source.ptx", "sha256": sha256(raw).hexdigest()}]
        (directory / "provenance.json").write_text(json.dumps({"revision": "2" * 40, "files": files}), encoding="utf-8")


def test_method_builder_preserves_hypotheses_excludes_solution_and_crossref(tmp_path):
    body = "For a finite simple undirected graph T, T is a tree if and only if each distinct pair of vertices has exactly one path between them."
    xml = ("<section><theorem><title>Tree characterization</title><statement><p>" + body + "</p></statement>"
           "<proof><p>PROOF_SENTINEL_8173</p></proof></theorem>"
           "<example><theorem><statement><p>" + body + "ANSWER_SENTINEL_319</p></statement></theorem></example>"
           "<theorem><statement><p>" + body + '<xref ref="missing"/></p></statement></theorem></section>')
    _source_fixture(tmp_path, xml)
    rows, _ = extract_methods(tmp_path)
    assert len(rows) == 1
    assert rows[0]["text"] == body
    assert "finite simple undirected" in rows[0]["text"]
    assert "exactly one" in rows[0]["text"]
    assert "SENTINEL" not in json.dumps(rows)


def test_method_builder_rejects_source_digest_change(tmp_path):
    _source_fixture(tmp_path, "<section/>")
    (tmp_path / "dmoi3/source.ptx").write_text("<section>changed</section>", encoding="utf-8")
    with pytest.raises(ValueError, match="source integrity"):
        extract_methods(tmp_path)


def test_method_builder_rejects_path_escape(tmp_path):
    _source_fixture(tmp_path, "<section/>")
    path = tmp_path / "dmoi3/provenance.json"
    provenance = json.loads(path.read_bytes())
    provenance["files"][0]["path"] = "../outside.ptx"
    path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(ValueError, match="path containment"):
        extract_methods(tmp_path)
