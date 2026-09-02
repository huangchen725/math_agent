"""Competition evidence constants and fail-closed runtime validation."""

from __future__ import annotations

import os
from types import MappingProxyType
from typing import Mapping
from urllib.parse import urlsplit


OFFICIAL_MATERIAL_SHA256 = MappingProxyType({
    "competition_handbook_pdf": (
        "ece081cd4a0c4f496943b3e3c7d79716d8ffd1d9a6249e11bb3ed5c4a39902d7"
    ),
    "official_tools_notice_docx": (
        "6855baa8b2ebaa38642725ca3404f7ad98cbadee7fb695ccccc04faf9667c8c4"
    ),
    "official_message_screenshots_docx": (
        "30cac629e87703c8decf28e9596af56e6c280be8a84745db8199e47cccd1401e"
    ),
    "atomgit_deadline_message_transcript": (
        "757377813dc101c3ad3574aa2b1acb0da12ffe7e6178fd79c9b716a46a1defa3"
    ),
})
COMPETITION_MANUAL_SHA256 = OFFICIAL_MATERIAL_SHA256["competition_handbook_pdf"]
OFFICIAL_BASELINE_COMMIT = "43be244a880d64a1f9d3a631aa7d9e976f26c17b"
OFFICIAL_EVIDENCE_URLS = MappingProxyType({
    "atomgit_competition_intro": (
        "https://competition.gitcode.com/competition/2074065063594618882/intro"
    ),
    "feishu_registration_guide": (
        "https://aicarrier.feishu.cn/wiki/VTSdwzVoPi0AdVkZhkWcnFQznAd"
    ),
    "feishu_rule_updates": (
        "https://aicarrier.feishu.cn/wiki/C3dBwzdyFiDxEIkYq7ucOZ59neh"
    ),
    "feishu_preliminary_rules": (
        "https://aicarrier.feishu.cn/wiki/L90FwD9gJiqdg0k33RCcHTdcnrb"
    ),
    "feishu_faq": "https://aicarrier.feishu.cn/wiki/BHoMw601Xiy5i3keTLDcg3M3n5x",
})
OFFICIAL_EVIDENCE_VERIFIED_ON = MappingProxyType({
    "atomgit_competition_intro": "2026-09-01",
    "feishu_registration_guide": "2026-09-01",
    "feishu_rule_updates": "2026-09-01",
    "feishu_preliminary_rules": "2026-09-02",
    "feishu_faq": "2026-09-01",
})
OFFICIAL_WEB_EVIDENCE_VERIFIED_ON = max(OFFICIAL_EVIDENCE_VERIFIED_ON.values())
FORMAL_COMPETITION_MODEL = "intern-s1"
FORMAL_COMPETITION_MODELS = frozenset({
    "intern-s1",
    "intern-s1-pro",
    "intern-s2-preview",
})
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
    """Reject models outside the exact documented Intern-S allowlist."""
    selected = str(model or "").strip()
    if not selected:
        raise RuntimeError("INTERN_MODEL must be non-empty")
    if competition_mode and selected not in FORMAL_COMPETITION_MODELS:
        raise RuntimeError(
            "Competition mode permits only documented Intern-S models: "
            f"{', '.join(sorted(FORMAL_COMPETITION_MODELS))}. Set "
            "COMPETITION_MODE=0 only for a clearly labelled non-submission "
            "experiment."
        )
    return selected
