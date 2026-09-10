# Public question/answer bank — day 1, 2026-09-10

This is an attributed, modified collection of **1,054 complete public question/answer pairs**:

| Source | Fixed revision | Pairs | Data license |
| --- | --- | ---: | --- |
| U-MATH, Konstantin Chernyshev et al.; Toloka AI and Gradarius | `7210f97b3f21122c3a90126935e966ca7d8951b6` | 606 | MIT |
| Notes on Diffy Qs, Jiří Lebl | `658bcae9fb710f3fae2c9da4ca4524ce157453af` | 222 | CC BY-SA 4.0, selected from the source dual license |
| Discrete Mathematics: An Open Introduction, Oscar Levin, third-edition branch | `1e2e26b0be8f47c9862b756ba5d7265b60c47854` | 226 | CC BY-SA 4.0 |

The MIT copyright/license and dataset licensing statement, plus the textbook source license notices, are reproduced in `licenses/`. Textbook-derived records retain CC BY-SA 4.0: <https://creativecommons.org/licenses/by-sa/4.0/>. They are not relicensed as the repository code license. Retain authors, source URLs, license links and adaptation notices when sharing these records or adaptations. No endorsement by the original authors is implied.

U-MATH data copyright: (c) 2024 Toloka.ai. Its dataset card explicitly makes all dataset contents available under MIT; the accompanying official project MIT notice is also included. DMOI source frontmatter attributes copyright 2013–2019 to Oscar Levin. Notes on Diffy Qs is attributed to Jiří Lebl under its fixed source license.

## Adaptations

This collection pairs existing public questions with their existing public answers. It does not generate new solutions. For the textbooks it removes formatting comments/labels/page layout and translates a bounded list of explicitly defined presentation macros to standard LaTeX. Numbered subquestions, numerical values, mathematical signs and source answers are retained. XML math, list numbering and ellipses are retained. Missing diagrams, unresolved cross-references, unsupported macros, empty answers and known source defects are excluded rather than guessed.

`trust=source_verified` means provenance and full source question/answer pairing have been checked by the adapter; it does **not** mean independent mathematical proof. Inference must still perform substantive model checking and retain existing mathematical vetoes. This bank is not an answer authority.

## Isolation and reproduction

The original Q0 144 question-only inputs and numeric-masked near duplicates are excluded. This removed 290 U-MATH source rows before their answer fields were accessed; three other U-MATH rows with corrupted control-character math escapes were quarantined. An independent review of the fixed public hit probes found one hourglass-area source answer that omits the sign conditions on its parameters; that entire record was quarantined without substituting another probe. No private, official hidden or Q0 label was used to pick source answers. The original U-MATH `test` designation is a public upstream release label; these selected records are now explicitly `public_retrieval` material and may not count as unseen evaluation evidence.

`SOURCE_PROVENANCE.json` records fixed source revisions, URLs and raw hashes; `source_audit.json` records exclusion counts and question-input hashes. Individual records additionally bind their original source and source key.

The reproducible adapters are `evaluation/xh_answer_sources.py`, followed by `evaluation/xh_answer_bank.py`. The day-1 clean input SHA-256 is `d8a1e550f0bc7fa774fae3b33620612dcc731dd33b44f31f62fffe0879a27c40`; the root manifest SHA-256 is `4ed168f2a36c48d314ddc33c37b64aa7c71eafc5a1489598553154d8adaa93b1`. The runtime pins this root separately and verifies the selected indexes and record payloads. The license/provenance documents are accompanying attribution evidence, not runtime prompt material.

No independent mathematical accuracy or official score improvement is established by this collection or by successful local index roundtrips.
