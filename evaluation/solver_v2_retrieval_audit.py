"""Build answer-free method references from already acquired licensed sources.

No network, model client, or evaluation labels are read; exercise/answer nodes
are not extracted. Only complete method/theory statements are admitted; source pairing is not a
claim of independent mathematical verification.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from evaluation.xh_answer_sources import (
    _UNRESOLVED_TEX, _XML_BAD, clean_tex, dmoi_macros, render_xml,
    strip_tex_comments,
)

_KINDS = {"theorem", "definition", "lemma", "corollary", "proposition", "algorithm", "assemblage"}
_TEX_BLOCK = re.compile(
    r"\\begin\{(theorem|definition|lemma|corollary|proposition)\}"
    r"(?:\[([^\]]*)\])?(.*?)\\end\{\1\}", re.S)
_CONTEXT = re.compile(
    r"\b(?:above|previous|preceding|following|this|the given) "
    r"(?:equation|system|example|figure|table|lemma|theorem|matrix|diagram)\b"
    r"|\bas (?:above|before|defined)\b", re.I)


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _qualified(body):
    return (80 <= len(body) <= 2600 and body.count("{") == body.count("}")
            and not _UNRESOLVED_TEX.search(body) and not _CONTEXT.search(body)
            and not any(ord(c) < 32 and c not in "\n\r\t" for c in body))


def _diffy_presentation(text):
    # These presentation-only source macros are explicitly defined in the
    # pinned diffyqssetup.sty: box decoration, index decoration, page penalty.
    text = re.sub(r"\\(?:mybxbg|myindex)\b", "", text)
    text = re.sub(r"\\avoidbreak\b", "", text)
    return clean_tex(text)


def extract_methods(source_root: Path):
    cards, stats, sources = [], Counter(), []
    for source in ("diffyqs", "dmoi3"):
        root = source_root / source
        provenance = json.loads((root / "provenance.json").read_bytes())
        license_path = root / ("LICENSE.md" if source == "diffyqs" else "LICENSE")
        license_raw = license_path.read_bytes()
        marker = b"Attribution-Share Alike 4.0" if source == "diffyqs" else b"Attribution-ShareAlike 4.0"
        if marker not in license_raw:
            raise ValueError("unapproved source license")
        sources.append({"source": source, "revision": provenance["revision"],
                        "provenance_sha256": sha256((root / "provenance.json").read_bytes()).hexdigest(),
                        "license_sha256": sha256(license_raw).hexdigest()})
        for entry in provenance["files"]:
            name = entry["path"]
            if source == "diffyqs" and not (name.startswith(("ch-", "ap-")) and name.endswith(".tex")):
                continue
            if source == "dmoi3" and not name.endswith(".ptx"):
                continue
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()):
                raise ValueError("source path containment")
            raw = path.read_bytes()
            if sha256(raw).hexdigest() != entry["sha256"]:
                raise ValueError("source integrity mismatch")
            candidates = []
            if source == "diffyqs":
                text = strip_tex_comments(raw.decode("utf-8"))
                for match in _TEX_BLOCK.finditer(text):
                    prefix = text[:match.start()]
                    if any(prefix.rfind(r"\begin{" + kind + "}") > prefix.rfind(r"\end{" + kind + "}")
                           for kind in ("example", "exercise")):
                        continue
                    body = re.sub(r"\\index\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", match[3])
                    title = clean_tex(match[2] or "")
                    if _UNRESOLVED_TEX.search(title):
                        title = ""
                    candidates.append((match[1], title, _diffy_presentation(body),
                                       str(text.count("\n", 0, match.start()) + 1)))
            else:
                if b"<!ENTITY" in raw or b"<!DOCTYPE" in raw:
                    raise ValueError("unsupported XML declaration")
                tree = ET.fromstring(raw)
                # Walk only non-example/exercise ancestry; no exercise answers
                # enter the independent route's method material.
                def walk(node):
                    if node.tag in {"example", "exercise", "solution", "answer", "proof"}:
                        return
                    if node.tag in _KINDS:
                        body_node = node.find("statement")
                        if body_node is None:
                            body_node = node
                        if not any(child.tag.split("}")[-1] in _XML_BAD | {"example", "exercise", "solution", "answer", "proof"}
                                   for child in body_node.iter()):
                            title = node.find("title")
                            body = dmoi_macros(re.sub(r"\s+", " ", render_xml(body_node)).strip())
                            candidates.append((node.tag, "" if title is None else "".join(title.itertext()), body,
                                               node.get("{http://www.w3.org/XML/1998/namespace}id") or node.get("permid") or "statement"))
                        return
                    for child in node:
                        walk(child)
                walk(tree)
            for kind, title, body, locator in candidates:
                stats["source_statements"] += 1
                # The source shorthand omits the connectedness needed for its
                # Brooks exception classification. Do not silently repair it.
                if ("Brooks" in title or title in {
                        "Euler Paths and Circuits", "The Division Algorithm", "Finite Differences",
                        "The Divisibility Relation", "Characteristic Root Technique for Repeated Roots",
                        "Ratio and root tests for power series"}):
                    stats["source_qualification_quarantined"] += 1
                    continue
                if not _qualified(body):
                    stats["context_or_bounds_excluded"] += 1
                    continue
                identity = source + "-" + sha256((name + "#" + locator + body).encode()).hexdigest()[:24]
                cards.append({"id": identity, "kind": kind, "title": (title or name.rsplit("/", 1)[-1] + " " + kind)[:160],
                              "text": body, "source": "Jiří Lebl, Notes on Diffy Qs" if source == "diffyqs" else "Oscar Levin, Discrete Mathematics: An Open Introduction",
                              "source_url": entry["url"], "source_revision": provenance["revision"],
                              "source_sha256": entry["sha256"], "license": "CC-BY-SA-4.0", "locator": locator,
                              "conditions": ("Graph statements use the source convention of finite simple undirected graphs unless explicitly stated otherwise. " if source == "dmoi3" and "graph" in body.lower() else "") + "All hypotheses and quantifiers in the full source statement must hold; applicability to the new question is unproved.",
                              "caveat": "Source statement, not an answer to the new question or an independent proof. Check domain, nonzero denominators, dimensions, boundaries, and exceptional cases."})
    unique = {}
    for row in sorted(cards, key=lambda row: row["id"]):
        unique.setdefault(row["text"], row)
    stats["duplicate_statements_excluded"] = len(cards) - len(unique)
    cards = sorted(unique.values(), key=lambda row: row["id"])
    return cards, {"sources": sources, "stats": dict(stats), "records": len(cards),
                   "kinds": dict(Counter(row["kind"] for row in cards)),
                   "source_counts": dict(Counter(row["source"] for row in cards)),
                   "evidence": "Complete source statements with structural/context filters; not independent math or retrieval accuracy verification."}


def build(source_root: Path, output: Path):
    if output.exists():
        raise ValueError("destination must be new")
    cards, report = extract_methods(source_root)
    if not cards:
        raise ValueError("no qualified methods")
    output.mkdir(parents=True)
    raw = _bytes(cards)
    (output / "cards.json").write_bytes(raw)
    report["cards_sha256"] = sha256(raw).hexdigest()
    report["builder_sha256"] = sha256(Path(__file__).read_bytes()).hexdigest()
    (output / "manifest.json").write_bytes(_bytes(report))
    for source, filename in (("diffyqs", "LICENSE.md"), ("dmoi3", "LICENSE")):
        (output / (source + "-LICENSE.txt")).write_bytes((source_root / source / filename).read_bytes())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(build(args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
