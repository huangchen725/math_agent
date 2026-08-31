# AGENTS.md

## Project purpose

This repository is the XH-202627 competition math agent. `math_agent/` is the only runtime implementation; root `user_agent.py` is the official compatibility facade. `ARCHITECTURE.md` is the sole architecture source of truth.

## Non-negotiable contracts

- Preserve `ReasoningAgent(client).solve(problem, metadata) -> {"final_response": str, "trace": list}`.
- Keep the client injected by the caller. Never embed API keys, bearer tokens, private dataset content, or credentials in code, tests, logs, docs, archives, or prompts.
- `final_response` contains the selected reasoning and ends with exactly one canonical `最终答案：...` line. The answer body must not contain an explanatory sentence.
- The competition endpoint rejects `stream=True` and `n != 1`.
- Do not change candidate counts, temperatures, thinking mode, or token budgets without an evaluation plan that isolates one variable and records the dataset/commit/config.
- Keep model-produced tool arguments untrusted. Do not reintroduce unrestricted `eval`, `exec`, `sympify`, or `parse_expr`; preserve parser allowlists and resource bounds.
- Treat JSONL records and `idx` as untrusted input. Output paths must stay inside the requested output directory.
- Keep per-problem state in `SolveContext`. Model response text and metadata must return atomically through `ModelGateway`; do not reintroduce process/thread/context-local "last response" side channels.
- Keep `math_agent/agent.py` as the lifecycle and compatibility boundary. Put stage behavior in `solver.py` and the focused candidate/response modules; do not rebuild a monolithic Agent class.
- Keep `math_agent/math_tools.py` as an import-compatibility facade. Restricted parsing belongs in `math_parsing.py`, implementations in `tool_implementations.py`, schemas/dispatch in `tool_registry.py`, and the model loop in `tool_loop.py`.
- Keep offline evaluation grouped under `evaluation/data`, `evaluation/scoring`, and `evaluation/experiments`. Use `evaluation/io_utils.py` for JSON/JSONL, hashing, and atomic writes; do not add `sys.path` mutation to evaluation modules.
- Keep dependency inputs and locks paired: edit `requirements*.txt`, regenerate the affected `requirements*.lock` with exact versions and SHA-256 hashes, then validate installation with `--require-hashes`.
- Do not remove required checks from `scripts/run_quality_gates.py`, weaken the coverage floor, broaden release file allowlists, or bypass the clean-commit/quality-report rules merely to make CI or packaging pass.
- Formal release archives must come from Git blobs of a clean commit. Dirty workspaces may produce only explicitly marked draft archives.

## Start of work

1. Inspect `git status` and preserve unrelated user changes. In particular, submission documents and generated report artifacts may be under active editing.
2. Read `README.md`. For architecture changes, also read `ARCHITECTURE.md` and the relevant current source files.
3. Use the repository skill at `.agents/skills/math-agent-maintainer/SKILL.md` for maintenance, audit, reliability, security, prompt, tool, or runner work.

## Relevant files

- Runtime pipeline: compatibility facade `user_agent.py`, lifecycle `math_agent/agent.py`, orchestration `math_agent/solver.py`, focused candidate/response modules, and adapters `main.py`/`demo.py`.
- Offline checks: `tests/`.
- Quality and delivery: `scripts/run_quality_gates.py`, `scripts/check_secrets.py`, `scripts/check_markdown_links.py`, `scripts/build_release.py`, dependency locks, and `.github/workflows/offline-quality.yml`.
- Live API experiment: `verify_math.py`; it is dry-run by default, while `--execute` is manual and may incur cost.
- Offline evaluation: `python -m evaluation.data.audit_dataset` audits provenance and prompt/sample overlap; `evaluation.scoring.judge` keeps unverifiable equivalence as `unknown`; generated internal benchmarks must never be described as official or pretraining-independent results.
- Generated outputs: `outputs/`; never use them as committed source.

## Verification

Use a Python 3.10+ environment with the hash-locked development dependencies installed.

```bash
python -m pip install --require-hashes -r requirements-dev.lock
python -m scripts.run_quality_gates
```

Run focused tests first while iterating, then the complete gate. `pip-audit` may query the public vulnerability service; `--skip-dependency-audit` is suitable for a disconnected diagnostic but its report cannot authorize a formal release. Do not call the real model API as part of ordinary tests. If a live evaluation is necessary, state the expected request count and obtain the user's authorization before spending quota.

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
- Flag lock entries without exact versions or hashes, GitHub Actions not pinned to full commit SHAs, and formal packages whose quality evidence refers to another commit/tree.
- Flag tests that require a real API key or depend on stochastic model output.
- Flag benchmark records without source, license, split, and calibrated level metadata; flag any test/dev item that overlaps prompt few-shots or public samples.
- Flag judges that accept substring matches, unrestricted symbolic parsing, or semantic guesses as correct.
