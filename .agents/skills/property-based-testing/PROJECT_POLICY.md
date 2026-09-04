# XH-202627 project policy overlay

This local overlay controls use of the project-adapted property-based-testing Skill. `UPSTREAM.json` preserves both the upstream hash and the current adapted hash.

Before applying the Skill:

1. Read `../../policies/HARD_RULES.md` and `../../policies/policy_manifest.json`.
2. Run `python .agents/policy_guard.py --paths <intended paths>` and add `--actions benchmark` when applicable; report every triggered rule ID.
3. Do not edit the frozen R0 runtime, add Hypothesis, change dependencies, or broaden a parser merely because property testing would benefit from it. These remain separate project decisions.
4. Use the strongest meaningful property, retain a fixed regression for the historical failure, and keep unproved equivalence as `unknown`.
5. If generation could reach unrestricted parsing, excessive symbolic work, private data, reference answers, or external services, report `[POLICY BLOCK]` with `SECURITY-001`, `DATA-001`, or the applicable rule before generating or running cases.
6. Run `python .agents/policy_guard.py --changed` after edits.

This file is a local policy overlay and is listed separately from the imported upstream file hashes in `UPSTREAM.json`.
