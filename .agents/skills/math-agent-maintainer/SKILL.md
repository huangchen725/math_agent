---
name: math-agent-maintainer
description: Maintain and audit the XH-202627 competition math-agent repository when work changes its ReasoningAgent pipeline, prompts, math tools, local runner, reliability, security, tests, architecture, or project documentation. Do not use for merely solving a math problem.
---

# Math Agent Maintainer

Maintain the single active runtime while the repository is recovering from repeated official request-before-send failures.

## Establish scope

Read `AGENTS.md`, `.agents/policies/HARD_RULES.md`, this Skill's `PROJECT_POLICY.md`, and inspect `git status` before planning edits. Run `python .agents/policy_guard.py --paths <intended paths>` and add `--actions <actions>` for policy-sensitive commands or external effects; report the triggered rule IDs plus recovery phase in the first work update. Preserve unrelated changes. Read `docs/ENGINEERING_SPECIFICATION.md` before changing code. For runtime or component changes, read `ARCHITECTURE.md`; for competition-facing work, also read `docs/COMPETITION_COMPLIANCE.md` and `docs/OFFICIAL_MATERIALS_REGISTER.md`.

When the guard or manual review finds a blocker, emit `[POLICY BLOCK] <RULE-ID>` with the exact proposed action, consequence, and safe alternative before any mutation. Stop only the violating sub-action and continue safe in-scope work. Never execute first and explain afterward.

The active runtime is the recovery snapshot matching the last officially scored commit `350a267f`. The S1-S6 implementation is preserved at `archive/s1-s6-1fc98b7` for selective reintroduction. Do not describe archived modules as current architecture.

## Preserve the recovery anchor

- Keep `ReasoningAgent(client).solve(problem, metadata)` returning a non-empty `final_response` string and a trace list.
- Until the first official anchor evaluation completes, do not change runtime files, prompts, candidates, temperatures, token budgets, tools, aggregation, or client calls. Documentation and offline tests may change without claiming that the historical runtime is already hardened.
- Treat the exact `350a267f` runtime as a one-time compatibility canary, not a final design. Its historical extensions, trace behavior, and truncation behavior must not be copied into a post-anchor version.
- Do not call a real API unless the user authorizes the expected request count and cost.

## Enforce the incident bottom line

`IMPORT-001`, `IMPORT-002`, `CLIENT-001`, and `TEST-IMPORT-001` in the engineering specification are absolute release blockers.

- Treat `sys.modules`, `sys.path`, the judge working directory, and preloaded modules as hostile integration state.
- Never infer that `from llm_client import InternChatClient` resolves to a project-owned class. Never use such a class in `isinstance`/`issubclass` to unlock `chat_with_metadata`, tools, extra kwargs, metadata, or any privileged path.
- A post-anchor formal entrypoint must treat every injected client as external and call only `chat(messages=..., temperature=..., max_tokens=...)`.
- Put project-private client features behind an explicit local adapter outside the formal import graph. Do not probe markers, fields, same-name methods, signatures, or attributes.
- Keep a real `ReasoningAgent` declaration in root `user_agent.py`. Use project-prefixed formal module names; do not add generic top-level names such as `agent`, `context`, `solver`, `budget`, or `llm_client`.
- Before editing an injected-client boundary, first reproduce the official load order: preload a foreign `llm_client`, then import `user_agent`. Also test a strict three-parameter fake without `**kwargs`, a private-attribute trap, isolated path loading, and the complete `sys.modules` pollution matrix.
- A local A/B may prove a deterministic code defect. It cannot close `OFFICIAL-GAP-CLIENT`, `OFFICIAL-GAP-ERROR`, `OFFICIAL-GAP-RUNNER`, or `OFFICIAL-GAP-CHANGE` without the required official evidence.

## Reintroduce changes in order

Follow the recovery stages in `docs/ENGINEERING_SPECIFICATION.md`:

1. R0 official compatibility anchor.
2. R1 minimum public contract hardening, one variable per official run.
3. Q0 frozen university-competition ability baseline.
4. Q1 truncation, deterministic evidence, routing, verifier calibration, then advanced strategies.
5. A1 maintainable architecture, importing low-risk quality assets before runtime topology.
6. Q2 paired and repeated evidence of ability improvement.

For architecture work, preserve one implementation and explicit state. Prefer uniquely prefixed root modules until package loading receives a dedicated official success result. A physical package is not forbidden, but package topology must be the only changed variable in its evaluation.

For parser, canonicalizer, normalizer, validator, numeric-equivalence, serialization, or recovery-state work, also apply `.agents/skills/property-based-testing/SKILL.md`. Name a concrete property and keep a fixed example for every historical failure.

## Verification

Run focused tests first, then the recovery baseline checks:

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
python verify_math.py
```

Before those checks and before every commit, run:

```bash
python .agents/policy_guard.py --changed
```

Before a submission, run `--anchor-canary` for the unmodified R0 anchor or `--formal` for a later changed runtime. A nonzero guard exit blocks the submission and must be reported with its rule ID.

These checks do not establish official compatibility or mathematical improvement. After S5 quality tooling is selectively restored, use its complete gate only after adapting it to the active runtime; do not copy archived green reports or weaken checks.

## Documentation

- `ARCHITECTURE.md` is the only current architecture source.
- `docs/ENGINEERING_SPECIFICATION.md` defines hard rules and the rebuild sequence.
- `docs/AUDIT_AND_OPTIMIZATION.md` records incidents and decisions.
- `docs/OFFICIAL_MATERIALS_REGISTER.md` is append-only for official evidence and unresolved contract gaps.
- `docs/evaluations/` stores immutable experiment and official-log summaries.

Update claims with their commit, model, configuration, dataset hash, request/error counts, and evidence limits. Never turn a request recovery, offline test, synthetic benchmark, or engineering improvement into an unsupported accuracy claim.
