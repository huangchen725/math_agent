"""Zero-request task analysis and conservative deterministic verification plans.

The router deliberately recognizes only direct, structurally explicit questions.
Ambiguous, proof-like, constrained-domain, or multi-operation problems may still
receive broad task labels, but they do not receive an executable verification
plan.  This keeps a routing miss harmless: candidate selection falls back to the
existing model-verifier and majority rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal


TaskType = Literal[
    "calculation",
    "equation",
    "derivative",
    "integral",
    "limit",
    "residue",
    "matrix_determinant",
    "modular_power",
    "binomial",
    "proof",
    "optimization",
    "probability",
    "general",
]


@dataclass(frozen=True)
class VerificationPlan:
    """A bounded, explicit operation that can be checked without another model."""

    kind: str
    parameters: tuple[tuple[str, str], ...]
    confidence: float = 1.0

    def as_kwargs(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True)
class TaskAnalysis:
    """Local task labels plus at most one unambiguous verification plan."""

    task_types: tuple[TaskType, ...]
    confidence: float
    verification_plan: VerificationPlan | None = None
    reason: str = "keyword_only"

    @property
    def deterministically_verifiable(self) -> bool:
        return self.verification_plan is not None


_PROOF_MARKERS = (
    "证明",
    "推导",
    "说明为什么",
    "show that",
    "prove that",
    "prove ",
    "derive ",
)

_TASK_MARKERS: tuple[tuple[TaskType, tuple[str, ...]], ...] = (
    ("equation", ("解方程", "solve the equation", "solve equation")),
    ("derivative", ("导数", "求导", "differentiate", "derivative")),
    ("integral", ("不定积分", "积分", "integrate", "antiderivative")),
    ("limit", ("极限", "limit", "lim_", "lim{")),
    ("residue", ("留数", "residue", "res(")),
    ("matrix_determinant", ("行列式", "determinant", "det(")),
    ("modular_power", ("余数", "模幂", "modulo", " mod ")),
    ("binomial", ("组合数", "二项式系数", "binomial coefficient", "binom")),
    ("optimization", ("最优化", "最大值", "最小值", "maximize", "minimize")),
    ("probability", ("概率", "期望", "方差", "probability", "expectation")),
)

_UNSUPPORTED_EQUATION_DOMAINS = (
    "整数",
    "正根",
    "正数",
    "非负",
    "integer",
    "positive root",
    "nonnegative",
)

_REAL_EQUATION_DOMAINS = (
    "实根",
    "实数解",
    "实数范围",
    "实数域",
    "real root",
    "real solution",
    "over the reals",
)

_COMPLEX_EQUATION_DOMAINS = (
    "复根",
    "复数解",
    "复数范围",
    "复数域",
    "complex root",
    "complex solution",
    "over the complex",
)

_SAFE_EXPRESSION = re.compile(r"[A-Za-z0-9_\s+\-*/^().,]+\Z")
_MAX_EXPRESSION_CHARS = 2048
_CLOSED_EXPRESSION_NAMES = {
    "E",
    "I",
    "Rational",
    "acos",
    "asin",
    "atan",
    "cos",
    "cosh",
    "exp",
    "factorial",
    "gamma",
    "log",
    "oo",
    "pi",
    "sin",
    "sinh",
    "sqrt",
    "tan",
    "tanh",
}


def analyze_task(problem: str) -> TaskAnalysis:
    """Classify a problem locally and build a plan only for a strict direct task."""
    if not isinstance(problem, str) or not problem.strip():
        return TaskAnalysis(("general",), 0.0, reason="empty")

    normalized = problem.casefold()
    proof_like = any(marker in normalized for marker in _PROOF_MARKERS)
    labels: list[TaskType] = []
    if proof_like:
        labels.append("proof")
    for task_type, markers in _TASK_MARKERS:
        if any(marker in normalized for marker in markers):
            labels.append(task_type)

    plan = None if proof_like else _extract_verification_plan(problem)
    if plan is not None:
        plan_type = _plan_task_type(plan.kind)
        labels = [plan_type, *(label for label in labels if label != plan_type)]
        return TaskAnalysis(
            tuple(labels),
            plan.confidence,
            verification_plan=plan,
            reason="strict_direct_pattern",
        )

    if not labels:
        labels = ["general"]
    confidence = 0.65 if len(labels) == 1 and labels[0] != "general" else 0.4
    if labels == ["general"]:
        confidence = 0.0
    return TaskAnalysis(
        tuple(labels),
        confidence,
        reason="proof_blocked" if proof_like else "keyword_only",
    )


def _plan_task_type(kind: str) -> TaskType:
    mapping: dict[str, TaskType] = {
        "expression": "calculation",
        "equation_solutions": "equation",
        "derivative": "derivative",
        "integral": "integral",
        "limit": "limit",
        "residue": "residue",
        "matrix_determinant": "matrix_determinant",
        "modular_power": "modular_power",
        "binomial": "binomial",
    }
    return mapping.get(kind, "general")


def _extract_verification_plan(problem: str) -> VerificationPlan | None:
    for extractor in (
        _extract_modular_power,
        _extract_binomial,
        _extract_matrix_determinant,
        _extract_derivative,
        _extract_integral,
        _extract_limit,
        _extract_residue,
        _extract_equation,
        _extract_expression,
    ):
        plan = extractor(problem)
        if plan is not None:
            return plan
    return None


def _plan(kind: str, **parameters: str) -> VerificationPlan:
    return VerificationPlan(kind, tuple(sorted(parameters.items())))


def _clean_expression(raw: str) -> str | None:
    value = str(raw).strip()
    if not value or len(value) > _MAX_EXPRESSION_CHARS:
        return None
    value = value.strip("$ ")
    value = value.replace(r"\(", "").replace(r"\)", "")
    value = value.replace(r"\[", "").replace(r"\]", "")
    value = value.replace(r"\left", "").replace(r"\right", "")
    value = value.replace(r"\,", "").replace(r"\!", "")
    for command, replacement in (
        (r"\cdot", "*"),
        (r"\times", "*"),
        (r"\pi", "pi"),
        (r"\infty", "oo"),
    ):
        value = value.replace(command, replacement)
    for _ in range(3):
        value = re.sub(r"\\(?:d?frac)\{([^{}]+)\}\{([^{}]+)\}", r"(\1)/(\2)", value)
    value = re.sub(r"\\(?=(?:sin|cos|tan|log|exp|sqrt)\b)", "", value)
    value = value.replace("{", "(").replace("}", ")")
    value = value.translate(str.maketrans({"−": "-", "×": "*", "⋅": "*", "π": "pi"}))
    value = value.rstrip("。！？?;； ")
    if not value or not _SAFE_EXPRESSION.fullmatch(value):
        return None
    return value.strip()


def _bounded_integer(raw: str, *, positive: bool = False) -> str | None:
    value = str(raw).strip()
    if not re.fullmatch(r"[+-]?\d{1,1000}", value):
        return None
    if positive and int(value) <= 0:
        return None
    return str(int(value))


def _is_closed_expression(expression: str) -> bool:
    names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expression))
    return names.issubset(_CLOSED_EXPRESSION_NAMES)


def _extract_modular_power(problem: str) -> VerificationPlan | None:
    patterns = (
        r"([+-]?\d+)\s*(?:\^|\*\*)\s*(\d+)\s*(?:除以|模)\s*([1-9]\d*)\s*(?:的)?(?:余数)?",
        r"([+-]?\d+)\s*(?:\^|\*\*)\s*(\d+)\s*(?:mod(?:ulo)?)\s*([1-9]\d*)",
        r"remainder\s+(?:when|of)\s+([+-]?\d+)\s*(?:\^|\*\*)\s*(\d+)\s+(?:is\s+)?divided\s+by\s+([1-9]\d*)",
    )
    for pattern in patterns:
        match = re.search(pattern, problem, re.IGNORECASE)
        if not match:
            continue
        base = _bounded_integer(match.group(1))
        exponent = _bounded_integer(match.group(2))
        modulus = _bounded_integer(match.group(3), positive=True)
        if base is not None and exponent is not None and modulus is not None:
            return _plan(
                "modular_power",
                base=base,
                exponent=exponent,
                modulus=modulus,
            )
    return None


def _extract_binomial(problem: str) -> VerificationPlan | None:
    patterns = (
        r"(?:C|c)\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)",
        r"\\binom\s*\{\s*(\d+)\s*\}\s*\{\s*(\d+)\s*\}",
    )
    for pattern in patterns:
        match = re.search(pattern, problem)
        if not match:
            continue
        prefix = problem[:match.start()].casefold()
        suffix = problem[match.end():].strip().casefold().rstrip("。！？?. ")
        if not any(
            marker in prefix
            for marker in ("计算", "求值", "组合数", "二项式系数", "compute", "calculate", "evaluate")
        ):
            continue
        if suffix not in {"", "的值", "value", "the value"}:
            continue
        n = _bounded_integer(match.group(1))
        k = _bounded_integer(match.group(2))
        if n is None or k is None:
            return None
        n_value, k_value = int(n), int(k)
        if 0 <= k_value <= n_value <= 100_000:
            return _plan("binomial", n=n, k=k)
    return None


def _extract_balanced_matrix(problem: str) -> str | None:
    start = problem.find("[[")
    if start < 0:
        return None
    depth = 0
    for index in range(start, min(len(problem), start + 8192)):
        character = problem[index]
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return problem[start:index + 1]
            if depth < 0:
                return None
    return None


def _extract_matrix_determinant(problem: str) -> VerificationPlan | None:
    normalized = problem.casefold()
    if not any(marker in normalized for marker in ("行列式", "determinant", "det(")):
        return None
    if not (
        re.search(r"(?:求|计算).{0,80}行列式", problem, re.DOTALL)
        or re.search(r"(?:find|compute|calculate).{0,80}determinant", normalized, re.DOTALL)
    ):
        return None
    matrix_text = _extract_balanced_matrix(problem)
    if not matrix_text:
        return None
    try:
        matrix = json.loads(matrix_text)
    except (json.JSONDecodeError, TypeError):
        return None
    if (
        not isinstance(matrix, list)
        or not matrix
        or len(matrix) > 12
        or not all(isinstance(row, list) and row for row in matrix)
        or any(len(row) != len(matrix[0]) or len(row) > 12 for row in matrix)
    ):
        return None
    for row in matrix:
        for cell in row:
            if isinstance(cell, bool) or not isinstance(cell, (int, float, str)):
                return None
            cleaned_cell = _clean_expression(str(cell))
            if cleaned_cell is None or not _is_closed_expression(cleaned_cell):
                return None
    compact = json.dumps(matrix, ensure_ascii=False, separators=(",", ":"))
    return _plan("matrix_determinant", matrix=compact)


def _extract_derivative(problem: str) -> VerificationPlan | None:
    patterns = (
        r"(?:求|计算)\s*(?:函数\s*)?[A-Za-z]\s*\(\s*([A-Za-z])\s*\)\s*=\s*(.+?)\s*的(?:一阶)?导数",
        r"(?:求|计算)\s*(.+?)\s*(?:关于|对)\s*([A-Za-z])\s*的(?:一阶)?导数",
        r"(?:differentiate|find\s+the\s+derivative\s+of)\s+(.+?)\s+(?:with\s+respect\s+to|w\.?r\.?t\.?)\s+([A-Za-z])",
    )
    for index, pattern in enumerate(patterns):
        match = re.search(pattern, problem, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        variable, expression = (
            (match.group(1), match.group(2))
            if index == 0
            else (match.group(2), match.group(1))
        )
        cleaned = _clean_expression(expression)
        if cleaned:
            return _plan("derivative", expression=cleaned, variable=variable)
    return None


def _extract_integral(problem: str) -> VerificationPlan | None:
    normalized = problem.casefold()
    if any(marker in normalized for marker in ("最大", "最小", "maximum", "minimum")):
        return None
    if re.search(r"(?:\\int|∫)\s*_", problem) and "不定积分" not in problem:
        return None
    patterns = (
        r"(?:计算|求)\s*不定积分\s*[∫]\s*(.+?)\s*d\s*([A-Za-z])",
        r"(?:计算|求)\s*不定积分\s*\\int\s*(.+?)\s*\\?,?d\s*([A-Za-z])",
        r"(?:integrate|find\s+an\s+antiderivative\s+of)\s+(.+?)\s+(?:with\s+respect\s+to|w\.?r\.?t\.?)\s+([A-Za-z])",
        r"(?:求|计算)\s*(.+?)\s*(?:关于|对)\s*([A-Za-z])\s*的不定积分",
    )
    for pattern in patterns:
        match = re.search(pattern, problem, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        cleaned = _clean_expression(match.group(1))
        if cleaned:
            return _plan("integral", expression=cleaned, variable=match.group(2))
    return None


def _extract_limit(problem: str) -> VerificationPlan | None:
    normalized = problem.replace(r"\to", "->").replace("→", "->")
    normalized = normalized.replace(r"\lim", "lim")
    match = re.search(
        r"lim\s*_?\s*\{?\s*([A-Za-z])\s*->\s*([^}\s]+)\s*\}?\s*(.+)",
        normalized,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    prefix = normalized[:match.start()].casefold()
    if not any(marker in prefix for marker in ("求", "计算", "find", "compute", "evaluate")):
        return None
    variable = match.group(1)
    point = _clean_expression(match.group(2))
    expression = _clean_expression(re.sub(r"\s*的?极限\s*$", "", match.group(3)))
    if point and expression:
        return _plan("limit", expression=expression, variable=variable, point=point)
    return None


def _extract_residue(problem: str) -> VerificationPlan | None:
    patterns = (
        r"(?:求|计算)\s*(?:函数\s*)?(?:[A-Za-z]\s*\(\s*[A-Za-z]\s*\)\s*=\s*)?(.+?)\s*在\s*([A-Za-z])\s*=\s*(.+?)\s*处的留数",
        r"(?:find|compute)\s+the\s+residue\s+of\s+(.+?)\s+at\s+([A-Za-z])\s*=\s*([^\s.,;]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, problem, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        expression = _clean_expression(match.group(1))
        pole = _clean_expression(match.group(3))
        if expression and pole:
            return _plan(
                "residue",
                expression=expression,
                variable=match.group(2),
                pole=pole,
            )
    return None


def _clean_equation(raw: str) -> str | None:
    value = raw.strip().rstrip("。！？?;；. ")
    if value.count("=") != 1:
        return None
    left, right = value.split("=", 1)
    clean_left = _clean_expression(left)
    clean_right = _clean_expression(right)
    if not clean_left or not clean_right:
        return None
    return f"{clean_left}={clean_right}"


def _infer_equation_variable(equation: str) -> str | None:
    names = set(re.findall(r"\b([A-Za-z])\b", equation))
    names.difference_update({"E", "I"})
    return next(iter(names)) if len(names) == 1 else None


def _extract_equation(problem: str) -> VerificationPlan | None:
    normalized = problem.casefold()
    if any(marker in normalized for marker in _UNSUPPORTED_EQUATION_DOMAINS):
        return None
    if any(marker in normalized for marker in _REAL_EQUATION_DOMAINS):
        domain = "real"
    elif any(marker in normalized for marker in _COMPLEX_EQUATION_DOMAINS):
        domain = "complex"
    else:
        return None
    stripped_problem = re.sub(
        r"\s*(?:的)?(?:所有)?(?:实根|实数解|复根|复数解)\s*",
        " ",
        problem,
        flags=re.IGNORECASE,
    )
    stripped_problem = re.sub(
        r"\s*(?:在|于)?\s*(?:实数|复数)(?:范围|域)?(?:内|上)?\s*",
        " ",
        stripped_problem,
        flags=re.IGNORECASE,
    )
    stripped_problem = re.sub(
        r"\s*(?:for\s+)?(?:all\s+)?(?:real|complex)\s+(?:roots?|solutions?)\s*",
        " ",
        stripped_problem,
        flags=re.IGNORECASE,
    )
    stripped_problem = re.sub(
        r"\s*over\s+the\s+(?:reals|complex(?:\s+numbers)?)\s*",
        " ",
        stripped_problem,
        flags=re.IGNORECASE,
    )
    patterns = (
        r"解方程\s*[:：]?\s*(.+?=.+?)(?:\s*(?:关于|求)\s*([A-Za-z])\s*(?:的解)?)?\s*[。！？?]*$",
        r"solve\s+(?:the\s+)?equation\s+(.+?=.+?)(?:\s+for\s+([A-Za-z]))?\s*[.?]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, stripped_problem, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        equation = _clean_equation(match.group(1))
        if not equation:
            continue
        variable = match.group(2) or _infer_equation_variable(equation)
        if variable:
            return _plan(
                "equation_solutions",
                equation=equation,
                variable=variable,
                domain=domain,
            )
    return None


def _extract_expression(problem: str) -> VerificationPlan | None:
    match = re.fullmatch(
        r"\s*(?:计算|求值|calculate|evaluate)\s*[:：]?\s*(.+?)\s*[。！？?]*\s*",
        problem,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    expression = _clean_expression(match.group(1))
    if expression and _is_closed_expression(expression):
        return _plan("expression", expression=expression)
    return None
