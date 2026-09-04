# Third-party notices

This repository does not vendor the source code of its Python dependencies. Reproducible runtime, development, and optional Demo installations use the exact versions and artifact hashes recorded in `requirements.lock`, `requirements-dev.lock`, and `requirements-demo.lock`; every installed distribution remains under its own license. The table below lists the runtime dependency closure shipped for normal execution.

| Package | Locked version | License metadata | Project |
| --- | ---: | --- | --- |
| requests | 2.34.2 | Apache-2.0 | [psf/requests](https://github.com/psf/requests) |
| python-dotenv | 1.2.3 | BSD-3-Clause | [theskumar/python-dotenv](https://github.com/theskumar/python-dotenv) |
| SymPy | 1.14.0 | BSD | [sympy/sympy](https://github.com/sympy/sympy) |
| mpmath | 1.3.0 | BSD | [mpmath/mpmath](https://github.com/mpmath/mpmath) |
| certifi | 2026.7.22 | MPL-2.0 | [certifi/python-certifi](https://github.com/certifi/python-certifi) |
| charset-normalizer | 3.5.1 | MIT | [jawah/charset_normalizer](https://github.com/jawah/charset_normalizer) |
| idna | 3.19 | BSD-3-Clause | [kjd/idna](https://github.com/kjd/idna) |
| urllib3 | 2.7.0 | MIT | [urllib3/urllib3](https://github.com/urllib3/urllib3) |

The optional Demo's direct dependency is Gradio 6.26.0 (Apache-2.0). Its secure locked closure requires Python 3.12+ because the Pillow release that fixes the currently known issues no longer supports 3.10/3.11; the runtime agent does not import these UI packages. Development-only direct tools are pytest, pytest-cov, Ruff, Bandit, pip-audit, and pip-tools; `stevedore<5.9` is a Python 3.10 compatibility cap for Bandit. Exact versions and complete transitive closures are recorded in the corresponding lock files. Package metadata and upstream license files remain authoritative if a classifier in this summary differs from a distribution's bundled license text.

The committed truncation stress set is project-authored and declares `CC0-1.0` in each record. PutnamBench questions are not committed by the importer; any locally imported copy remains governed by its upstream source and recorded source commit/license metadata.

The repository's own `LICENSE` is an all-rights-reserved notice and does not relicense third-party code or data. A competition submission agreement may grant separate rights for the submitted project without changing any upstream license.
