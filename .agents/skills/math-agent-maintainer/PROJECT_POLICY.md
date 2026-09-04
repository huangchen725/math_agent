# Project policy overlay

This project-level overlay is mandatory whenever `math-agent-maintainer` is used.

1. Read `../../policies/HARD_RULES.md` and `../../policies/policy_manifest.json` before planning edits.
2. Run `python .agents/policy_guard.py --paths <intended paths>` before mutation; add `--actions <actions>` for API, Git, release, dependency, official-material, benchmark, or architecture actions.
3. State the triggered rule IDs and current recovery phase in the first work update.
4. If the guard reports `[POLICY BLOCK]`, report the exact rule, stop the violating sub-action, and use a safe alternative or wait for the required evidence/authorization.
5. Run `python .agents/policy_guard.py --changed` before tests and commit.
6. Use `--anchor-canary` for the frozen `350a267f` runtime and `--formal` only after the policy phase has formally moved beyond R0.

This overlay cannot authorize real API use, push, submission, publication, disclosure, or a waiver of competition/security rules.
