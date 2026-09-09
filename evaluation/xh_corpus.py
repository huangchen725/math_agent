"""Reproducible public-source card extraction; no downloads and no model calls."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

REVISION = "df2262e089a02651c127f1dd12649c4622ee1383"
_BLOCK = re.compile(r"\\begin\{(definition|theorem|lemma|corollary|proposition|example)\}(.*?)\\end\{\1\}", re.S)
_MACROS = {"Re": r"\mathbb{R}", "polyspace": r"\mathcal{P}", "real": r"\mathbb{R}"}
# Source-level quality exclusion, not a query/answer blacklist. Opposite nonzero
# vectors are parallel but their dot product is the negative product of lengths.
_QUARANTINED_LABELS = {"co:VectorsOrthogonalIffDoTProductZero"}


def clean_tex(text):
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)
    text = re.sub(r"\\(?:label|index)\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "", text)
    for name, value in _MACROS.items():
        text = re.sub(r"\\" + name + r"(?![A-Za-z])", lambda _: value, text)
    text = text.replace(r"\definend", r"\textbf")
    text = re.sub(r"\\begin\{mat\}(?:\[[clr]\])?", r"\\begin{pmatrix}", text)
    text = text.replace(r"\end{mat}", r"\end{pmatrix}")
    text = re.sub(r"\\colvec(?:\[[clr]\])?\{([^{}]*)\}", lambda m: r"\begin{pmatrix}" + m[1] + r"\end{pmatrix}", text)
    text = re.sub(r"\\nbyn\{([^{}]+)\}", lambda m: m[1] + r"\times " + m[1], text)
    text = re.sub(r"\\sequence\{([^{}]*)\}", lambda m: r"\langle " + m[1] + r"\rangle", text)
    text = text.replace("~", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def extract(source: Path):
    provenance = json.loads((source / "provenance.json").read_text(encoding="utf-8"))
    if provenance["revision"] != REVISION or provenance["license_choice"] != "CC-BY-SA-2.5":
        raise ValueError("unapproved corpus source")
    hashes = {r["path"]: r["sha256"] for r in provenance["files"]}
    all_cards, excluded = [], {}
    # Theory/examples only: exercises and answers are reserved for independent query review.
    for name in sorted(hashes):
        if not re.fullmatch(r"src/(gr/gr[1-4]|vs/vs[1-3]|map/map[1-6]|det/det[1-4])\.tex", name):
            continue
        raw = (source / name).read_bytes()
        if sha256(raw).hexdigest() != hashes[name]:
            raise ValueError("source fingerprint changed")
        text = raw.decode("utf-8")
        # Ignore commented environments without changing the source line numbers.
        uncommented = re.sub(r"(?<!\\)%[^\n]*", "", text)
        for ordinal, match in enumerate(_BLOCK.finditer(uncommented)):
            prefix = uncommented[:match.start()]
            if prefix.rfind(r"\begin{exercises}") > prefix.rfind(r"\end{exercises}"):
                continue
            label = re.search(r"\\label\{([^{}]+)\}", match[2])
            if label and label[1] in _QUARANTINED_LABELS:
                excluded["source_math_qualification"] = excluded.get("source_math_qualification", 0) + 1
                continue
            body = clean_tex(match[2])
            if (not 80 <= len(body) <= 2300 or re.search(r"\\(?:ref|eqref|pageref|nearby[a-z]+|includegraphics|input|include|grstep|cite|picture|asy|pspicture|xymatrix|jhankel)\b", body)
                    or re.search(r"(?:previous|preceding|above|following) (?:example|theorem|figure|table|lemma)", body, re.I)):
                excluded["context_or_size"] = excluded.get("context_or_size", 0) + 1
                continue
            if body.count("{") != body.count("}"):
                excluded["braces"] = excluded.get("braces", 0) + 1
                continue
            chapter = {"gr": "Linear systems", "vs": "Vector spaces", "map": "Linear maps", "det": "Determinants"}[name.split("/")[1]]
            title = chapter + ": " + (label[1] if label else match[1] + " " + str(ordinal + 1))
            all_cards.append({"id": name.replace("/", "-").replace(".tex", "") + "-" + str(ordinal),
                "title": title[:160], "text": body, "question": body,
                "source": "Jim Hefferon, Linear Algebra / " + name,
                "source_revision": REVISION, "license": "CC-BY-SA-2.5", "source_sha256": hashes[name],
                "line": uncommented.count("\n", 0, match.start()) + 1})
    # Balanced deterministic coverage across source sections; never pick by evaluation answers.
    groups = {}
    for card in all_cards:
        groups.setdefault(card["source"], []).append(card)
    selected = []
    for i in range(max(map(len, groups.values()), default=0)):
        for name in sorted(groups):
            if i < len(groups[name]):
                selected.append(groups[name][i])
    return selected[:160], {"eligible": len(all_cards), "selected": min(160, len(all_cards)), "excluded": excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    cards, report = extract(args.source)
    if len(cards) < 100:
        raise ValueError("fewer than 100 eligible complete cards")
    args.destination.mkdir(parents=True, exist_ok=False)
    raw = (json.dumps(cards, ensure_ascii=False, indent=2) + "\n").encode()
    (args.destination / "cards.json").write_bytes(raw)
    report.update({"cards_sha256": sha256(raw).hexdigest(), "revision": REVISION,
                   "extractor_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
                   "source_manifest_sha256": sha256((args.source / "provenance.json").read_bytes()).hexdigest(),
                   "evidence": "source extraction and structural checks; not retrieval or accuracy measurement"})
    # Content fingerprints must survive Windows/Linux Git checkouts.
    (args.destination / "manifest.json").write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
    notice = (args.source / "LICENSE").read_text(encoding="utf-8")
    notice = "\n".join(line.rstrip() for line in notice.splitlines()) + "\n"
    (args.destination / "LICENSE.source.txt").write_bytes(notice.encode("utf-8"))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
