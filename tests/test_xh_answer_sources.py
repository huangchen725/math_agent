"""Regression and source-boundary properties for offline public source adapters."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from evaluation.xh_answer_sources import (
    braced, clean_tex, diffyqs, dmoi_macros, finish, input_exclusions,
    isolation_key, json_bytes, record, render_xml,
)


def _diffy_source(tmp_path: Path, text: str) -> Path:
    raw = text.encode()
    (tmp_path / "ch-test.tex").write_bytes(raw)
    (tmp_path / "LICENSE.md").write_text("Attribution-Share Alike 4.0", encoding="utf-8")
    (tmp_path / "provenance.json").write_text(json.dumps({
        "revision": "a" * 40,
        "files": [{"path": "ch-test.tex", "sha256": sha256(raw).hexdigest(),
                   "url": "https://example.org/ch-test.tex"}],
    }), encoding="utf-8")
    return tmp_path


def test_unsolved_exercise_never_borrows_next_answer(tmp_path):
    source = _diffy_source(tmp_path, r"""
\begin{exercise}Unsolved task 1.\end{exercise}
\begin{exercise}Solve $y'=2y$, $y(0)=3$.\end{exercise}
\exsol{$y=3e^{2x}$}
\begin{exercise}Unsolved task 3.\end{exercise}
""")
    rows = diffyqs(source, Counter())
    assert len(rows) == 1
    assert rows[0]["problem"] == r"Solve $y'=2y$, $y(0)=3$."
    assert rows[0]["answer"] == "$y=3e^{2x}$"


def test_source_hash_mismatch_rejected(tmp_path):
    source = _diffy_source(tmp_path, r"\begin{exercise}Q\end{exercise}\exsol{A}")
    (source / "ch-test.tex").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="digest mismatch"):
        diffyqs(source, Counter())


def test_graph_and_cross_reference_pair_not_used(tmp_path):
    source = _diffy_source(tmp_path, r"""
\begin{exercise}See \exerciseref{a}.\end{exercise}\exsol{A}
\begin{exercise}Find graph below.\end{exercise}\exsol{\diffyincludegraphics{a}{b}{c}{d}}
""")
    assert diffyqs(source, Counter()) == []


def test_macro_prefixes_and_layout_preserve_math():
    assert clean_tex(r"\Rightarrow \Re \R \C \Cos") == r"\Rightarrow \Re \mathbb{R} \mathbb{C} \Cos"
    value = clean_tex(r"\pagebreak[2] \leavevmode \begin{tasks}(2)\task $x<2$\task $x\geq2$\end{tasks}")
    assert "[2]" not in value
    assert value == r"\begin{enumerate}\item $x<2$\item $x\geq2$\end{enumerate}"


@pytest.mark.parametrize("depth", range(1, 21))
def test_balanced_group_does_not_take_following_answer(depth):
    inner = "{" * depth + "x+1" + "}" * depth
    body, end = braced("{" + inner + "}SENTINEL{y}", 0)
    assert body == inner
    assert ("{" + inner + "}SENTINEL{y}")[end:] == "SENTINEL{y}"


def test_dangling_group_fails():
    with pytest.raises(ValueError, match="unclosed"):
        braced("{x{y}", 0)


def test_xml_math_and_subquestions_remain_separate():
    node = ET.fromstring("<statement><p>For every <m>x</m>:</p><ol><li><p>Find <m>x+1</m>.</p></li><li><p>Not <m>x-1</m>.</p></li></ol><p>1,2,<ellipsis/>; a<ndash/>b.</p></statement>")
    value = render_xml(node)
    assert r"\(x+1\)" in value and r"\(x-1\)" in value
    assert "(1)" in value and "(2)" in value
    assert "Not" in value and "1,2,..." in value and "a-b" in value


def test_multiline_math_closes_rows_before_display():
    node = ET.fromstring(r"<md><mrow>x \amp = 1</mrow><mrow>y \amp = 2</mrow></md>")
    assert dmoi_macros(render_xml(node)) == r"\[\begin{aligned}x &amp; = 1 \\ y &amp; = 2\end{aligned}\]".replace("&amp;", "&")


def test_source_defined_macro_expansion_keeps_unrelated_commands():
    value = dmoi_macros(r"\N \neg \imp \implies \card{A_{1}} \pow(X)")
    assert value == r"\mathbb{N} \neg \rightarrow \implies \left|A_{1}\right| \mathcal{P}(X)"


def test_exclusion_reads_only_question_inputs(tmp_path):
    labels = tmp_path / "test.labels.jsonl"
    labels.write_text('{"idx":"a","problem":"Q","answer":"SECRET"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="question-only"):
        input_exclusions([labels])
    inputs = tmp_path / "test.input.jsonl"
    inputs.write_bytes(labels.read_bytes())
    with pytest.raises(ValueError, match="label fields"):
        input_exclusions([inputs])


def test_numeric_variants_excluded_but_no_runtime_identity_claim():
    left, right = "Solve x+31=55", "Solve x+32=56"
    assert isolation_key(left) == isolation_key(right)
    from xh202627_corpus import answer_bank_key
    assert answer_bank_key(left) != answer_bank_key(right)


def test_conflicting_whole_question_quarantines_every_answer():
    base = record("dmoi3", "https://example.org/source", "a" * 40, b"raw", "x", "Solve x=1", "1", "CC-BY-SA-4.0", "algebra")
    other = {**base, "id": "other", "answer": "2"}
    kept, quarantine = finish([base, other], [], Counter())
    assert kept == [] and {row["id"] for row in quarantine} == {base["id"], "other"}


def test_record_serialization_preserves_all_fields():
    value = record("dmoi3", "https://example.org/source", "a" * 40, b"raw", "x", "条件 x≤2", r"\frac{1}{2}", "CC-BY-SA-4.0", "algebra")
    assert json.loads(json_bytes(value)) == value
    assert value["trust"] == "source_verified"
    assert "not_independent_math_proof" in value["metadata"]["verification"]


def test_source_broken_fraction_escape_is_quarantined():
    value = record("umath", "https://example.org/source", "a" * 40, b"raw", "x", "Find \x0crac{1}{2}", "1/2", "MIT", "algebra")
    accepted, quarantine = finish([value], [], Counter())
    assert accepted == []
    assert quarantine == [{"id": value["id"], "reason": "source_control_character_corruption"}]


def test_known_source_area_missing_sign_condition_quarantined():
    value = record("umath", "https://example.org/source", "a" * 40, b"raw", "x", "Area for x=a sin(2t), y=b sin(t)", "8ab/3", "MIT", "calculus")
    value["id"] = "umath-00d40e3ce13ab1756fe05034"
    accepted, quarantine = finish([value], [], Counter())
    assert not accepted
    assert quarantine == [{"id": value["id"], "reason": "hourglass_area_source_omits_parameter_sign_conditions"}]
