"""Offline source adapters for fixed, explicitly licensed public answer banks.

Source trust means source pairing and provenance, never an independent proof.
This module never imports a model client and does not read evaluation labels.
"""
from __future__ import annotations

import argparse
from collections import Counter
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET


KNOWN_SOURCE_QUARANTINE = {
    "umath-00d40e3ce13ab1756fe05034": "hourglass_area_source_omits_parameter_sign_conditions",
}


def digest_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def isolation_key(text: str) -> str:
    """Aggressive exclusion only; NEVER a runtime identity match."""
    value = unicodedata.normalize("NFKC", text).casefold()
    value = value.replace(r"\left", "").replace(r"\right", "")
    value = value.replace("→", "->").replace("−", "-").replace("×", "*")
    value = re.sub(r"[\s，。,.！？?：:；;、'\"`$\\{}\[\]()]", "", value)
    return re.sub(r"\d+(?:\.\d+)?", "#", value)


def near(left: str, right: str) -> bool:
    if left == right:
        return True
    matcher = SequenceMatcher(None, left, right)
    return matcher.quick_ratio() >= .88 and (
        matcher.ratio() >= .88 or SequenceMatcher(None, right, left).ratio() >= .88)


def input_exclusions(paths: list[Path]) -> tuple[list[str], list[dict]]:
    keys, evidence = set(), []
    for path in paths:
        if not path.name.endswith(".input.jsonl"):
            raise ValueError("exclusion requires question-only input file")
        raw = path.read_bytes()
        rows = [json.loads(line) for line in raw.decode("utf-8-sig").splitlines() if line.strip()]
        if any(set(row) != {"idx", "problem"} for row in rows):
            raise ValueError("exclusion input contains unexpected or label fields")
        keys.update(isolation_key(row["problem"]) for row in rows)
        evidence.append({"file": path.name, "sha256": digest_bytes(raw), "records": len(rows)})
    return sorted(keys), evidence


def record(source, path, revision, raw, key, problem, answer, license_name, domain):
    authors = {"umath": "U-MATH authors: Konstantin Chernyshev et al.; Toloka AI and Gradarius",
               "dmoi3": "Oscar Levin", "diffyqs": "Jiri Lebl"}
    return {
        "id": source + "-" + sha256((path + "#" + key).encode()).hexdigest()[:24],
        "problem": problem, "answer": answer, "solution": answer,
        "source": source, "source_url": path, "source_revision": revision,
        "source_sha256": digest_bytes(raw), "license": license_name,
        "split": "public_retrieval", "domain": domain, "trust": "source_verified",
        "metadata": {"source_key": key, "verification": "source_paired_answer_not_independent_math_proof",
                     "level": "university_source_label", "language": "en", "attribution": authors[source],
                     "adaptation": "Source paired answer; whitespace/standard presentation macros normalized; no new solution generated",
                     "upstream_split": "test_public_release" if source == "umath" else "public_textbook"},
    }


def umath(root: Path, blocked: list[str], stats: Counter) -> list[dict]:
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    raw = (root / "records.jsonl").read_bytes()
    card = (root / "SOURCE_README.md").read_bytes()
    if digest_bytes(raw) != provenance["records_sha256"] or digest_bytes(card) != provenance["readme_sha256"]:
        raise ValueError("U-MATH source digest mismatch")
    if b"All the dataset contents are available under the MIT license" not in card:
        raise ValueError("unapproved U-MATH licensing")
    revision = provenance["revision"]
    result = []
    # Exclude by question BEFORE touching the source answer field.
    for line in raw.decode("utf-8").splitlines():
        row = json.loads(line)
        stats["umath_source_rows"] += 1
        if any(near(isolation_key(row["problem"]), key) for key in blocked):
            stats["umath_q0_exact_or_near_excluded"] += 1
            continue
        result.append(record("umath", f"https://huggingface.co/datasets/toloka/u-math/tree/{revision}",
                             revision, line.encode("utf-8"), row["idx"], row["problem"], row["answer"],
                             "MIT", row["subject"]))
    return result


def strip_tex_comments(text: str) -> str:
    return re.sub(r"(?<!\\)%[^\n]*", "", text)


def braced(text: str, start: int) -> tuple[str, int]:
    if start >= len(text) or text[start] != "{":
        raise ValueError("missing group")
    level = 1
    for pos in range(start + 1, min(len(text), start + 100_001)):
        if pos > 0 and text[pos - 1] == "\\":
            continue
        if text[pos] == "{":
            level += 1
        elif text[pos] == "}":
            level -= 1
            if not level:
                return text[start + 1:pos], pos + 1
    raise ValueError("unclosed group")


def clean_tex(text: str) -> str:
    text = strip_tex_comments(text).strip()
    text = re.sub(r"\\label\{[^{}]*\}", "", text)
    # Only presentation macros with an unambiguous standard LaTeX meaning.
    text = text.replace(r"\nicefrac", r"\frac").replace(r"\myquote", r"\text")
    text = re.sub(r"\\R\b", lambda _: r"\mathbb{R}", text)
    text = re.sub(r"\\C\b", lambda _: r"\mathbb{C}", text)
    text = re.sub(r"\\pagebreak(?:\[[0-9]+\])?", "", text)
    text = re.sub(r"\\leavevmode\b", "", text)
    text = re.sub(r"\\begin\{tasks\}(?:\([0-9]+\))?", lambda _: r"\begin{enumerate}", text)
    text = text.replace(r"\end{tasks}", r"\end{enumerate}")
    text = re.sub(r"\\task\b", lambda _: r"\item", text)
    text = re.sub(r"\\begin\{exercise\}(?:\[[^\]]*\])?", "", text)
    return re.sub(r"\s+", " ", text).strip()


_UNRESOLVED_TEX = re.compile(
    r"\\(?:[a-zA-Z]*ref|[a-zA-Z]*includegraphics|input|include|href|url|fig|figure|tikz|vref|subref|tag|unit|unitfrac|arabic|n|twoline)\b"
    r"|\\begin\{(?:figure|tikzpicture|picture|pspicture)\}"
    r"|\b(?:previous exercise|preceding exercise|above exercise|figure below|following figure|pictured|shown below|as before|as above|the forest)\b", re.I)


def diffyqs(root: Path, stats: Counter) -> list[dict]:
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    license_text = (root / "LICENSE.md").read_text(encoding="utf-8")
    if "Attribution-Share Alike 4.0" not in license_text:
        raise ValueError("unapproved Diffy Qs licensing")
    result = []
    for entry in provenance["files"]:
        path = root / entry["path"]
        if not path.name.startswith(("ch-", "ap-")) or path.suffix != ".tex":
            continue
        raw = path.read_bytes()
        if digest_bytes(raw) != entry["sha256"]:
            raise ValueError("Diffy Qs source digest mismatch")
        text = strip_tex_comments(raw.decode("utf-8"))
        for match in re.finditer(r"\\begin\{exercise\}(?:\[[^\]]*\])?(.*?)\\end\{exercise\}", text, re.S):
            solution_start = re.match(r"\s*\\exsol\s*", text[match.end():])
            if solution_start is None:
                continue
            stats["diffyqs_source_pairs"] += 1
            answer, _ = braced(text, match.end() + solution_start.end())
            problem = match.group(1)
            if _UNRESOLVED_TEX.search(problem + answer):
                stats["diffyqs_unresolved_context_excluded"] += 1
                continue
            result.append(record("diffyqs", entry["url"], provenance["revision"], raw,
                                 "exercise_at_" + str(match.start()), clean_tex(problem), clean_tex(answer),
                                 "CC-BY-SA-4.0", "differential_equations"))
    return result


_XML_BAD = {"xref", "image", "figure", "video", "interactive", "webwork", "sage", "asymptote", "latex-image", "tabular", "fillin"}
_XML_SKIP = {"idx", "title", "hint", "author"}


def render_xml(node: ET.Element) -> str:
    tag = node.tag.split("}")[-1]
    if tag in _XML_SKIP:
        return ""
    if tag in {"ellipsis", "ndash", "mdash"}:
        return {"ellipsis": "...", "ndash": "-", "mdash": "--"}[tag]
    parts = [node.text or ""]
    for i, child in enumerate(node):
        if tag in {"ol", "ul"} and child.tag.split("}")[-1] == "li":
            parts.append(f" ({i + 1}) ")
        parts.append(render_xml(child))
        parts.append(child.tail or "")
    body = "".join(parts)
    if tag == "m":
        return r"\(" + body.strip() + r"\)"
    if tag in {"me", "men", "md", "mdn"}:
        body = body.strip().removesuffix(r"\\").strip()
        if tag in {"md", "mdn"}:
            body = r"\begin{aligned}" + body + r"\end{aligned}"
        return r"\[" + body + r"\]"
    if tag == "mrow":
        return body.strip() + r" \\ "
    if tag in {"p", "li", "statement", "solution", "answer"}:
        return " " + body + " "
    if tag == "q":
        return '"' + body + '"'
    return body


def dmoi_macros(text: str) -> str:
    """Expand only fixed source/bookinfo.ptx definitions, not inferred math."""
    replacements = {
        "N": r"\mathbb{N}", "Z": r"\mathbb{Z}", "Q": r"\mathbb{Q}",
        "R": r"\mathbb{R}", "C": r"\mathbb{C}", "U": r"\mathcal{U}",
        "pow": r"\mathcal{P}", "inv": "^{-1}", "st": ":", "imp": r"\rightarrow",
        "Imp": r"\Rightarrow", "d": r"\displaystyle", "amp": "&", "lt": "<", "gt": ">",
    }
    text = re.sub(r"\\([a-zA-Z]+)", lambda match: replacements.get(match.group(1), match.group(0)), text)
    pos = 0
    while (match := re.search(r"\\card\s*", text[pos:])) is not None:
        start = pos + match.start()
        arg_start = pos + match.end()
        argument, end = braced(text, arg_start)
        replacement = r"\left|" + argument + r"\right|"
        text = text[:start] + replacement + text[end:]
        pos = start + len(replacement)
    return text


def dmoi(root: Path, stats: Counter) -> list[dict]:
    provenance = json.loads((root / "provenance.json").read_text(encoding="utf-8"))
    if "Attribution-ShareAlike 4.0" not in (root / "LICENSE").read_text(encoding="utf-8"):
        raise ValueError("unapproved DMOI third edition licensing")
    result = []
    for entry in provenance["files"]:
        if not entry["path"].endswith(".ptx"):
            continue
        raw = (root / entry["path"]).read_bytes()
        if digest_bytes(raw) != entry["sha256"]:
            raise ValueError("DMOI source digest mismatch")
        if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:
            raise ValueError("unsupported XML declaration")
        tree = ET.fromstring(raw)
        for number, node in enumerate(tree.iter()):
            if node.tag not in {"exercise", "example"}:
                continue
            problem = node.find("statement")
            answers = [child for child in node if child.tag in {"solution", "answer"}]
            if problem is None or len(answers) != 1:
                stats["dmoi_no_single_complete_pair"] += 1
                continue
            stats["dmoi_source_pairs"] += 1
            if any(child.tag.split("}")[-1] in _XML_BAD for part in (problem, answers[0]) for child in part.iter()):
                stats["dmoi_unresolved_context_excluded"] += 1
                continue
            question = dmoi_macros(re.sub(r"\s+", " ", render_xml(problem)).strip())
            answer = dmoi_macros(re.sub(r"\s+", " ", render_xml(answers[0])).strip())
            if _UNRESOLVED_TEX.search(question + answer):
                stats["dmoi_unresolved_context_excluded"] += 1
                continue
            key = node.get("{http://www.w3.org/XML/1998/namespace}id") or node.get("permid") or str(number)
            if "Three kids, Alberto, Bernadette, and Carlos" in question:
                stats["dmoi_source_explanation_inconsistency_quarantined"] += 1
                continue
            result.append(record("dmoi3", entry["url"], provenance["revision"], raw, key,
                                 question, answer, "CC-BY-SA-4.0", "discrete_mathematics"))
    return result


def finish(rows: list[dict], blocked: list[str], stats: Counter) -> tuple[list[dict], list[dict]]:
    groups: dict[str, list[dict]] = {}
    quarantine = []
    for row in rows:
        if row["id"] in KNOWN_SOURCE_QUARANTINE:
            stats["known_source_math_defect_quarantined"] += 1
            quarantine.append({"id": row["id"], "reason": KNOWN_SOURCE_QUARANTINE[row["id"]]})
            continue
        if any(ord(char) < 32 and char not in "\t\n\r" for char in row["problem"] + row["answer"]):
            stats["source_control_character_quarantined"] += 1
            quarantine.append({"id": row["id"], "reason": "source_control_character_corruption"})
            continue
        if not row["problem"].strip() or not row["answer"].strip():
            stats["empty_pair_excluded"] += 1
            continue
        if len(row["problem"]) > 20_000 or len(row["answer"]) > 12_000 or len(json_bytes(row)) > 64_000:
            stats["oversize_pair_excluded"] += 1
            continue
        if row["source"] != "umath" and any(near(isolation_key(row["problem"]), key) for key in blocked):
            stats["textbook_q0_exact_or_near_excluded"] += 1
            continue
        # Exact content only; formatting differences are separately audited by builder.
        key = re.sub(r"\s+", " ", row["problem"]).strip()
        groups.setdefault(key, []).append(row)
    accepted = []
    for group in groups.values():
        if len({row["answer"] for row in group}) > 1:
            quarantine.extend({"id": row["id"], "reason": "same_question_different_source_answer"} for row in group)
            stats["conflicting_pair_excluded"] += len(group)
        else:
            accepted.append(sorted(group, key=lambda row: row["id"])[0])
            stats["identical_pair_deduplicated"] += len(group) - 1
    return sorted(accepted, key=lambda row: row["id"]), quarantine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--umath", type=Path, required=True)
    parser.add_argument("--textbooks", type=Path, required=True)
    parser.add_argument("--exclude-input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    blocked, evidence = input_exclusions(args.exclude_input)
    stats = Counter()
    rows = umath(args.umath, blocked, stats) + diffyqs(args.textbooks / "diffyqs", stats) + dmoi(args.textbooks / "dmoi3", stats)
    rows, quarantine = finish(rows, blocked, stats)
    args.output.mkdir(parents=True, exist_ok=True)
    data = b"".join(json_bytes(row) + b"\n" for row in rows)
    (args.output / "records.jsonl").write_bytes(data)
    summary = {"status": "source_prepared_not_math_verified", "records": len(rows), "records_sha256": digest_bytes(data),
               "sources": dict(Counter(row["source"] for row in rows)), "domains": dict(Counter(row["domain"] for row in rows)),
               "stats": dict(stats), "exclusion_inputs": evidence,
               "exclusion_rule": "Q0 question-only exact and bidirectional SequenceMatcher >=0.88 on numeric-masked templates",
               "quarantine": quarantine, "over_6000_reference_chars": sum(len(row["problem"] + row["answer"]) > 5800 for row in rows),
               "independent_mathematical_verification": False}
    (args.output / "source-audit.json").write_bytes(json_bytes(summary) + b"\n")
    print(json.dumps({key: summary[key] for key in ("records", "records_sha256", "sources", "stats", "over_6000_reference_chars")}, indent=2))


if __name__ == "__main__":
    main()
