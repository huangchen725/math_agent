"""Prepare reference disputes and anonymous review packets without changing scores.

This is an offline consumer of a bound replay snapshot and the original dev labels.
Packets contain neither variant names nor earlier verdicts/proofs. Two distinct
reviewers can later use q0_pipeline.reconcile_reviews; preparing a packet is not review.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path

from evaluation.audit_dataset import load_jsonl
from evaluation.q0_pipeline import review_packet, verify_bundle
from evaluation.xh202627_response_replay import digest, inside, read, verify_snapshot, write_new

CATEGORIES = {"reference_error", "domain_ambiguity", "tolerance", "term_count_ambiguity", "condition_ambiguity"}


def assemble(labels, issues, items, checkpoints, *, salt):
    if not isinstance(salt, str) or not 16 <= len(salt) <= 256:
        raise ValueError("nontrivial private review salt required")
    by_idx = {row["idx"]: row for row in labels}
    if len(by_idx) != len(labels) or not 1 <= len(issues) <= 100:
        raise ValueError("invalid labels or issue count")
    selected, catalog = set(), []
    for issue in issues:
        if (set(issue) != {"idx", "category", "basis"} or issue["idx"] not in by_idx
                or issue["idx"] in selected or issue["category"] not in CATEGORIES
                or not isinstance(issue["basis"], str) or not 1 <= len(issue["basis"]) <= 16000):
            raise ValueError("invalid or duplicate reference issue")
        selected.add(issue["idx"])
        label = by_idx[issue["idx"]]
        catalog.append({**issue, "problem": label["problem"], "reference_as_frozen": label["answer"],
                        "reference_row_sha256": digest(label), "independent_review": "pending"})
    rows, results, mapping, seen = [], [], [], set()
    for item in items:
        if item["idx"] not in selected:
            continue
        pair = (item["variant"], item["idx"])
        if pair in seen:
            raise ValueError("duplicate variant/item")
        seen.add(pair)
        checkpoint = checkpoints[pair]
        if checkpoint["idx"] != item["idx"]:
            raise ValueError("checkpoint identity mismatch")
        label = by_idx[item["idx"]]
        opaque = digest([salt, *pair])
        rows.append({"idx": opaque, "problem": label["problem"], "answer": label["answer"]})
        results.append({"idx": opaque, "actual": item["actual"], "final_response": checkpoint["final_response"]})
        mapping.append({"review_id": digest([salt, opaque]), "variant": pair[0], "idx": pair[1]})
    if {pair[1] for pair in seen} != selected:
        raise ValueError("issue lacks a completed checkpoint")
    complete = review_packet(rows, {"results": results}, salt=salt)
    final_only = review_packet(rows, {"results": [{**row, "final_response": ""} for row in results]}, salt=salt)
    return {"catalog": {"issues": catalog, "scope": "Single-assistant diagnosis; independent review pending",
                        "frozen_labels_modified": False, "automatic_scores_overridden": False},
            "packet-final": {**final_only, "view": "final_answer_only"},
            "packet-full": {**complete, "view": "delivered_full_response"},
            "private-mapping": {"items": mapping, "scope": "Keep separate from reviewers"}}


def prepare(snapshot, bundle, specification, output, *, salt):
    manifest = verify_snapshot(snapshot)
    bundle, output = Path(bundle).resolve(), Path(output).resolve()
    pilot = Path(manifest["pilot"]).resolve()
    if output.is_relative_to(pilot) or output.is_relative_to(bundle):
        raise ValueError("cannot write review artifacts into original evidence")
    frozen = verify_bundle(bundle)
    labels_path = bundle / "dev.labels.jsonl"
    if frozen["files"]["dev.input.jsonl"] != manifest["input_sha256"]:
        raise ValueError("review dataset differs from replay snapshot")
    spec = read(specification)
    if set(spec) != {"label_file_sha256", "issues"} or spec["label_file_sha256"] != frozen["files"][labels_path.name]:
        raise ValueError("reference specification is stale")
    checkpoints = {}
    for item in manifest["items"]:
        relative = f"runs/{item['variant']}-0/{item['idx']}.json"
        if relative not in manifest["files"]:
            raise ValueError("unbound review checkpoint")
        checkpoints[(item["variant"], item["idx"])] = read(inside(pilot, relative))
    artifacts = assemble(load_jsonl(labels_path), spec["issues"], manifest["items"], checkpoints, salt=salt)
    verify_snapshot(snapshot)
    verify_bundle(bundle)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in artifacts.items():
        write_new(output / (name + ".json"), value)
    provenance = {"schema_version": 1, "snapshot_sha256": digest(manifest),
        "label_file_sha256": spec["label_file_sha256"], "specification_sha256": digest(spec),
        "tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "files": {name + ".json": sha256((output / (name + ".json")).read_bytes()).hexdigest() for name in artifacts},
        "actual_api_requests": 0, "review_status": "pending_two_distinct_reviewers",
        "scores_changed": False, "reference_labels_changed": False}
    write_new(output / "provenance.json", provenance)
    return provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("specification", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--salt", required=True)
    args = parser.parse_args()
    prepare(args.snapshot, args.bundle, args.specification, args.output, salt=args.salt)
    print("Offline reference catalog and two anonymous review views prepared; review pending.")


if __name__ == "__main__":
    main()
