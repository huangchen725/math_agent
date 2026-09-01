---
name: math-agent-maintainer
description: Maintain and audit the XH-202627 competition math-agent repository when work changes its ReasoningAgent pipeline, prompts, math tools, local runner, reliability, security, tests, architecture, or project documentation. Do not use for merely solving a math problem.
---

# Math Agent Maintainer

Maintain the repository's single runtime architecture and its competition contract.

## Establish scope

Read `AGENTS.md` and inspect `git status` before editing. Preserve unrelated working-tree changes.

Read `docs/ENGINEERING_SPECIFICATION.md` and name the affected hard-rule IDs and known-problem IDs before changing behavior. Keep unresolved items unresolved unless the task produces the exact evidence required by that registry. Do not infer success from a passing structural test, an API request being submitted, or a single stochastic score.

Read `ARCHITECTURE.md` when a task changes component boundaries, contracts, runtime behavior, tools, configuration, or entrypoints. The only runtime implementation is the `math_agent/` package. Root `user_agent.py` is the competition compatibility facade; `main.py` and `demo.py` are adapters and must import the package public API.

## Preserve active contracts

- Keep `ReasoningAgent(client).solve(problem, metadata)` returning a non-empty `final_response` string and a trace list.
- Keep the API client injected and secrets environment-only.
- Preserve the response behavior: selected reasoning followed by exactly one canonical `最终答案：...` line whose body contains no explanation.
- Keep `stream=False`, `n=1`, three-way local concurrency by default, and platform-compatible tool messages.
- Treat problems, indexes, model output, tool calls, tool parameters, HTTP responses, and checkpoint files as untrusted.
- Pass per-problem budget, trace, and model access through `SolveContext`; keep response metadata atomically bound by `ModelGateway` and never restore a last-response side channel.
- Keep `agent.py` limited to lifecycle, validation, error containment, and compatibility delegates. Route, generate, evaluate, recover, select, and format through their focused modules instead of adding stage logic back to the Agent class.
- Keep `math_tools.py` as a compatibility facade. Put restricted parsing, concrete tools, registry/dispatch, and the tool-calling loop in `math_parsing.py`, `tool_implementations.py`, `tool_registry.py`, and `tool_loop.py` respectively.
- Keep evaluation code importable as packages under `evaluation.data`, `evaluation.scoring`, and `evaluation.experiments`. Reuse `evaluation.io_utils` for structured file I/O and never repair imports with `sys.path` mutation.
- Treat `requirements*.txt` as dependency inputs and `requirements*.lock` as installation artifacts. Regenerate exact versions and SHA-256 hashes together, explicitly retain dependencies conditional on another supported Python minor, and verify shared locks with the lowest supported real interpreter plus `scripts.check_lock_closure`. Never relax `--require-hashes` to hide a resolution problem.
- Preserve the complete quality-check list, coverage floor, secret/link checks, SHA-pinned CI actions, release path/size allowlists, and clean-commit provenance checks.
- Read `docs/COMPETITION_COMPLIANCE.md` for competition-facing work. Formal runs and packages use `intern-s1`, the official injected client or official Intern endpoint, and local bounded tools. Never add per-question answer overrides, forward dataset answer/reference fields to the Agent, treat manually filled checkpoints as model output, rewrite source logs, or add an unauthorized external solving service. Non-S1 work must be explicitly marked as a non-submission experiment and may produce only draft artifacts.

## Make changes from evidence

For correctness, prompt, candidate, temperature, thinking-mode, or token changes, first read the relevant history in `技术报告.md` and the current contract in `ARCHITECTURE.md`. Define a fixed dataset and record commit, model, configuration, request count, errors, runtime, and score. Change one experimental variable at a time.

For tool changes, keep an explicit registry, JSON-schema definition, bounded arguments/results, restricted SymPy namespace, killable child-process timeout, and malformed-call behavior. Add an offline test for successful calculation and rejected hostile, excessive, or timed-out input.

For runner changes, validate JSONL shape and indexes, keep atomic writes, retry invalid/error checkpoints, and test that paths cannot escape the output directory.

For client changes, retry only transient network/service errors and never log authorization headers or keys.

For injected-client changes, use only the public `chat()` contract. Project-private atomic metadata is permitted only after the project-owned client explicitly advertises the exact protocol marker; always retain a fake client with a deliberately incompatible same-name private method so structural probing cannot return.

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

Update `docs/ENGINEERING_SPECIFICATION.md` when a P1-S6 stage invariant, hard rule, acceptance matrix, or known-problem status changes. Update `docs/COMPETITION_COMPLIANCE.md` only for handbook facts, written organizer authorization, formal run controls, or submission evidence. Keep historical experiment numbers in evaluation reports rather than silently replacing them with current values.
