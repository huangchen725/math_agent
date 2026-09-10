"""Independent whole-question, artifact-integrity and bounded-retrieval checks."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

import xh202627_corpus as bank
from evaluation.xh_answer_bank import build_answer_bank, canonical_bytes, read_records


def record(problem="Use cofactor expansion to find the determinant of the matrix [[1,2],[3,4]].", *, id="fixture-1", answer="-2"):
    return {
        "id": id, "problem": problem, "answer": answer,
        "solution": "The determinant is 1*4 - 2*3 = -2.",
        "source": "Project-authored synthetic fixture", "source_url": "https://example.org/math",
        "license": "CC0-1.0", "source_revision": "fixture-v1", "source_sha256": "1" * 64,
        "split": "public_corpus", "domain": "linear_algebra", "trust": "source_verified",
        "metadata": {"verification": "synthetic_test_only"},
    }


@pytest.fixture
def small_bank(tmp_path):
    rows = [record(), record("Find the determinant of the matrix [[5,6],[7,8]].",
                             id="fixture-2", answer="-2")]
    report = build_answer_bank(rows, tmp_path)
    return bank.AnswerBank(tmp_path, report["manifest_sha256"]), rows


def _repin_manifest(root, manifest):
    raw = canonical_bytes(manifest)
    (root / "manifest.json").write_bytes(raw)
    return bank.AnswerBank(root, sha256(raw).hexdigest())


def _change_page(reader, kind, bucket, mutate):
    root = reader.root
    manifest = json.loads((root / "manifest.json").read_bytes())
    path = root / kind / f"{bucket}.json"
    page = json.loads(path.read_bytes())
    mutate(page)
    raw = canonical_bytes(page)
    path.write_bytes(raw)
    manifest[kind][bucket] = {"size": len(raw), "sha256": sha256(raw).hexdigest()}
    return _repin_manifest(root, manifest)


def test_constructor_and_default_factory_are_lazy(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("construction performed resource I/O")
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "stat", forbidden)
        bank.AnswerBank(tmp_path, "0" * 64)
        result = bank.load_answer_bank()
    assert isinstance(result, bank.AnswerBank)


def test_source_answer_roundtrip_and_independent_return(small_bank):
    reader, rows = small_bank
    assert reader.lookup(rows[0]["problem"]) == rows[0]
    result = reader.lookup(rows[0]["problem"])
    result["answer"] = "corrupted by caller"
    result["metadata"]["verification"] = "corrupted"
    assert reader.lookup(rows[0]["problem"]) == rows[0]
    assert not hasattr(reader, "last_problem")
    assert not hasattr(reader, "last_answer")


def test_transport_normalization_only(tmp_path):
    row = record("For x > 0,\nfind f(x).")
    report = build_answer_bank([row], tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    assert reader.lookup("  For x > 0,\r\nfind f(x).\n") == row
    for altered in ("For x > 0, find f(x).", "for x > 0,\nfind f(x).",
                    "For x ≥ 0,\nfind f(x).", "For x > 0,\nfind f(X)."):
        assert reader.lookup(altered) is None


def test_360_condition_mutations_never_match(tmp_path):
    # Independent semantic distinctions: positive evidence plus every changed
    # condition, rather than deriving expected results from the normalizer.
    originals = []
    mutations = []
    for n in range(60):
        question = (f"For every x in (0,{n + 2}], matrix A=[[{n},2],[3,4]], "
                    "assume A is not singular. Find det(A); then determine rank(A).")
        originals.append(record(question, id=f"property-{n}"))
        mutations.extend([
            question.replace(f"(0,{n + 2}]", f"[0,{n + 2}]"),
            question.replace(f"[[{n},2]", f"[[{n + 1},2]"),
            question.replace("not singular", "singular"),
            question.replace("every x", "some x"),
            question.replace("rank(A)", "rank(a)"),
            question.replace("; then determine rank(A)", ""),
        ])
    report = build_answer_bank(originals, tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    for row in originals:
        assert reader.lookup(row["problem"]) == row
    assert len(mutations) == 360
    for changed in mutations:
        assert reader.lookup(changed) is None


def test_tex_unicode_operators_and_spacing_are_not_collapsed(small_bank):
    reader, _ = small_bank
    variants = [
        "Find the determinant of the matrix [[1,2],[3,5]].",
        "Find the determinant of the matrix [[1,-2],[3,4]].",
        "Find the determinant of the matrix [[1,2],[3,4]]; also find its inverse.",
        "Find the determinant of the matrix [[1,2],[3,4.0]].",
        "Find the determinant of the matrix [[１,2],[3,4]].",
        "Find the determinant of the matrix [[1, 2],[3,4]].",
    ]
    assert len({bank.answer_bank_key(p) for p in variants}) == len(variants)
    assert all(reader.lookup(p) is None for p in variants)


@pytest.mark.parametrize("bad", [None, {}, [], 3, "", " \n", "x" * 20001, "x\x00y"])
def test_invalid_queries_are_optional_misses(small_bank, bad):
    reader, _ = small_bank
    assert reader.lookup(bad) is None
    assert reader.context(bad) == ""


def test_conflicting_answers_quarantine_entire_question(tmp_path):
    left = record()
    right = record(id="conflict", answer="2")
    survivor = record("Find the determinant of the identity matrix.", id="safe", answer="1")
    report = build_answer_bank([left, right, survivor], tmp_path)
    assert report["conflict_count"] == 1
    assert report["record_count"] == 1
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    assert reader.lookup(left["problem"]) is None
    assert reader.lookup(survivor["problem"]) == survivor


def test_reproducible_bytes_under_input_reordering_and_dedup(tmp_path):
    rows = [record(id="b"), record(id="a"), record("Evaluate 2+2.", id="c", answer="4")]
    first = build_answer_bank(rows, tmp_path / "a")
    second = build_answer_bank(reversed(rows), tmp_path / "b")
    assert first == second
    assert first["duplicate_count"] == 1
    assert first["record_count"] == 2
    files_a = {p.relative_to(tmp_path / "a").as_posix(): p.read_bytes()
               for p in (tmp_path / "a").rglob("*") if p.is_file()}
    files_b = {p.relative_to(tmp_path / "b").as_posix(): p.read_bytes()
               for p in (tmp_path / "b").rglob("*") if p.is_file()}
    assert files_a == files_b
    reader = bank.AnswerBank(tmp_path / "a", first["manifest_sha256"])
    assert reader.lookup(rows[0]["problem"])["id"] == "a"


def test_exclusion_can_overreject_but_never_widen_runtime_identity(tmp_path):
    excluded = record("Find $x$ for x=1.", id="dev")
    survivor = record()
    report = build_answer_bank([excluded, survivor], tmp_path,
                               exclude_problems=[" find x FOR x=1. "])
    assert report["excluded_count"] == 1
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    assert reader.lookup(excluded["problem"]) is None
    assert reader.lookup(survivor["problem"]) == survivor


@pytest.mark.parametrize("field,value", [
    ("trust", "model_generated"), ("split", "holdout"), ("split", "official"),
    ("source_sha256", "bad"), ("source_url", "file:///private"),
    ("source_revision", ""), ("answer", ""), ("answer", "x" * 12001),
    ("id", "../../escape"), ("metadata", {"x": float("nan")}),
])
def test_unqualified_provenance_and_fields_rejected(tmp_path, field, value):
    row = record()
    row[field] = value
    with pytest.raises(ValueError):
        build_answer_bank([row], tmp_path)


def test_missing_corrupt_manifest_and_index_are_optional(small_bank):
    reader, rows = small_bank
    assert bank.AnswerBank(reader.root / "missing", reader.expected_sha256).lookup(rows[0]["problem"]) is None
    assert bank.AnswerBank(reader.root, "0" * 64).lookup(rows[0]["problem"]) is None
    bucket = sha256(bank.answer_bank_key(rows[0]["problem"]).encode()).hexdigest()[:2]
    (reader.root / "exact" / f"{bucket}.json").write_bytes(b"{}")
    assert reader.lookup(rows[0]["problem"]) is None
    (reader.root / "manifest.json").write_bytes(b"{")
    assert reader.lookup(rows[0]["problem"]) is None


def test_index_and_record_digest_chains_are_independent(small_bank):
    reader, rows = small_bank
    row = rows[0]
    digest = sha256(bank.answer_bank_key(row["problem"]).encode()).hexdigest()
    page = json.loads((reader.root / "exact" / f"{digest[:2]}.json").read_bytes())
    ref = page[digest]
    path = reader.root / "records" / f"{ref[0]}.jsonl"
    raw = bytearray(path.read_bytes())
    raw[ref[1] + 10] ^= 1
    path.write_bytes(raw)
    assert reader.lookup(row["problem"]) is None


@pytest.mark.parametrize("part,value", [(0, "../escape"), (1, -1), (1, True), (1, 999999999),
                                        (2, 65537), (2, 0), (3, "bad"), (4, "f" * 64)])
def test_even_repinned_invalid_record_references_fail_closed(small_bank, part, value):
    reader, rows = small_bank
    digest = sha256(bank.answer_bank_key(rows[0]["problem"]).encode()).hexdigest()
    def change(page):
        page[digest][part] = value
    reader = _change_page(reader, "exact", digest[:2], change)
    assert reader.lookup(rows[0]["problem"]) is None


def test_wrong_record_with_a_valid_digest_never_becomes_exact_match(small_bank):
    reader, rows = small_bank
    first = sha256(bank.answer_bank_key(rows[0]["problem"]).encode()).hexdigest()
    second = sha256(bank.answer_bank_key(rows[1]["problem"]).encode()).hexdigest()
    ref = json.loads((reader.root / "exact" / f"{second[:2]}.json").read_bytes())[second]
    reader = _change_page(reader, "exact", first[:2], lambda page: page.update({first: ref}))
    assert reader.lookup(rows[0]["problem"]) is None


def test_read_bytes_and_deadline_caps_fail_closed(small_bank, monkeypatch):
    reader, rows = small_bank
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_BYTES", 1)
    assert reader.lookup(rows[0]["problem"]) is None
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_BYTES", 4 * 1024 * 1024)
    moments = iter([0.0, 2.01])
    monkeypatch.setattr(bank, "monotonic", lambda: next(moments))
    assert reader.lookup(rows[0]["problem"]) is None


def test_material_has_one_shared_budget_and_never_restarts_after_miss(small_bank, monkeypatch):
    reader, _ = small_bank
    created = []
    original_budget = bank._AnswerReadBudget
    class ObservedBudget(original_budget):
        def __init__(self):
            super().__init__()
            created.append(self)
    monkeypatch.setattr(bank, "_AnswerReadBudget", ObservedBudget)
    query = "Use cofactor expansion to find the determinant of the matrix [[20,22],[33,44]]."
    assert reader.material(query)["context"]
    assert len(created) == 1
    used = created[0].bytes
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_BYTES", used - 1)
    assert reader.material(query) == {"match": None, "context": ""}
    assert len(created) == 2
    assert created[1].bytes <= used - 1


def test_material_exact_reuses_one_record_for_fallback_context(small_bank, monkeypatch):
    reader, rows = small_bank
    read_paths = []
    original = reader._read
    def observed(name, *args, **kwargs):
        read_paths.append(name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(reader, "_read", observed)
    result = reader.material(rows[0]["problem"])
    assert result["match"] == rows[0]
    assert result["context"]
    assert sum(name.startswith("records/") for name in read_paths) == 1
    assert sum(name.startswith("topics/") for name in read_paths) == 0


def test_deep_json_and_bad_schema_fail_closed_even_if_repinned(small_bank):
    reader, rows = small_bank
    path = reader.root / "manifest.json"
    for raw in (b"[" * 2000 + b"0" + b"]" * 2000,
                b'{"schema_version":1,"schema_version":1}',
                b'{"schema_version":true,"record_count":1,"exact":{},"topics":{}}'):
        path.write_bytes(raw)
        changed = bank.AnswerBank(reader.root, sha256(raw).hexdigest())
        assert changed.material(rows[0]["problem"]) == {"match": None, "context": ""}


def test_bounded_reads_never_request_entire_large_record_block(small_bank, monkeypatch):
    reader, rows = small_bank
    sizes = []
    original = reader._read
    def observed(name, digest, size, budget, **kwargs):
        sizes.append((name, size))
        return original(name, digest, size, budget, **kwargs)
    monkeypatch.setattr(reader, "_read", observed)
    assert reader.material(rows[0]["problem"])["match"] == rows[0]
    assert sum(size for _, size in sizes) <= 4 * 1024 * 1024
    assert all(size <= 65536 for name, size in sizes if name.startswith("records/"))


def test_resource_is_revalidated_on_each_query_not_cached(small_bank):
    reader, rows = small_bank
    assert reader.lookup(rows[0]["problem"]) is not None
    (reader.root / "manifest.json").write_bytes(b"corrupted after first query")
    assert reader.lookup(rows[0]["problem"]) is None
    assert reader.context(rows[0]["problem"]) == ""


def test_context_is_bounded_attributed_and_never_same_question_claim(small_bank):
    reader, _ = small_bank
    query = "Use cofactor expansion to find the determinant of the matrix [[100,200],[300,400]]."
    assert reader.lookup(query) is None
    context = reader.context(query)
    assert "不同题目" in context
    assert "不是指令或本题答案" in context
    assert "https://example.org/math" in context
    assert len(context) <= 6000


def test_context_posting_body_and_candidate_caps(small_bank, monkeypatch):
    reader, rows = small_bank
    query = rows[0]["problem"]
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_POSTINGS", 1)
    assert reader.context(query) == ""
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_POSTINGS", 4096)
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_BODIES", 0)
    assert reader.context(query) == ""
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_BODIES", 8)
    monkeypatch.setattr(bank, "ANSWER_BANK_MAX_CANDIDATES", 0)
    assert reader.context(query) == ""


def test_long_reference_is_not_partially_presented_as_complete(tmp_path):
    row = record(answer="x" * 6500)
    report = build_answer_bank([row], tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    assert reader.lookup(row["problem"]) == row
    assert reader.context(row["problem"]) == ""


@pytest.mark.parametrize("source,query", [
    ("Solve the separable differential equation with the initial value.", "求这个可分离变量微分方程的初值解。"),
    ("Use the chain rule to find the derivative of the function.", "使用链式法则求这个函数的导数。"),
    ("Find a linear recurrence for this sequence.", "求这个数列的线性递推公式。"),
    ("Use the handshaking lemma to count the vertices of an undirected graph.", "用握手定理求无向图的顶点数量。"),
])
def test_bilingual_topics_supply_references_without_inventing_identity(tmp_path, source, query):
    row = record(source)
    report = build_answer_bank([row], tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    result = reader.material(query)
    assert result["match"] is None
    assert source in result["context"]
    assert "不同题目" in result["context"]


def test_bilingual_topic_stemming_does_not_change_old_terms_or_exact_keys():
    assert "derivative" not in bank.terms("求导数")
    assert "derivative" in bank.answer_bank_terms("求导数")
    assert bank.answer_bank_key("求函数f的导数") != bank.answer_bank_key("Find derivative of f")


def test_live_integral_reference_with_a_different_mechanism_is_rejected():
    # Fixed 2026-09-10 candidate/item-02 request-0003 retrieval failure.
    problem = "Solve the integral:\n$$\n\\int \\left(\\frac{ x+4 }{ x-4 } \\right)^{\\frac{ 3 }{ 2 }} \\, dx\n$$"
    unrelated = "Solve the integral:\n$$\n\\int \\frac{ \\cos(x)^3 }{ \\sin(x)^9 } \\, dx\n$$"
    assert not bank.answer_reference_eligible(problem, unrelated)
    assert bank.load_answer_bank().material(problem) == {"match": None, "context": ""}


def test_synonym_expansion_and_repetition_never_create_independent_evidence(tmp_path):
    source = record("Solve the integral. Find an antiderivative.", answer="C")
    report = build_answer_bank([source], tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    for n in range(1, 61):
        query = "Compute " + ("积分 integral integration antiderivative 原函数 " * n)
        assert bank.answer_reference_concepts(query) == frozenset({"task:integral"})
        assert not bank.answer_reference_eligible(query, source["problem"])
        assert reader.material(query) == {"match": None, "context": ""}


@pytest.mark.parametrize("fragment", ["x", "0", "=", "x=0", "x+1", "f(x)=0"])
def test_trivial_shared_math_is_not_method_evidence(fragment):
    query = "Find the integral with $" + fragment + "$ as a condition."
    reference = "Compute an antiderivative where $" + fragment + "$ holds."
    assert not bank.answer_reference_eligible(query, reference)


def test_nontrivial_same_math_fragment_is_reference_only(tmp_path):
    fragment = r"\int \frac{x+4}{x-4} dx"
    source = record("Compute the integral, an antiderivative, $" + fragment + "$.")
    query = "Find the integral antiderivative $" + fragment + "$."
    report = build_answer_bank([source], tmp_path)
    reader = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    assert bank.answer_reference_eligible(query, source["problem"])
    material = reader.material(query)
    assert material["match"] is None and material["context"]


def test_function_or_power_conflicts_override_shared_named_method():
    pairs = [
        (r"Use substitution to find the integral of $\sin(x)^3$.",
         r"Use substitution to find the integral of $\exp(x)^3$."),
        (r"Use substitution to find the integral of $x^{3/2}$.",
         r"Use substitution to find the integral of $x^{5/2}$."),
        (r"Use substitution to find the integral of $x^{\frac{3}{2}}$.",
         r"Use substitution to find the integral of $x^{\frac{5}{2}}$."),
    ]
    for query, reference in pairs:
        assert not bank.answer_reference_eligible(query, reference)


def test_named_method_requires_the_same_requested_operation():
    assert not bank.answer_reference_eligible(
        "Find an integral using the chain rule.", "Find a derivative using the chain rule.")


def test_rejected_weak_references_preserve_complete_no_reference_request_sequence(tmp_path, monkeypatch):
    from dataclasses import replace
    import user_agent as runtime

    class RecordedClient:
        def __init__(self):
            self.calls = []
        def chat(self, *, messages, temperature, max_tokens, thinking_mode):
            self.calls.append({"messages": messages, "temperature": temperature,
                               "max_tokens": max_tokens, "thinking_mode": thinking_mode})
            assert thinking_mode is False
            if "验证器" in messages[0]["content"]:
                return {"content": "CHECK: A deterministic fixture check gives 1+1=2.\nVERDICT: A", "finish_reason": "stop"}
            return {"content": "A deterministic fixture response.\n最终答案：2", "finish_reason": "stop"}

    row = record("Solve the integral; compute an antiderivative.", answer="C")
    report = build_answer_bank([row], tmp_path)
    synthetic = bank.AnswerBank(tmp_path, report["manifest_sha256"])
    cases = [
        (bank.load_answer_bank(), "Solve the integral:\n$$\n\\int \\left(\\frac{ x+4 }{ x-4 } \\right)^{\\frac{ 3 }{ 2 }} \\, dx\n$$"),
        (synthetic, "Find integral integration antiderivative 积分 原函数。"),
    ]
    for reader, problem in cases:
        assert reader.material(problem) == {"match": None, "context": ""}
        monkeypatch.setattr(runtime._dependencies["xh202627_corpus"], "load_answer_bank", lambda: reader)
        before, after = RecordedClient(), RecordedClient()
        disabled = replace(runtime.deployment_policy(), answer_bank_fastpath=False, answer_bank_reference=False)
        old = runtime.ReasoningAgent(before, local_policy=disabled).solve(problem, {})
        new = runtime.ReasoningAgent(after).solve(problem, {})
        assert len(before.calls) == len(after.calls) == 6
        assert before.calls == after.calls
        assert old["final_response"] == new["final_response"]


def test_json_duplicate_fields_and_oversized_input_rejected(tmp_path):
    path = tmp_path / "records.jsonl"
    row = record()
    raw = canonical_bytes(row).rstrip()
    path.write_bytes(raw[:-1] + b',"answer":"wrong"}\n')
    with pytest.raises(ValueError):
        list(read_records(path))
    path.write_bytes(b"x" * 65537)
    with pytest.raises(ValueError):
        list(read_records(path))


def test_builder_refuses_overwrite_and_duplicate_ids(tmp_path):
    build_answer_bank([record()], tmp_path / "bank")
    with pytest.raises(ValueError):
        build_answer_bank([record()], tmp_path / "bank")
    with pytest.raises(ValueError):
        build_answer_bank([record(), record("Other complete problem.")], tmp_path / "dupes")


def test_bank_loader_preserves_old_cards():
    old = bank.load_corpus()
    assert len(old.cards) == 160
    assert old.context("Find the determinant of a triangular matrix")
