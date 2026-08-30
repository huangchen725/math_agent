"""Create and resolve blinded A/B review packets for proof or semantic answers."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import secrets
from pathlib import Path
from typing import Any

from ..data.audit_dataset import load_jsonl
from ..io_utils import (
    configure_utf8_stdout,
    file_sha256,
    read_json_object,
    read_jsonl_objects,
    write_json,
    write_jsonl,
)


_SAFE_INDEX = re.compile(r"[A-Za-z0-9_-]{1,128}")
_REVIEW_STATUSES = {"correct", "wrong", "unknown", "no_answer"}
_MAX_RESPONSE_CHARS = 50_000


def _safe_idx(value: object) -> str:
    idx = str(value)
    if not _SAFE_INDEX.fullmatch(idx):
        raise ValueError(f"unsafe idx: {idx!r}")
    return idx


def _load_response(output_dir: Path, idx: str) -> str:
    path = output_dir / f"{idx}.json"
    if not path.is_file():
        return "[MISSING OUTPUT]"
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return f"[INVALID OUTPUT: {type(exc).__name__}]"
    if not isinstance(record, dict) or record.get("status") != "success":
        return "[UNSUCCESSFUL OUTPUT]"
    response = str(record.get("final_response", "")).strip()
    return response[:_MAX_RESPONSE_CHARS] if response else "[EMPTY OUTPUT]"


def create_review_packet(
    dataset: list[dict[str, Any]],
    baseline_output_dir: Path,
    candidate_output_dir: Path,
    *,
    blinding_secret: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    secret = blinding_secret or secrets.token_hex(32)
    if not secret:
        raise ValueError("blinding_secret must not be empty")
    packet: list[dict[str, Any]] = []
    mappings: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for position, item in enumerate(dataset):
        idx = _safe_idx(item.get("idx", position))
        if idx in seen:
            raise ValueError(f"duplicate idx: {idx}")
        seen.add(idx)
        baseline_response = _load_response(baseline_output_dir, idx)
        candidate_response = _load_response(candidate_output_dir, idx)
        assignment = hmac.new(
            secret.encode("utf-8"),
            idx.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        swap = bool(assignment[0] & 1)
        if swap:
            response_a, response_b = candidate_response, baseline_response
            mapping = {"a": "candidate", "b": "baseline"}
        else:
            response_a, response_b = baseline_response, candidate_response
            mapping = {"a": "baseline", "b": "candidate"}
        mappings[idx] = mapping
        packet.append(
            {
                "idx": idx,
                "problem": str(item["problem"]),
                "reference_answer": str(item.get("answer", "")),
                "reference_solution": str(item.get("reference_solution", "")),
                "rubric": str(
                    item.get(
                        "rubric",
                        "Judge the mathematical conclusion and the supporting reasoning.",
                    )
                ),
                "response_a": response_a,
                "response_b": response_b,
                "a_status": "",
                "b_status": "",
                "reviewer_id": "",
                "blind": True,
            }
        )
    key = {
        "schema_version": 1,
        "items": len(packet),
        "assignment_fingerprint": hashlib.sha256(secret.encode("utf-8")).hexdigest(),
        "mappings": mappings,
    }
    return packet, key


def _load_completed_review(path: Path) -> list[dict[str, Any]]:
    return read_jsonl_objects(path)


def resolve_review(
    completed: list[dict[str, Any]],
    key: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    mappings = key.get("mappings")
    if not isinstance(mappings, dict):
        raise ValueError("review key has no mappings object")
    baseline: list[dict[str, Any]] = []
    candidate: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in completed:
        idx = _safe_idx(row.get("idx"))
        if idx in seen:
            raise ValueError(f"duplicate completed review idx: {idx}")
        seen.add(idx)
        mapping = mappings.get(idx)
        if not isinstance(mapping, dict) or set(mapping) != {"a", "b"}:
            raise ValueError(f"idx {idx!r} does not match the review key")
        if row.get("blind") is not True:
            raise ValueError(f"idx {idx!r} is not marked as blind review")
        reviewer_id = str(row.get("reviewer_id", "")).strip()
        if not reviewer_id:
            raise ValueError(f"idx {idx!r} has no reviewer_id")
        for label in ("a", "b"):
            status = str(row.get(f"{label}_status", ""))
            if status not in _REVIEW_STATUSES:
                raise ValueError(f"idx {idx!r} has invalid {label}_status: {status!r}")
            adjudication = {
                "idx": idx,
                "status": status,
                "reviewer_id": reviewer_id,
                "blind": True,
            }
            score = row.get(f"{label}_score")
            if score is not None:
                if not isinstance(score, (int, float)) or not 0 <= float(score) <= 10:
                    raise ValueError(f"idx {idx!r} has invalid {label}_score")
                adjudication["score"] = float(score)
            target = mapping[label]
            if target == "baseline":
                baseline.append(adjudication)
            elif target == "candidate":
                candidate.append(adjudication)
            else:
                raise ValueError(f"idx {idx!r} has invalid key target: {target!r}")
    expected = set(str(idx) for idx in mappings)
    if seen != expected:
        missing = sorted(expected - seen)
        extra = sorted(seen - expected)
        raise ValueError(f"review/key idx mismatch; missing={missing[:10]}, extra={extra[:10]}")
    baseline.sort(key=lambda item: item["idx"])
    candidate.sort(key=lambda item: item["idx"])
    return baseline, candidate


def _create(args: argparse.Namespace) -> None:
    dataset = load_jsonl(args.dataset)
    packet, key = create_review_packet(
        dataset,
        args.baseline_output_dir,
        args.candidate_output_dir,
    )
    key["dataset_sha256"] = file_sha256(args.dataset)
    write_jsonl(args.packet, packet)
    write_json(args.key, key)
    print(json.dumps({"items": len(packet), "packet": str(args.packet)}, ensure_ascii=False))


def _resolve(args: argparse.Namespace) -> None:
    completed = _load_completed_review(args.completed)
    key = read_json_object(args.key)
    baseline, candidate = resolve_review(completed, key)
    write_jsonl(args.baseline_adjudications, baseline)
    write_jsonl(args.candidate_adjudications, candidate)
    print(json.dumps({"items": len(baseline), "status": "resolved"}, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a blinded review packet and secret key")
    create.add_argument("dataset", type=Path)
    create.add_argument("baseline_output_dir", type=Path)
    create.add_argument("candidate_output_dir", type=Path)
    create.add_argument("--packet", type=Path, required=True)
    create.add_argument("--key", type=Path, required=True)
    create.set_defaults(handler=_create)

    resolve = subparsers.add_parser("resolve", help="Resolve completed A/B labels into run adjudications")
    resolve.add_argument("completed", type=Path)
    resolve.add_argument("key", type=Path)
    resolve.add_argument("--baseline-adjudications", type=Path, required=True)
    resolve.add_argument("--candidate-adjudications", type=Path, required=True)
    resolve.set_defaults(handler=_resolve)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    configure_utf8_stdout()
    args.handler(args)


if __name__ == "__main__":
    main()
