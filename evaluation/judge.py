"""Conservative offline answer judge with an explicit unknown state."""

from __future__ import annotations

import re
import ast
from dataclasses import dataclass
from typing import Literal

from answer_equivalence import equivalent_answers, normalize_answer
from deterministic_verifier import verify_symbolic_equivalence


JudgeStatus = Literal["correct", "wrong", "unknown", "no_answer"]
_SYMBOLIC_TEXT = re.compile(r"[A-Za-z0-9_+\-*/^().{}\[\]\\,\sπ∞]+")


def _domain_safe_polynomial(text):
    """Only polynomial syntax and division by a nonzero numeric literal need no domain assumptions."""
    if len(text) > 2048:
        return False
    try:
        tree = ast.parse(normalize_answer(text), mode="eval")
    except (SyntaxError, ValueError, RecursionError):
        return False
    nodes = list(ast.walk(tree))
    if len(nodes) > 128:
        return False
    allowed = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Name, ast.Load, ast.Constant,
               ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.UAdd, ast.USub)
    for node in nodes:
        if not isinstance(node, allowed):
            return False
        if isinstance(node, ast.Name) and (not node.id.isalpha() or node.id in {"oo", "nan", "inf"}):
            return False
        if isinstance(node, ast.Constant) and (type(node.value) is not int or abs(node.value) > 10**12):
            return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int or node.right.value == 0:
                return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            if not isinstance(node.right, ast.Constant) or type(node.right.value) is not int or not 0 <= node.right.value <= 12:
                return False
    return True


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
    if not (_domain_safe_polynomial(expected) and _domain_safe_polynomial(actual)):
        return JudgeResult("unknown", "domain_review_required", "symbolic simplification may discard domain conditions")
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
