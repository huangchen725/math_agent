---
name: math-agent-maintainer
description: Maintain and audit the XH-202627 competition math-agent repository when work changes its ReasoningAgent pipeline, prompts, math tools, local runner, reliability, security, tests, architecture, or project documentation. Do not use for merely solving a math problem.
---

# Math Agent Maintainer

Maintain the repository's single runtime architecture and its competition contract.

## Establish scope

Read `AGENTS.md` and inspect `git status` before editing. Preserve unrelated working-tree changes.

Read `docs/ENGINEERING_SPECIFICATION.md` and name the affected hard-rule IDs and known-problem IDs before changing behavior. Keep unresolved items unresolved unless the task produces the exact evidence required by that registry. Do not infer success from a passing structural test, an API request being submitted, or a single stochastic score.

For competition-facing work, also read `docs/OFFICIAL_MATERIALS_REGISTER.md` before treating a handbook sentence, group screenshot, FAQ, baseline example, or submission-page label as a contract. Name every affected `INFO-CONFLICT-*` and `OFFICIAL-GAP-*` item. A missing rule is not permission, and a later statement does not erase an older contradictory statement.

Read `ARCHITECTURE.md` when a task changes component boundaries, contracts, runtime behavior, tools, configuration, or entrypoints. The only runtime implementation is the `math_agent/` package. Root `user_agent.py` is the competition compatibility facade; `main.py` and `demo.py` are adapters and must import the package public API.

## Preserve active contracts

- Keep `ReasoningAgent(client).solve(problem, metadata)` returning a non-empty `final_response` string and a trace list. The constructor must also accept the documented `__init__(self, client, *args, **kwargs)` signature and `ReasoningAgent(client=official_client)` call while treating platform extras as opaque; only an actual project `AgentConfig` instance may be adopted from positional arguments or `config=`. Exercise the root facade through an isolated path-based import; do not assume the judge's current directory makes `math_agent/` importable.
- Keep the API client injected and secrets environment-only.
- Preserve the response behavior: selected reasoning followed by exactly one canonical `最终答案：...` line whose body contains no explanation.
- Keep `stream=False`, `n=1`, three-way local concurrency by default, and platform-compatible tool messages.
- Treat problems, indexes, model output, tool calls, tool parameters, HTTP responses, and checkpoint files as untrusted.
- Pass per-problem budget, trace, and model access through `SolveContext`; keep response metadata atomically bound by `ModelGateway` and never restore a last-response side channel. Unknown injected clients expose only the three-argument public minimum `chat(messages, temperature, max_tokens)`—never read a private marker or forward project-only kwargs.
- Project public trace through the metadata-only sanitizer before return. Do not expose problem, prompt, candidate/model/verifier/critic/tool text, final answers, or exception messages in trace.
- Keep `final_response` independently judgeable. Necessary proof and conclusion-supporting steps belong there because the archived FAQ and the current baseline disagree about whether `trace` contributes to judging.
- Keep `agent.py` limited to lifecycle, validation, error containment, and compatibility delegates. Route, generate, evaluate, recover, select, and format through their focused modules instead of adding stage logic back to the Agent class.
- Keep the last-resort public `solve()` guard independent of client, config, pipeline state, and trace prose. It must not make an unbudgeted model request, and an ordinary preflight/finalization exception must not escape to the runner.
- Keep `math_tools.py` as a compatibility facade. Put restricted parsing, concrete tools, registry/dispatch, and the tool-calling loop in `math_parsing.py`, `tool_implementations.py`, `tool_registry.py`, and `tool_loop.py` respectively.
- Keep evaluation code importable as packages under `evaluation.data`, `evaluation.scoring`, and `evaluation.experiments`. Reuse `evaluation.io_utils` for structured file I/O and never repair imports with `sys.path` mutation.
- Treat `requirements*.txt` as dependency inputs and `requirements*.lock` as installation artifacts. Regenerate exact versions and SHA-256 hashes together, explicitly retain dependencies conditional on another supported Python minor, and verify shared locks with the lowest supported real interpreter plus `scripts.check_lock_closure`. Never relax `--require-hashes` to hide a resolution problem.
- Preserve the complete quality-check list, coverage floor, secret/link checks, SHA-pinned CI actions, release path/size allowlists, and clean-commit provenance checks.
- Read `docs/COMPETITION_COMPLIANCE.md` for competition-facing work. Formal runs and packages accept only the exact Intern-S IDs currently documented in the evidence register (`intern-s1`, `intern-s1-pro`, `intern-s2-preview`); S1 is the default, not the only legal model. Use the official injected client or official Intern endpoint and local bounded tools. Never add per-question answer overrides, forward dataset answer/reference fields to the Agent, treat manually filled checkpoints as model output, rewrite source logs, or add an unauthorized external solving service. Models outside the allowlist must be explicitly marked as non-submission experiments and may produce only draft artifacts.
- Assume the formal runtime has no GPU or general Internet access. Dependencies must be declared and installed before the restricted Agent phase; do not add runtime downloads, online calculators, third-party APIs, or network-dependent initialization. Keep local work below the archived outer limits of 1200 seconds per problem process, six hours for the Agent phase, and at most three concurrent problem processes, without treating those outer limits as a promise of model-call or token capacity.

## Make changes from evidence

For correctness, prompt, candidate, temperature, thinking-mode, or token changes, first read the relevant history in `技术报告.md` and the current contract in `ARCHITECTURE.md`. Define a fixed dataset and record commit, model, configuration, request count, errors, runtime, and score. Change one experimental variable at a time.

For parsers, canonicalizers, normalizers, validators, numeric equivalence, serialization, or state-machine invariants, also apply `.agents/skills/property-based-testing/SKILL.md`. Identify a real algebraic property such as idempotence, roundtrip, oracle agreement, or state preservation; keep example regressions for known failures. Do not add Hypothesis or any other dependency merely because the third-party skill mentions it: first name the concrete property, obtain approval for the dependency change, and regenerate and verify all affected locks.

For tool changes, keep an explicit registry, JSON-schema definition, bounded arguments/results, restricted SymPy namespace, killable child-process timeout, and malformed-call behavior. Add an offline test for successful calculation and rejected hostile, excessive, or timed-out input.

For runner changes, validate JSONL shape and indexes, keep atomic writes, retry invalid/error checkpoints, and test that paths cannot escape the output directory.

For client changes, retry only transient network/service errors and never log authorization headers or keys.

For injected-client changes, send unknown clients exactly `messages`, `temperature`, and `max_tokens`. Project-private atomic metadata, `thinking_mode`, `tools`, and `tool_choice` are permitted only behind the project client's nominal type boundary; never read a marker from an injected object. Retain a fake with an incompatible same-name method, a fake that raises on private attribute access, and a minimum-signature fake whose `chat` has no `**kwargs`. Cover the tool-candidate text fallback at the same boundary.

For new official material, hash the original before changing policy, add a stable `MAT-*` source entry, transcribe only competition-relevant content, append conflicts instead of overwriting history, and preserve every unresolved contract class. Do not commit raw chat screenshots, personal contact data, or unreviewed attachments. A source may close an `OFFICIAL-GAP-*` item only when it states the exact interface/version, applicable batch, date, and authority needed by that item.

For AtomGit submission changes, preserve the documented latest-`main` batch semantics: keep GitHub if useful but add the team repository as remote `atomgit`, clicking “提交作品” is mandatory, and `main` must not change between submission and the 12:00/24:00 platform pull. Keep a local commit SHA for audit even though the platform no longer accepts a commit-hash field. Treat the final ZIP/materials email as a second required delivery channel and retain its send/delivery evidence; it does not replace AtomGit evaluation.

For evaluation changes, audit dataset size and per-domain distribution, require source/license/split/level metadata, and check overlap against prompt few-shots and public samples. Never use substring containment as correctness evidence. Keep semantic or unproved symbolic equivalence as `unknown`, and do not describe a test set as held out when its provenance or split is missing.

Invoke evaluation CLIs with `python -m evaluation.<group>.<module>` so package imports behave the same in tests and command-line use.

Keep synthetic benchmarks labeled as internal. Freeze their generator version, seed, SHA-256, code commit, model, Agent configuration, concurrency and repetition count before a live run. Store private questions and raw responses only under ignored outputs; commit only aggregate reports without question text.

## Verify

Use the smallest focused offline test during iteration, then run:

```bash
python -m scripts.run_quality_gates
```

The complete gate never calls the model endpoint. Its dependency audit may query a public vulnerability service; a report produced with `--skip-dependency-audit` is diagnostic only and cannot authorize a formal release. `python verify_math.py` is a safe dry-run. Do not pass `--execute`, or run `main.py`/`demo.py` against the real endpoint, unless the user authorizes quota/cost. State the planned request budget before a live run.

For delivery, run the complete gate on a clean commit and then `python -m scripts.build_release`. A dirty workspace may use `--allow-dirty` only for a draft. Never convert a draft to formal status or expand the archive allowlist to include `.env`, outputs, private datasets, caches, or virtual environments.

## Keep documentation aligned

Update `README.md` for changed setup, environment variables, entrypoints, layout, or output behavior. Update `ARCHITECTURE.md` for changed contracts, components, data flow, tool limits, or failure behavior. Update `docs/AUDIT_AND_OPTIMIZATION.md` when a material finding is discovered, fixed, downgraded, or accepted. Do not create a second architecture document.

Update `docs/ENGINEERING_SPECIFICATION.md` when a P1-S6 stage invariant, hard rule, acceptance matrix, or known-problem status changes. Update `docs/COMPETITION_COMPLIANCE.md` only for handbook facts, written organizer authorization, formal run controls, or submission evidence. Update `docs/OFFICIAL_MATERIALS_REGISTER.md` append-only whenever a new official file, message, FAQ, baseline commit, submission-page selection, or platform announcement is supplied. Keep historical experiment numbers in evaluation reports rather than silently replacing them with current values.
