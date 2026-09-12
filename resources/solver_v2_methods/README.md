# Solver-v2 public method statements

This modified collection contains 88 complete, answer-free textbook statements:
29 from Jiří Lebl's *Notes on Diffy Qs*, fixed revision
`658bcae9fb710f3fae2c9da4ca4524ce157453af`, and 59 from Oscar Levin's
*Discrete Mathematics: An Open Introduction*, fixed third-edition revision
`1e2e26b0be8f47c9862b756ba5d7265b60c47854`.

Both sources are used under **CC BY-SA 4.0**:
https://creativecommons.org/licenses/by-sa/4.0/ . Original license notices
accompany this directory. These adaptations retain that license; the repository
code license does not replace it. Retain author attribution, source URLs,
license notices and adaptation information when redistributing the material.
No author endorsement is implied.

`evaluation/solver_v2_retrieval_audit.py` reads already acquired, hash-verified
public source snapshots. It extracts full theorem/proposition/lemma statements
and textbook method boxes, excluding exercise, example, answer, solution and
proof nodes. It removes presentation/index macros whose meaning is fixed in
the source, preserves mathematical signs and quantifiers, and rejects unresolved
cross references, missing illustrations and oversized/incomplete material.
Seven source statements with insufficient local qualifications were quarantined,
including Euler-path connectedness, division-by-zero boundaries, and the
power-series ratio/root statement's omitted center-point exception when the
radius is zero.
Graph source conventions are stated explicitly in the applicability field.

No evaluation question or label is read by the builder. These are reference
statements, not newly generated solutions or independently verified mathematics.
The solver must establish the hypotheses and applicability to each new problem.
The independent solving route receives this method material without the answer
bank's source-question solutions. Source-origin method examples embedded within
general rules are pedagogical illustrations, never asserted current answers.

Every record includes the source file URL, source revision, source SHA-256,
locator, license, complete statement and applicability caveat. `manifest.json`
records extraction exclusions, input provenance and builder hash. Runtime pins
the exact `cards.json` SHA-256 separately; resource corruption disables this
optional resource without preventing other retrieval or ordinary solving.

Reproduce into a new destination:

```
python -m evaluation.solver_v2_retrieval_audit outputs/day1-20260910/data NEW_DIR
```

The original 1,054 question/answer bank and the 160-card Hefferon resource are
unchanged. Solver-v2 additionally uses only theorem-like Hefferon cards from
that existing, separately attributed CC BY-SA 2.5 resource.
