"""Parse model answers and enforce the final response contract."""

from __future__ import annotations

import re

from .answer_equivalence import format_answer_for_output


def build_response(content: str, answer: str) -> str:
    formatted_answer = format_answer_for_output(answer)
    if not formatted_answer:
        return "未解出"
    formatted_answer = formatted_answer.splitlines()[0].strip()
    if not formatted_answer:
        return "未解出"
    if not content:
        return validate_response(f"最终答案：{formatted_answer}", formatted_answer)
    body_lines = [
        line
        for line in content.strip().splitlines()
        if not re.search(
            r"(?:最终答案\s*(?:是|为)?\s*[:：]?|答案\s*(?:是|为)\s*[:：]?|答案\s*[:：])",
            line,
        )
    ]
    body = "\n".join(body_lines).strip()
    if not body:
        return validate_response(f"最终答案：{formatted_answer}", formatted_answer)
    return validate_response(f"{body}\n最终答案：{formatted_answer}", formatted_answer)


def validate_response(response: str, answer: str) -> str:
    matches = re.findall(r"^\s*最终答案\s*[:：]\s*(.*?)\s*$", response, re.MULTILINE)
    lines = [line for line in response.splitlines() if line.strip()]
    valid = (
        len(matches) == 1
        and bool(matches[0].strip())
        and bool(lines)
        and re.fullmatch(r"\s*最终答案\s*[:：]\s*.+?\s*", lines[-1]) is not None
    )
    return response if valid else f"最终答案：{answer}"


def extract_answer(text: str) -> str:
    """Extract only an explicit answer marker; never guess from a reasoning tail."""
    if not text:
        return ""
    match = re.search(r"最终答案\s*[:：]\s*(.+?)(?:\n|$)", text)
    if match:
        return match.group(1).strip()
    match = re.search(r"\\boxed\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", text)
    if match:
        return match.group(1).strip()
    match = re.search(
        r"(?:候选)?答案(?:\s*(?:是|为)\s*|\s*[:：]\s*)"
        r"(.+?)(?:\n|。|$)",
        text,
    )
    return match.group(1).strip() if match else ""


def extract_first_line_answer(text: str) -> str:
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*最终答案\s*[:：]\s*(.+?)\s*", line)
        return match.group(1).strip() if match else ""
    return ""


def parse_verdict(verdict: str) -> bool | None:
    matches = re.findall(r"\bVERDICT\s*[:：]\s*([AB])\b", verdict, re.IGNORECASE)
    if matches:
        return matches[-1].upper() == "A"
    matches = re.findall(r"^\s*([AB])\s*$", verdict, re.IGNORECASE | re.MULTILINE)
    if matches:
        return matches[-1].upper() == "A"
    return None


def review_excerpt(text: str, limit: int = 3000) -> str:
    """Keep both ends so a verifier sees the opening answer and final reasoning."""
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    return f"{text[:head]}\n...[中间内容已截断]...\n{text[-tail:]}"
