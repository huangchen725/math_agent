# Third-party notices

This repository does not vendor the source code of its Python dependencies. The active R0 recovery tree currently uses the historical `requirements*.txt` inputs and does not include the later hash locks; `requirements.lock`, `requirements-dev.lock`, and `requirements-demo.lock` remain archived at `archive/s1-s6-1fc98b7` until the S5 supply-chain controls are deliberately restored. The table below records that archived S5 runtime closure and must not be presented as the active R0 installation proof.

| Package | Archived S5 locked version | License metadata | Project |
| --- | ---: | --- | --- |
| requests | 2.34.2 | Apache-2.0 | [psf/requests](https://github.com/psf/requests) |
| python-dotenv | 1.2.3 | BSD-3-Clause | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |
| SymPy | 1.14.0 | BSD | [sympy/sympy](https://github.com/sympy/sympy) |
| mpmath | 1.3.0 | BSD | [mpmath/mpmath](https://github.com/mpmath/mpmath) |
| certifi | 2026.7.22 | MPL-2.0 | [certifi/python-certifi](https://github.com/certifi/python-certifi) |
| charset-normalizer | 3.5.1 | MIT | [jawah/charset_normalizer](https://github.com/jawah/charset_normalizer) |
| idna | 3.19 | BSD-3-Clause | [kjd/idna](https://github.com/kjd/idna) |
| urllib3 | 2.7.0 | MIT | [urllib3/urllib3](https://github.com/urllib3/urllib3) |

The archived optional Demo lock used Gradio 6.26.0 (Apache-2.0) and Python 3.12+ for its secure Pillow closure. The archived development lock covered pytest, pytest-cov, Ruff, Bandit, pip-audit, and pip-tools, including Python 3.10 compatibility markers. Those statements describe S5 evidence, not the active recovery tree. Package metadata and upstream license files remain authoritative if a classifier in this summary differs from a distribution's bundled license text.

The repository vendors Trail of Bits' `property-based-testing` Agent Skill under `.agents/skills/property-based-testing/`, pinned to upstream commit `6feac677af72e52ef4d279412276b5a6f21366f0` from `trailofbits/skills`. Its imported upstream files remain licensed under CC BY-SA 4.0; `UPSTREAM_LICENSE.txt` preserves the license and `UPSTREAM.json` records the source path and original SHA-256 of every imported file. The project adapts `SKILL.md` by removing the unsupported `effort` frontmatter key and adding a mandatory project-policy gate; `UPSTREAM.json` records its separate current hash. `PROJECT_POLICY.md` is a separately identified project-authored overlay. The Skill is development-only, is not imported by the runtime, and remains outside the formal competition release allowlist. Updating an upstream file requires refreshing its provenance, hashes, attribution, current hashes, and applicable share-alike notice.

The committed truncation stress set is project-authored and declares `CC0-1.0` in each record. PutnamBench questions are not committed by the importer; any locally imported copy remains governed by its upstream source and recorded source commit/license metadata.

The repository's own `LICENSE` is an all-rights-reserved notice and does not relicense third-party code or data. A competition submission agreement may grant separate rights for the submitted project without changing any upstream license.
