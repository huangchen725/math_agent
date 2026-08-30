# AGENTS.md

## Project purpose

This repository is the XH-202627 competition math agent. `user_agent.py::ReasoningAgent` and its flat-module dependencies are the only runtime architecture. `ARCHITECTURE.md` is the sole architecture source of truth.

## Non-negotiable contracts

- Preserve `ReasoningAgent(client).solve(problem, metadata) -> {"final_response": str, "trace": list}`.
- Keep the client injected by the caller. Never embed API keys, bearer tokens, private dataset content, or credentials in code, tests, logs, docs, archives, or prompts.
- `final_response` contains the selected reasoning and ends with exactly one canonical `最终答案：...` line. The answer body must not contain an explanatory sentence.
- The competition endpoint rejects `stream=True` and `n != 1`.
- Do not change candidate counts, temperatures, thinking mode, or token budgets without an evaluation plan that isolates one variable and records the dataset/commit/config.
- Keep model-produced tool arguments untrusted. Do not reintroduce unrestricted `eval`, `exec`, `sympify`, or `parse_expr`; preserve parser allowlists and resource bounds.
- Treat JSONL records and `idx` as untrusted input. Output paths must stay inside the requested output directory.

## Start of work

1. Inspect `git status` and preserve unrelated user changes. In particular, submission documents and generated report artifacts may be under active editing.
2. Read `README.md`. For architecture changes, also read `ARCHITECTURE.md` and the relevant current source files.
3. Use the repository skill at `.agents/skills/math-agent-maintainer/SKILL.md` for maintenance, audit, reliability, security, prompt, tool, or runner work.

## Relevant files

- Runtime pipeline: `user_agent.py`, `agent_types.py`, `answer_equivalence.py`, `task_router.py`, `deterministic_verifier.py`, `budget.py`, `domain_prompts.py`, `math_tools.py`, `tool_executor.py`, `llm_client.py`, `main.py`.
- Offline checks: `tests/`.
- Live API experiment: `verify_math.py`; it is dry-run by default, while `--execute` is manual and may incur cost.
- Offline evaluation: `evaluation/audit_dataset.py` audits provenance and prompt/sample overlap; `evaluation/judge.py` keeps unverifiable equivalence as `unknown`; generated internal benchmarks must never be described as official or pretraining-independent results.
- Generated outputs: `outputs/`; never use them as committed source.

## Verification

Use a Python 3.10+ environment with `requirements-dev.txt` installed.

```bash
python -m pytest -q
python -m compileall -q .
python -m ruff check .
```

Run focused tests first while iterating, then all offline checks. Do not call the real model API as part of ordinary tests. If a live evaluation is necessary, state the expected request count and obtain the user's authorization before spending quota.

## Documentation rules

- Update `README.md` when setup, environment variables, entrypoints, output behavior, or directory layout changes.
- Update `ARCHITECTURE.md` when component boundaries, data flow, contracts, tool limits, or runtime behavior changes. Do not create another architecture document.
- Update `docs/AUDIT_AND_OPTIMIZATION.md` when closing or discovering a material defect.
- Keep claims about accuracy, score, latency, cost, and platform limits tied to a recorded experiment or existing project evidence.
- Use `AGENTS.md` for durable repository rules and the project skill for task-specific maintenance workflow. Avoid duplicating long architecture material in either file.

## Code review rules

- Flag any path built directly from dataset fields without validation.
- Flag retry loops that retry authentication, validation, or other permanent failures.
- Flag model/tool outputs copied into logs or prompts without size limits.
- Flag a checkpoint as complete only when it is valid JSON with `status == "success"` and a non-empty `final_response`.
- Flag additions to runtime dependencies that are not imported directly or justified by an entrypoint.
- Flag tests that require a real API key or depend on stochastic model output.
- Flag benchmark records without source, license, split, and calibrated level metadata; flag any test/dev item that overlaps prompt few-shots or public samples.
- Flag judges that accept substring matches, unrestricted symbolic parsing, or semantic guesses as correct.
