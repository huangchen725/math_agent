---
name: math-agent-maintainer
description: Maintain and audit the XH-202627 competition math-agent repository when work changes its ReasoningAgent pipeline, prompts, math tools, local runner, reliability, security, tests, architecture, or project documentation. Do not use for merely solving a math problem.
---

# Math Agent Maintainer

Maintain the repository's single runtime architecture and its competition contract.

## Establish scope

Read `AGENTS.md` and inspect `git status` before editing. Preserve unrelated working-tree changes.

Read `ARCHITECTURE.md` when a task changes component boundaries, contracts, runtime behavior, tools, configuration, or entrypoints. The runtime path is `user_agent.py`, `agent_types.py`, `answer_equivalence.py`, `budget.py`, `domain_prompts.py`, `math_tools.py`, `tool_executor.py`, `llm_client.py`, `main.py`, and `demo.py`.

## Preserve active contracts

- Keep `ReasoningAgent(client).solve(problem, metadata)` returning a non-empty `final_response` string and a trace list.
- Keep the API client injected and secrets environment-only.
- Preserve the response behavior: selected reasoning followed by exactly one canonical `最终答案：...` line whose body contains no explanation.
- Keep `stream=False`, `n=1`, three-way local concurrency by default, and platform-compatible tool messages.
- Treat problems, indexes, model output, tool calls, tool parameters, HTTP responses, and checkpoint files as untrusted.

## Make changes from evidence

For correctness, prompt, candidate, temperature, thinking-mode, or token changes, first read the relevant history in `技术报告.md` and the current contract in `ARCHITECTURE.md`. Define a fixed dataset and record commit, model, configuration, request count, errors, runtime, and score. Change one experimental variable at a time.

For tool changes, keep an explicit registry, JSON-schema definition, bounded arguments/results, restricted SymPy namespace, killable child-process timeout, and malformed-call behavior. Add an offline test for successful calculation and rejected hostile, excessive, or timed-out input.

For runner changes, validate JSONL shape and indexes, keep atomic writes, retry invalid/error checkpoints, and test that paths cannot escape the output directory.

For client changes, retry only transient network/service errors and never log authorization headers or keys.

For evaluation changes, audit dataset size and per-domain distribution, require source/license/split/level metadata, and check overlap against prompt few-shots and public samples. Never use substring containment as correctness evidence. Keep semantic or unproved symbolic equivalence as `unknown`, and do not describe a test set as held out when its provenance or split is missing.

## Verify

Use the smallest focused offline test during iteration, then run:

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

`python verify_math.py` is a safe dry-run. Do not pass `--execute`, or run `main.py`/`demo.py` against the real endpoint, unless the user authorizes quota/cost. State the planned request budget before a live run.

## Keep documentation aligned

Update `README.md` for changed setup, environment variables, entrypoints, layout, or output behavior. Update `ARCHITECTURE.md` for changed contracts, components, data flow, tool limits, or failure behavior. Update `docs/AUDIT_AND_OPTIMIZATION.md` when a material finding is discovered, fixed, downgraded, or accepted. Do not create a second architecture document.
