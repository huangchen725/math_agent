"""Conservative answer normalization and equivalence helpers.

The module returns ``None`` when equivalence cannot be proved safely. Unknown is
kept distinct from false so callers do not turn formatting heuristics into
mathematical evidence.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Any, Optional

from agent_types import Answer


_CATEGORICAL_ANSWERS = {
    "收敛",
    "发散",
    "是",
    "否",
    "true",
    "false",
    "yes",
    "no",
    "存在",
    "不存在",
}


def normalize_answer(answer: str) -> str:
    """Normalize notation without attempting unrestricted symbolic evaluation."""
    if not answer:
        return ""
    value = answer.strip()
    value = value.replace(r"\(", "").replace(r"\)", "")
    value = value.replace(r"\[", "").replace(r"\]", "")
    value = re.sub(r"\\boxed\{([^{}]*)\}", r"\1", value)
    for _ in range(3):
        value = re.sub(r"\\[d]?frac\{([^{}]+)\}\{([^{}]+)\}", r"\1/\2", value)
    value = re.sub(r"\\(?:mathbb|text|mathrm|mathcal)\{([^{}]*)\}", r"\1", value)
    value = value.replace(r"\displaystyle", "")
    value = value.replace("\\left", "").replace("\\right", "").replace("$", "")
    for command, replacement in [
        (r"\pi", "pi"),
        (r"\cdot", "*"),
        (r"\times", "*"),
        (r"\leq", "<="),
        (r"\le", "<="),
        (r"\geq", ">="),
        (r"\ge", ">="),
        (r"\neq", "!="),
        (r"\ne", "!="),
        (r"\infty", "oo"),
        (r"\to", "->"),
    ]:
        value = value.replace(command, replacement)
    value = re.sub(r"_([0-9]+)", r"\1", value)
    superscript_digits = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
    value = re.sub(
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+",
        lambda match: "^" + match.group(0).translate(superscript_digits),
        value,
    )
    for source, target in {
        "₀": "0",
        "₁": "1",
        "₂": "2",
        "₃": "3",
        "₄": "4",
        "₅": "5",
        "₆": "6",
        "₇": "7",
        "₈": "8",
        "₉": "9",
    }.items():
        value = value.replace(source, target)
    for source, target in {
        "ℤ": "Z",
        "ℝ": "R",
        "ℕ": "N",
        "ℚ": "Q",
        "ℂ": "C",
        "π": "pi",
        "∞": "oo",
        "−": "-",
        "×": "*",
        "⋅": "*",
        "≤": "<=",
        "≥": ">=",
        "≠": "!=",
        "∑": "sum",
        "∏": "prod",
        "∫": "int",
        "√": "sqrt",
        "→": "->",
        "∂": "d",
        "^": "**",
    }.items():
        value = value.replace(source, target)
    return value.rstrip("。.，,；;").strip("\"'").strip()


def numeric_value(answer: str) -> Optional[Fraction]:
    """Parse an exact integer, decimal, or simple fraction without ``eval``."""
    value = normalize_answer(answer).replace(" ", "")
    try:
        if re.fullmatch(r"[+-]?\d+", value):
            return Fraction(int(value), 1)
        if re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", value):
            return Fraction(Decimal(value))
        match = re.fullmatch(
            r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))"
            r"/([+-]?(?:\d+(?:\.\d*)?|\.\d+))",
            value,
        )
        if match:
            denominator = Decimal(match.group(2))
            if denominator == 0:
                return None
            return Fraction(Decimal(match.group(1))) / Fraction(denominator)
    except (InvalidOperation, ValueError, ZeroDivisionError):
        return None
    return None


def _split_top_level(value: str) -> Optional[list[str]]:
    parts = []
    current = []
    depth = 0
    for character in value:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
            if depth < 0:
                return None
        if character in ",，;；" and depth == 0:
            part = "".join(current).strip()
            if not part:
                return None
            parts.append(part)
            current = []
        else:
            current.append(character)
    if depth != 0:
        return None
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts


def canonical_answer(answer: str) -> tuple[Any, ...]:
    """Return a hashable key; equality of keys is safe but not necessarily complete."""
    normalized = normalize_answer(answer)
    number = numeric_value(normalized)
    if number is not None:
        return "number", number.numerator, number.denominator

    compact = normalized.replace(" ", "")
    if len(compact) >= 2 and compact[0] == "{" and compact[-1] == "}":
        parts = _split_top_level(compact[1:-1])
        if parts:
            keys = tuple(sorted((canonical_answer(part) for part in parts), key=repr))
            return "set", keys

    parts = _split_top_level(compact)
    if parts and len(parts) > 1:
        keys = tuple(sorted((canonical_answer(part) for part in parts), key=repr))
        return "multi", keys

    return "text", compact.casefold()


def answer_kind(answer: str) -> str:
    return str(canonical_answer(answer)[0])


def build_answer(raw: str) -> Answer:
    normalized = normalize_answer(raw)
    canonical = canonical_answer(normalized)
    return Answer(
        raw=raw,
        normalized=normalized,
        kind=str(canonical[0]),
        canonical=canonical,
    )


def format_answer_for_output(answer: str) -> str:
    """Render a compact final-answer body with stable ASCII-safe notation."""
    value = normalize_answer(answer)
    value = re.sub(r"^(?:最终)?答案(?:是|为)?\s*[:：]?\s*", "", value)
    value = value.replace("**", "^")
    return re.sub(r"\s+", " ", value).strip()


def equivalent_answers(left: str, right: str) -> Optional[bool]:
    """Return true/false only when equivalence or difference is safely known."""
    left_normalized = normalize_answer(left)
    right_normalized = normalize_answer(right)
    if not left_normalized or not right_normalized:
        return None
    left_key = canonical_answer(left_normalized)
    right_key = canonical_answer(right_normalized)
    if left_key == right_key:
        return True
    if left_key[0] == right_key[0] and left_key[0] in {"number", "set", "multi"}:
        return False
    if (
        left_normalized.casefold() in _CATEGORICAL_ANSWERS
        and right_normalized.casefold() in _CATEGORICAL_ANSWERS
    ):
        return False
    if (
        left_normalized.casefold() in _CATEGORICAL_ANSWERS
        and right_normalized.casefold() == f"不{left_normalized.casefold()}"
    ) or (
        right_normalized.casefold() in _CATEGORICAL_ANSWERS
        and left_normalized.casefold() == f"不{right_normalized.casefold()}"
    ):
        return False
    return None
