"""Competition policy constants and fail-closed runtime validation.

The formal profile follows the supplied XH-202627 handbook. Non-S1 models
remain available only when an operator explicitly marks a run as a local,
non-submission experiment.
"""

from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit


COMPETITION_MANUAL_SHA256 = (
    "ece081cd4a0c4f496943b3e3c7d79716d8ffd1d9a6249e11bb3ed5c4a39902d7"
)
FORMAL_COMPETITION_MODEL = "intern-s1"
OFFICIAL_API_BASE = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
COMPETITION_MODE_ENV = "COMPETITION_MODE"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def competition_mode_enabled(environment: Mapping[str, str] | None = None) -> bool:
    """Return whether fail-closed competition restrictions are active."""
    source = os.environ if environment is None else environment
    raw = str(source.get(COMPETITION_MODE_ENV, "1")).strip().lower()
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    raise ValueError(
        f"{COMPETITION_MODE_ENV} must be one of "
        "1/0, true/false, yes/no, or on/off"
    )


def validate_official_api_base(value: str) -> str:
    """Accept only the documented HTTPS Intern API completion endpoint."""
    candidate = str(value or "").strip().rstrip("/")
    parsed = urlsplit(candidate)
    expected = urlsplit(OFFICIAL_API_BASE)
    valid = (
        candidate == OFFICIAL_API_BASE
        and parsed.scheme == expected.scheme == "https"
        and parsed.hostname == expected.hostname
        and parsed.port is None
        and parsed.path == expected.path
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )
    if not valid:
        raise RuntimeError(
            "Competition client must use the documented official Intern API endpoint"
        )
    return candidate


def validate_runtime_model(model: str, *, competition_mode: bool) -> str:
    """Reject accidental non-S1 use in the formal competition profile."""
    selected = str(model or "").strip()
    if not selected:
        raise RuntimeError("INTERN_MODEL must be non-empty")
    if competition_mode and selected != FORMAL_COMPETITION_MODEL:
        raise RuntimeError(
            "Competition mode permits only intern-s1. Set COMPETITION_MODE=0 "
            "only for a clearly labelled non-submission experiment."
        )
    return selected
