# Hefferon public reference corpus v1

160 theory and worked-example excerpts from *Linear Algebra*, Jim Hefferon.
Source: https://gitlab.com/jim.hefferon/linear-algebra
Immutable revision: `df2262e089a02651c127f1dd12649c4622ee1383`.

The LICENSE at that revision offers CC BY-SA 2.5 or GFDL. This derived corpus uses
CC BY-SA 2.5: https://creativecommons.org/licenses/by-sa/2.5/ . The original
notice is reproduced in `LICENSE.source.txt`. Attribution must accompany reuse;
adaptations are distributed under the same license. This license applies to the
textbook-derived corpus, not automatically to unrelated repository software.
The author's current web page also offers another license version; the immutable
source notice is the basis used here.

The reproduced notice uses LF line endings and removes trailing whitespace;
its wording is unchanged. The original bytes remain in the source snapshot.

Changes: select complete bounded definitions, theorems and worked examples;
remove TeX comments, indexes and labels; expand a small explicit set of display
macros; retain source path, source hash, revision and original line number.
No evaluation reference labels or U-MATH records are included.

Quality quarantine: source label `co:VectorsOrthogonalIffDoTProductZero`
(`src/gr/gr2.tex`, line 1035) was excluded after finding that its unqualified
parallel-vector statement omits an absolute value or same-direction condition.
The counterexample (1,0), (-1,0) has dot product -1 and length product 1.
The entire block is omitted; the deterministic source selection supplies the
next eligible block to retain 160 cards. This is a source-quality correction,
not retrieval-query tuning. Other excerpts are not certified theorem proofs.

`question` stores the entire reference block for conservative offline identity
diagnostics; it is not a separate hidden-test question or an answer lookup key.
Exact self-retrieval does not establish useful question coverage. Runtime only
supplies bounded reference context to one generation; it never returns a stored
answer directly. Raw source snapshots and build provenance are held in local
`outputs/first-batch-20260908/hefferon-source/`; `evaluation.xh_corpus` rebuilds
the cards deterministically from that pinned source.

Remaining TeX notation includes `\spanof{S}` (span of S), `\sequence{...}`
(ordered tuple), `\polyspace_n` (polynomials of degree at most n), and ordinary
matrix/vector environments. No LaTeX or source code is executed by retrieval.
