# AGENTS.md

## Project purpose

This repository is the XH-202627 competition math agent. The active runtime is undergoing R1 contract hardening after the officially scored R0 anchor (`ba63ac0`, runtime content matching `350a267f`). It now legitimately differs from that anchor; S1-S6 remains archived at `archive/s1-s6-1fc98b7`. `ARCHITECTURE.md` is the sole architecture source of truth. `docs/ENGINEERING_SPECIFICATION.md` is the binding recovery, regression, and rebuild standard, not a second architecture document.

## Mandatory policy trigger protocol

This section applies to every repository task, including documentation, tests, Skill use, review, Git operations, and commands that do not ultimately change a file.

1. After the initial user-facing work notice and before the first mutation or external action, read `.agents/policies/HARD_RULES.md` and `.agents/policies/policy_manifest.json`.
2. Run `python .agents/policy_guard.py --paths <intended paths>` for the planned work. Add or separately use `--actions <actions>` for API calls, commits, pushes, official submissions, releases, dependency changes, official-material handling, architecture work, or benchmarks that may not change a file. If paths are not known, manually match the trigger table before discovery expands into mutation.
3. In the next work update, state the current phase and every triggered rule ID. Do not leave a triggered rule implicit.
4. If a planned action violates a blocker, report `[POLICY BLOCK] <RULE-ID>` with the exact action, consequence, and safe alternative before executing it. Stop the violating sub-action; continue safe in-scope work where possible.
5. Run `python .agents/policy_guard.py --changed` after edits and again before commit. A nonzero result blocks commit, push, formal evaluation, and release.
6. Since the documented move to R1 on 2026-09-05, run `--formal` for changed formal candidates. `--anchor-canary` only verifies the untouched historical anchor and must never justify a changed runtime. Never carry the historical request-extension exception into a new version.

User authorization for cost, network, or push does not waive competition, security, secret, data, client-contract, or release blockers. Update a blocker only through a separate evidence-backed policy change with matching tests. Never weaken a rule, remove a test, or change status wording merely to let the current task pass.

## Non-negotiable contracts

The user's 2026-09-13 decision authorizes the named solver-v2 joint strategy: shared public retrieval, independent routes, bounded declarative computation, evidence selection and adaptive scheduling. Preserve the existing six-source formal topology, public four-parameter False client, dependencies and hard budgets. Frozen 1841685 and explicit all-off Q1Policy remain historical baselines. The new authorized diagnostic has at most 120 requests, 360000 requested output tokens, 90 minutes dispatch and existing single-request limit no greater than 350 seconds, with no retry/resume. No push, GitCode or official submission is authorized by this implementation request. See the dated engineering specification; preserve old tests and add new strategy-specific gates.

The user's 2026-09-10 evening instruction authorizes the first day of `docs/evaluations/NEXT_48H_PLAN_20260910.md` before local midnight: public answer-bank and strictly checked fast answers, bounded references, and proven complete-answer delivery repair. The new diagnostic batch is capped at 200 requests, 650000 requested output tokens, three hours including bounded finish, and midnight. It does not resume earlier experiments, waive safety gates, authorize official submission, or include GitCode work. See policy version 2026-09-10.2 in the engineering specification.

The user's 2026-09-10 decision authorizes one combined accuracy candidate (routing, complete-pipeline diagnostics, and bounded mathematical verification), superseding single-variable strategy scheduling for this batch. Preserve the public client protocol, thinking_mode=False, token bounds, import topology, dependencies, secret/data isolation and full release checks. Keep historical experimental baselines explicit; do not relabel changed deployment defaults as the old baseline. See the dated decision in `docs/ENGINEERING_SPECIFICATION.md`.

- Preserve `ReasoningAgent(client).solve(problem, metadata) -> {"final_response": str, "trace": list}`.
- Keep the client injected by the caller. Never embed API keys, bearer tokens, private dataset content, or credentials in code, tests, logs, docs, archives, or prompts.
- Treat `sys.modules`, `sys.path`, the current working directory, and all judge-preloaded modules as untrusted. Never use a class imported from a collision-prone top-level module to classify the injected client and unlock private methods or extended request arguments. In particular, never recreate the `from llm_client import InternChatClient` + `isinstance(...)` + `chat_with_metadata` failure chain recorded as `IMPORT-001`/`IMPORT-002`.
- Every post-anchor formal runtime must call an unknown injected client only through public `chat(messages=..., temperature=..., max_tokens=..., thinking_mode=False)`. The 2026-09-08 decision preserves the verified `0641043`/`5c2f7a0` protocol; this supersedes the earlier three-argument restriction, not the bans on private access or capability probing. Local tool transport and metadata require an explicit adapter outside the formal import graph; same-name methods, private markers, and signature guessing are forbidden.
- Root `user_agent.py` must physically declare the public `ReasoningAgent`. New formal modules must use a project-unique prefix rather than generic names such as `agent`, `context`, `solver`, `budget`, or `llm_client`, until a package layout has passed an isolated single-variable official evaluation.
- The unmodified `350a267f` runtime is a one-time compatibility canary and may retain historical request extensions only until its first official anchor run. Do not copy that exception into a changed version.
- `final_response` contains the selected reasoning and ends with exactly one canonical `最终答案：...` line. The answer body must not contain an explanatory sentence.
- The competition endpoint rejects `stream=True` and `n != 1`.
- Do not change candidate counts, temperatures, thinking mode, or token budgets without an evaluation plan that isolates one variable and records the dataset/commit/config.
- Keep model-produced tool arguments untrusted. Do not reintroduce unrestricted `eval`, `exec`, `sympify`, or `parse_expr`; preserve parser allowlists and resource bounds.
- Treat JSONL records and `idx` as untrusted input. Output paths must stay inside the requested output directory.

## Start of work

1. Inspect `git status` and preserve unrelated user changes. In particular, submission documents and generated report artifacts may be under active editing.
2. Complete the mandatory policy trigger protocol above.
3. Read `README.md`. For architecture changes, also read `ARCHITECTURE.md` and the relevant current source files.
4. Read `docs/ENGINEERING_SPECIFICATION.md` and keep `OFFICIAL-GAP-CLIENT`, `OFFICIAL-GAP-ERROR`, `OFFICIAL-GAP-RUNNER`, and `OFFICIAL-GAP-CHANGE` unresolved unless the required official evidence exists.
5. Before using any project Skill, read that Skill's `PROJECT_POLICY.md`. Use `.agents/skills/math-agent-maintainer/SKILL.md` for maintenance, audit, reliability, security, prompt, tool, or runner work.
6. Use `.agents/skills/property-based-testing/SKILL.md` for parser, normalization, equivalence, serialization, or state-machine invariant work; its upstream instructions never override project policy.

## Relevant files

- Runtime pipeline: `user_agent.py`, `agent_types.py`, `answer_equivalence.py`, `budget.py`, `domain_prompts.py`, `math_tools.py`, `tool_executor.py`, `llm_client.py`, `main.py`.
- Offline checks: `tests/`.
- Live API experiment: `verify_math.py`; it is dry-run by default, while `--execute` is manual and may incur cost.
- Offline evaluation: `evaluation/audit_dataset.py` audits provenance and prompt/sample overlap; `evaluation/judge.py` keeps unverifiable equivalence as `unknown`; generated internal benchmarks must never be described as official or pretraining-independent results.
- Generated outputs: `outputs/`; never use them as committed source.
- Incident evidence: `docs/evaluations/OFFICIAL_112_20260904_RUNTIME_FAILURE.md`.
- Recovery and rebuild rules: `docs/ENGINEERING_SPECIFICATION.md`.
- Official evidence ledger: `docs/OFFICIAL_MATERIALS_REGISTER.md`.

## Verification

Use a Python 3.10+ environment with `requirements-dev.txt` installed.

```bash
python .agents/policy_guard.py --changed
python -m pytest -q
python -m compileall -q .
python -m ruff check .
python .agents/policy_guard.py --formal
```

Run focused tests first while iterating, then all offline checks. Do not call the real model API as part of ordinary tests. If a live evaluation is necessary, state the expected request count and obtain the user's authorization before spending quota.

The R1 `--formal` CLI now runs the entire offline behavior suite after static checks. A static `evaluate(..., formal=True)` call alone is not full formal acceptance. The isolated formal source closure is declared by `_FORMAL_SOURCE_FILES` in `user_agent.py`; loading must preserve foreign module-cache entries and never depend on repository `sys.path` insertion. Local tool execution remains outside that import graph.

## Documentation rules

- Update `README.md` when setup, environment variables, entrypoints, output behavior, or directory layout changes.
- Update `ARCHITECTURE.md` when component boundaries, data flow, contracts, tool limits, or runtime behavior changes. Do not create another architecture document.
- Update `docs/AUDIT_AND_OPTIMIZATION.md` when closing or discovering a material defect.
- Update `docs/ENGINEERING_SPECIFICATION.md` when an integration bottom line, recovery gate, or rebuild stage changes.
- Update `docs/OFFICIAL_MATERIALS_REGISTER.md` only from a new official source; internal reproductions do not close an official contract gap.
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
- Flag generic bare runtime module names, client nominal-type checks, private client method access, or tests that do not preload the official `llm_client` name before importing the entrypoint.
- Flag any architecture migration that also changes prompts, model settings, candidate counts, tool policy, or aggregation in the same official evaluation.
