"""Typed internal records for candidates, answers, and verification evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


VerificationStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True)
class Answer:
    """A conservatively normalized answer extracted from one candidate."""

    raw: str
    normalized: str
    kind: str
    canonical: Any = None


@dataclass(frozen=True)
class Verification:
    """One piece of evidence about a candidate answer."""

    source: str
    status: VerificationStatus
    confidence: float
    detail: str = ""


@dataclass
class Candidate:
    """A generated solution and all evidence used to select it."""

    content: str
    strategy: str
    answer: Answer
    confidence: float
    raw_confidence: float
    verifications: list[Verification] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

