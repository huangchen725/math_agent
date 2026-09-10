"""Offline dataset freezing, provenance binding, paired scoring and blind review."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from dataclasses import asdict
from difflib import SequenceMatcher
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import tempfile

from evaluation.audit_dataset import (ReferenceProblem, default_references, load_jsonl, normalize_problem,
                                      normalize_template, _match_problem)
from evaluation.score_run import score_run, STATUSES

SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
VERDICTS = {"correct", "wrong", "unknown", "no_answer"}


def near_template(left, right):
    matcher = SequenceMatcher(None, left, right)
    # SequenceMatcher.ratio can be asymmetric; split isolation must not depend on order.
    return matcher.quick_ratio() >= 0.88 and (
        matcher.ratio() >= 0.88 or SequenceMatcher(None, right, left).ratio() >= 0.88)


def _packed_template_counts(counts):
    """Encode bounded character counts in disjoint unary bit fields.

    AND plus bit_count is the exact multiset intersection, not a hash. Large
    alphabets/counts retain the original Counter path before any large shift.
    """
    maxima = {}
    for row in counts:
        for char, count in row.items():
            maxima[char] = max(count, maxima.get(char, 0))
    offsets, span = {}, 0
    for char, width in maxima.items():
        offsets[char] = span
        span += width
    if span > 65536:
        return None
    return [sum(((1 << count) - 1) << offsets[char]
                for char, count in row.items()) for row in counts]


def _has_near_template_overlap(templates):
    """Reject impossible pairs before rebuilding SequenceMatcher's histograms.

    quick_ratio is exactly twice the multiset intersection over total length.
    Reuse only these per-validation histograms, then retain the original final
    bidirectional predicate. No file, question or verdict survives this call.
    """
    features = [(len(text), Counter(text)) for text in templates]
    packed = _packed_template_counts([counts for _, counts in features])
    for index, left in enumerate(templates):
        left_length, left_counts = features[index]
        for other in range(index + 1, len(templates)):
            right_length, right_counts = features[other]
            total = left_length + right_length
            matches = ((packed[index] & packed[other]).bit_count() if packed is not None
                       else sum(min(count, right_counts.get(char, 0)) for char, count in left_counts.items()))
            upper = 2.0 * matches / total if total else 1.0
            if upper >= 0.88 and near_template(left, templates[other]):
                return True
    return False


def development_references():
    refs = default_references()
    root = Path(__file__).resolve().parents[1]
    for path in sorted((root/"tests").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.Constant) and type(node.value) is str and 8 <= len(node.value) <= 20_000:
                refs.append(ReferenceProblem("test_literal:"+path.name, "", node.value))
    return refs


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def scoring_hash():
    root = Path(__file__).resolve().parents[1]
    names = ("evaluation/judge.py", "evaluation/score_run.py", "evaluation/q0_pipeline.py",
             "answer_equivalence.py", "deterministic_verifier.py", "math_tools.py", "tool_executor.py")
    return digest({name: sha256((root/name).read_bytes()).hexdigest() for name in names})


def validate_records(records):
    seen = set()
    for row in records:
        if type(row) is not dict:
            raise ValueError("record must be an object")
        idx = row.get("idx")
        if type(idx) is not str or not SAFE_ID.fullmatch(idx) or idx in seen:
            raise ValueError("unsafe or duplicate idx")
        seen.add(idx)
        for key in ("problem", "answer", "subject", "level", "task_type", "source", "license"):
            value = row.get(key)
            if type(value) is not str or not value.strip() or len(value) > 100_000:
                raise ValueError("missing or excessive " + key)
            if value.casefold() in {"unknown", "tbd", "<missing>"}:
                raise ValueError("unresolved provenance: " + key)
        if len(row["problem"]) > 20_000:
            raise ValueError("problem exceeds runtime input contract")


def freeze_records(records, *, per_subject=24, seed="q0-20260906", references=None):
    validate_records(records)
    if type(per_subject) is not int or per_subject < 2 or per_subject % 2:
        raise ValueError("per_subject must be positive and even")
    references = development_references() if references is None else references
    groups = defaultdict(list)
    excluded = Counter()
    templates = set()
    # Select without opening/inspecting answer contents or choosing by model success.
    for row in sorted(records, key=lambda r: digest([seed, r["idx"]])):
        template = normalize_template(row["problem"])
        if template in templates:
            excluded["duplicate_template"] += 1
            continue
        if any(near_template(template, previous) for previous in templates):
            excluded["near_template"] += 1
            continue
        if _match_problem(row["problem"], references, 0.88):
            excluded["reference_overlap"] += 1
            continue
        templates.add(template)
        groups[row["subject"]].append(row)
    selected = []
    for subject, rows in sorted(groups.items()):
        if len(rows) < per_subject:
            raise ValueError("insufficient eligible rows for " + subject)
        for i, row in enumerate(rows[:per_subject]):
            selected.append({**row, "split": "dev" if i < per_subject//2 else "test",
                             "problem_sha256": digest(normalize_problem(row["problem"]))})
    if not selected:
        raise ValueError("no eligible records")
    return selected, {"excluded": dict(excluded), "seed": seed,
        "per_subject": per_subject, "subjects": sorted(groups),
        "reference_sha256": digest([asdict(r) for r in references]),
        "source_records_sha256": digest(records)}


def write_bundle(output: Path, records, selection):
    if output.exists():
        raise ValueError("refusing to overwrite frozen bundle")
    validate_records(records)
    if any(r.get("split") not in {"dev", "test"} for r in records):
        raise ValueError("invalid split")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="q0-stage-", dir=output.parent))
    try:
        manifest = {"schema_version": 1, "selection": selection, "files": {},
            "total": len(records), "subject_counts": dict(Counter(r["subject"] for r in records)),
            "evidence": "dataset preparation only; no model baseline or human review yet",
            "blindness": "development holdout; public data, not cryptographic or pretraining blind"}
        for split in ("dev", "test"):
            subset = [r for r in records if r["split"] == split]
            if not subset:
                raise ValueError("both splits required")
            for kind, rows in (("labels", subset), ("input", [
                {"idx": r["idx"], "problem": r["problem"]} for r in subset])):
                name = f"{split}.{kind}.jsonl"
                data = ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows)+"\n").encode()
                (stage / name).write_bytes(data)
                manifest["files"][name] = sha256(data).hexdigest()
        manifest["dataset_sha256"] = digest(manifest["files"])
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        verify_bundle(stage)
        stage.rename(output)
    finally:
        if stage.exists():
            if stage.resolve().parent != output.parent.resolve() or not stage.name.startswith("q0-stage-"):
                raise ValueError("unsafe staging cleanup")
            shutil.rmtree(stage)
    return manifest


def verify_bundle(bundle: Path):
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    expected = {f"{s}.{k}.jsonl" for s in ("dev", "test") for k in ("input", "labels")}
    if set(manifest["files"]) != expected or digest(manifest["files"]) != manifest["dataset_sha256"]:
        raise ValueError("invalid manifest")
    all_rows = []
    for name, hash_value in manifest["files"].items():
        if (bundle/name).resolve().parent != bundle.resolve():
            raise ValueError("frozen file escapes bundle")
        if sha256((bundle/name).read_bytes()).hexdigest() != hash_value:
            raise ValueError("frozen file changed: " + name)
    for split in ("dev", "test"):
        labels = load_jsonl(bundle/f"{split}.labels.jsonl")
        inputs = load_jsonl(bundle/f"{split}.input.jsonl")
        if inputs != [{"idx": r["idx"], "problem": r["problem"]} for r in labels]:
            raise ValueError("input/labels mismatch or answer leakage")
        if any(r.get("split") != split for r in labels):
            raise ValueError("split mismatch")
        all_rows.extend(labels)
    validate_records(all_rows)
    if len(all_rows) != manifest["total"] or len({normalize_template(r["problem"]) for r in all_rows}) != len(all_rows):
        raise ValueError("count or template overlap")
    templates = [normalize_template(row["problem"]) for row in all_rows]
    if _has_near_template_overlap(templates):
        raise ValueError("near template overlap")
    return manifest


def score_bound_run(bundle, split, run_dir, *, model, code_sha, config, execution="real", local_tools=False):
    if split not in {"dev", "test"} or execution not in {"real", "fixture"}:
        raise ValueError("invalid run kind")
    manifest = verify_bundle(bundle)
    if not model or not re.fullmatch(r"[a-f0-9]{40,64}", code_sha) or type(config) is not dict:
        raise ValueError("unbound run provenance")
    rows = load_jsonl(bundle/f"{split}.labels.jsonl")
    summary_file = run_dir/"_run"/"run_summary.json"
    summary = json.loads(summary_file.read_text(encoding="utf-8-sig"))
    if summary.get("status") != "complete" or summary.get("completed_items") != len(rows):
        raise ValueError("incomplete run; use raw score_run for partial diagnosis")
    expected_input = manifest["files"][f"{split}.input.jsonl"]
    # New Q1 runner binds before execution; legacy main runs need explicit provenance conversion.
    if summary.get("input_sha256") != expected_input or summary.get("model") != model:
        raise ValueError("run model/input provenance mismatch")
    if summary.get("code_sha") != code_sha or summary.get("config") != config or summary.get("execution") != execution:
        raise ValueError("run code/config/execution provenance mismatch")
    if summary.get("local_tools") is not local_tools:
        raise ValueError("tool capability provenance mismatch")
    outputs = summary.get("output_files_sha256", {})
    if set(outputs) != {r["idx"]+".json" for r in rows}:
        raise ValueError("missing checkpoint manifest")
    for name, expected in outputs.items():
        if (run_dir/name).resolve().parent != run_dir.resolve() or sha256((run_dir/name).read_bytes()).hexdigest() != expected:
            raise ValueError("checkpoint changed or escaped")
    scored = score_run(rows, run_dir)
    scored["provenance"] = {"dataset_sha256": manifest["dataset_sha256"], "split": split,
        "model": model, "code_sha": code_sha, "config": config, "execution": execution,
        "input_sha256": expected_input, "local_tools": local_tools}
    scored["provenance"]["output_sha256"] = digest(outputs)
    scored["provenance"]["scoring_sha256"] = scoring_hash()
    return scored


def paired_comparison(before, after):
    for key in ("dataset_sha256", "split", "model", "execution", "local_tools", "scoring_sha256"):
        if before["provenance"].get(key) != after["provenance"].get(key):
            raise ValueError("incomparable runs: " + key)
    def keyed(report):
        rows = report["results"]
        if any(r.get("status") not in STATUSES for r in rows):
            raise ValueError("invalid paired verdict")
        keys = [str(r["idx"]) for r in rows]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate paired index")
        return dict(zip(keys, rows))
    left, right = keyed(before), keyed(after)
    if not left or set(left) != set(right):
        raise ValueError("paired index mismatch")
    transitions = Counter()
    for idx in left:
        a, b = left[idx], right[idx]
        if a["expected"] != b["expected"]:
            raise ValueError("paired reference mismatch")
        transitions[a["status"] + "->" + b["status"]] += 1
    gains = sum(a["status"] != "correct" and right[i]["status"] == "correct" for i,a in left.items())
    losses = sum(a["status"] == "correct" and right[i]["status"] != "correct" for i,a in left.items())
    return {"total": len(left), "gains": gains, "losses": losses,
        "accuracy_delta": (gains-losses)/len(left), "transitions": dict(transitions),
        "before_usage": before["summary"]["usage"], "after_usage": after["summary"]["usage"],
        "claim": "fixture diagnostics only" if before["provenance"]["execution"] == "fixture" else
                 "single paired observation; unknowns and repeated-run uncertainty remain"}


def review_packet(rows, report, *, salt):
    by_idx = {str(r["idx"]): r for r in rows}
    result_ids = [str(r["idx"]) for r in report["results"]]
    if not result_ids or len(by_idx) != len(rows) or len(set(result_ids)) != len(result_ids):
        raise ValueError("empty or duplicate review items")
    packet = []
    for result in report["results"]:
        row = by_idx[str(result["idx"])]
        packet.append({"review_id": digest([salt, str(row["idx"])]),
            "problem": row["problem"], "reference": row["answer"], "actual": result["actual"],
            "solution": result.get("final_response", "")})
    packet.sort(key=lambda r: r["review_id"])
    return {"packet_sha256": digest(packet), "items": packet}


def reconcile_reviews(packet, first, second):
    if not first.get("reviewer") or not second.get("reviewer") or first["reviewer"] == second["reviewer"]:
        raise ValueError("two distinct reviewers required")
    ids = {r["review_id"] for r in packet["items"]}
    if not ids or len(ids) != len(packet["items"]):
        raise ValueError("empty or duplicate packet")
    if digest(packet["items"]) != packet["packet_sha256"]:
        raise ValueError("packet changed")
    for review in (first, second):
        if review.get("packet_sha256") != packet["packet_sha256"] or set(review["decisions"]) != ids:
            raise ValueError("stale or incomplete review")
        if any(v not in VERDICTS for v in review["decisions"].values()):
            raise ValueError("invalid human verdict")
    return {idx: {"status": first["decisions"][idx] if first["decisions"][idx] == second["decisions"][idx] else "unknown",
                  "disagreement": first["decisions"][idx] != second["decisions"][idx]} for idx in sorted(ids)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="mode", required=True)
    freeze = modes.add_parser("freeze")
    freeze.add_argument("source", type=Path)
    freeze.add_argument("output", type=Path)
    freeze.add_argument("--per-subject", type=int, default=24)
    verify = modes.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    score = modes.add_parser("score")
    score.add_argument("bundle", type=Path)
    score.add_argument("run", type=Path)
    score.add_argument("plan", type=Path)
    score.add_argument("--variant", required=True)
    score.add_argument("--execution", choices=("real", "fixture"), default="real")
    pair = modes.add_parser("compare")
    pair.add_argument("before", type=Path)
    pair.add_argument("after", type=Path)
    packet = modes.add_parser("review-packet")
    packet.add_argument("bundle", type=Path)
    packet.add_argument("report", type=Path)
    packet.add_argument("--salt", required=True)
    merge = modes.add_parser("review-merge")
    merge.add_argument("packet", type=Path)
    merge.add_argument("first", type=Path)
    merge.add_argument("second", type=Path)
    for mode in (score, pair, packet, merge):
        mode.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    def read(path):
        return json.loads(path.read_text(encoding="utf-8-sig"))
    if args.mode == "freeze":
        rows, selection = freeze_records(load_jsonl(args.source), per_subject=args.per_subject)
        result = write_bundle(args.output, rows, selection)
        verify_bundle(args.output)
    elif args.mode == "verify":
        result = verify_bundle(args.bundle)
    elif args.mode == "score":
        plan = read(args.plan)
        result = score_bound_run(args.bundle, plan["split"], args.run, model=plan["model"],
            code_sha=plan["code_sha"], config=plan["variants"][args.variant], execution=args.execution, local_tools=plan["local_tools"])
    elif args.mode == "compare":
        result = paired_comparison(read(args.before), read(args.after))
    elif args.mode == "review-packet":
        report = read(args.report)
        manifest = verify_bundle(args.bundle)
        if report["provenance"]["dataset_sha256"] != manifest["dataset_sha256"]:
            raise ValueError("review dataset mismatch")
        split = report["provenance"]["split"]
        if split not in {"dev", "test"}:
            raise ValueError("review split")
        result = review_packet(load_jsonl(args.bundle/f"{split}.labels.jsonl"), report, salt=args.salt)
    else:
        result = reconcile_reviews(read(args.packet), read(args.first), read(args.second))
    if args.mode not in {"freeze", "verify"}:
        if args.output.exists():
            raise ValueError("refusing to overwrite evidence")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print("offline artifact written")
    else:
        print(json.dumps({"total": result["total"], "dataset_sha256": result["dataset_sha256"],
                          "subjects": result["subject_counts"]}))


if __name__ == "__main__":
    main()
