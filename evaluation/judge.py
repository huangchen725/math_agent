"""Conservative offline answer judge with an explicit unknown state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from answer_equivalence import equivalent_answers
from deterministic_verifier import verify_symbolic_equivalence


JudgeStatus = Literal["correct", "wrong", "unknown", "no_answer"]
_SYMBOLIC_TEXT = re.compile(r"[A-Za-z0-9_+\-*/^().{}\[\]\\,\sπ∞]+")


@dataclass(frozen=True)
class JudgeResult:
    status: JudgeStatus
    method: str
    detail: str = ""


def judge_answer(
    expected: str,
    actual: str,
    *,
    symbolic_timeout_seconds: float = 5.0,
) -> JudgeResult:
    """Judge only provable equivalence; semantic ambiguity remains unknown."""
    if not isinstance(actual, str) or not actual.strip():
        return JudgeResult("no_answer", "empty")
    if not isinstance(expected, str) or not expected.strip():
        return JudgeResult("unknown", "missing_expected")

    conservative = equivalent_answers(expected, actual)
    if conservative is True:
        return JudgeResult("correct", "canonical")
    if conservative is False:
        return JudgeResult("wrong", "canonical")

    if not (_SYMBOLIC_TEXT.fullmatch(expected) and _SYMBOLIC_TEXT.fullmatch(actual)):
        return JudgeResult(
            "unknown",
            "semantic_review_required",
            "textual answers are never accepted by substring",
        )
    verification = verify_symbolic_equivalence(
        expected,
        actual,
        timeout_seconds=symbolic_timeout_seconds,
    )
    status: JudgeStatus
    if verification.status == "pass":
        status = "correct"
    elif verification.status == "fail":
        status = "wrong"
    else:
        status = "unknown"
    return JudgeResult(status, verification.source, verification.detail)
