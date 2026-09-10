"""Reproducible offline compiler for attributed, complete public question/answers.

Run as ``python -m evaluation.xh_answer_bank --input records.jsonl --output NEW_DIR``.
No model calls, expression execution, networking, or runtime source edits occur.
The returned manifest SHA must be reviewed and pinned separately in the runtime.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from time import perf_counter
from typing import Iterable

from xh202627_corpus import (
    ANSWER_BANK_MAX_RECORD_BYTES, ANSWER_BANK_MAX_RECORDS, ANSWER_BANK_SCHEMA,
    AnswerBank, _bank_decode, answer_bank_key, answer_bank_terms, validate_answer_record,
)

BLOCK_BYTES = 512 * 1024
PAGE_BYTES = 1024 * 1024
TOPIC_POSTINGS = 24


def canonical_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode("utf-8")


def read_records(path: Path):
    """Read bounded JSONL lines; unexpected fields and invalid records fail build."""
    with path.open("rb") as stream:
        for index in range(ANSWER_BANK_MAX_RECORDS + 1):
            line = stream.readline(ANSWER_BANK_MAX_RECORD_BYTES + 1)
            if not line:
                return
            if index == ANSWER_BANK_MAX_RECORDS or len(line) > ANSWER_BANK_MAX_RECORD_BYTES:
                raise ValueError("input record capacity exceeded")
            if not line.strip():
                raise ValueError("blank input record")
            yield validate_answer_record(_bank_decode(line))


def exclusion_key(problem: str) -> str:
    """Aggressive key used ONLY to exclude development overlap, never to accept.

    Erasing formatting, case and whitespace may over-exclude. It must not be
    reused by runtime acceptance, where all mathematical distinctions survive.
    """
    return re.sub(r"[\s$\\{}]+", "", problem).casefold()


def _write_unique(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("conflicting existing artifact")
        return
    with path.open("xb") as stream:
        stream.write(raw)


def build_answer_bank(records: Iterable[dict], output: Path, *, exclude_problems=()) -> dict:
    """Build digest-bound pages with whole-question conflict quarantine.

    Identical question/answer duplicates keep the lexicographically first ID.
    Differing source answers for the same whole question quarantine ALL versions.
    This is conservative text comparison, not a semantic equivalence claim.
    """
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("output must be a new or empty directory")
    excluded = {exclusion_key(p) for p in exclude_problems}
    seen_ids = set()
    groups = defaultdict(list)
    input_count = 0
    excluded_count = 0
    for row in records:
        input_count += 1
        if input_count > ANSWER_BANK_MAX_RECORDS:
            raise ValueError("answer bank capacity exceeded")
        validate_answer_record(row)
        if row["id"] in seen_ids:
            raise ValueError("duplicate record ID")
        seen_ids.add(row["id"])
        if exclusion_key(row["problem"]) in excluded:
            excluded_count += 1
            continue
        raw = canonical_bytes(row)
        if len(raw) > ANSWER_BANK_MAX_RECORD_BYTES:
            raise ValueError("encoded answer record too large")
        identity = sha256(answer_bank_key(row["problem"]).encode("utf-8")).hexdigest()
        groups[identity].append((row, raw))

    accepted = []
    conflicts = []
    duplicates = 0
    for identity in sorted(groups):
        group = groups[identity]
        # Guard a theoretical hash collision as well as conflicting answers.
        questions = {answer_bank_key(row["problem"]) for row, _ in group}
        answers = {answer_bank_key(row["answer"]) for row, _ in group}
        if len(questions) != 1 or len(answers) != 1:
            conflicts.append({"question_sha256": identity, "ids": sorted(row["id"] for row, _ in group)})
            continue
        duplicates += len(group) - 1
        row, raw = min(group, key=lambda pair: pair[0]["id"])
        accepted.append((identity, row, raw))
    if not accepted:
        raise ValueError("no qualified unambiguous records")

    exact_pages = defaultdict(dict)
    topic_lists = defaultdict(list)
    sources = Counter()
    licenses = Counter()
    block = bytearray()
    pending = []

    def flush():
        if not pending:
            return
        raw_block = bytes(block)
        block_hash = sha256(raw_block).hexdigest()
        _write_unique(output / "records" / f"{block_hash}.jsonl", raw_block)
        for identity, row, offset, raw in pending:
            ref = [block_hash, offset, len(raw), sha256(raw).hexdigest(), identity]
            exact_pages[identity[:2]][identity] = ref
            # Sparse deterministic term postings are method retrieval only.
            # Bound the per-record vocabulary to avoid pathological expansion.
            for term in sorted(answer_bank_terms(row["problem"]), key=lambda t: (-len(t), t))[:32]:
                if len(topic_lists[term]) < TOPIC_POSTINGS:
                    topic_lists[term].append(ref)
            sources[row["source"]] += 1
            licenses[row["license"]] += 1
        block.clear()
        pending.clear()

    for identity, row, raw in accepted:
        if block and len(block) + len(raw) > BLOCK_BYTES:
            flush()
        offset = len(block)
        block.extend(raw)
        pending.append((identity, row, offset, raw))
    flush()

    topic_pages = defaultdict(dict)
    for term in sorted(topic_lists):
        bucket = sha256(term.encode("utf-8")).hexdigest()[:2]
        topic_pages[bucket][term] = topic_lists[term]
    manifests = {}
    skipped_topic_terms = 0
    for kind, pages in (("exact", exact_pages), ("topics", topic_pages)):
        manifest_pages = {}
        for bucket in sorted(pages):
            page = pages[bucket]
            raw = canonical_bytes(page)
            if len(raw) > PAGE_BYTES and kind == "topics":
                # Overflow loses optional recall, never exact identities. Keep a
                # deterministic prefix and report it instead of oversized reads.
                page = {}
                size = 3
                for term in sorted(pages[bucket]):
                    estimate = len(canonical_bytes({term: pages[bucket][term]}))
                    if size + estimate > PAGE_BYTES:
                        skipped_topic_terms += 1
                        continue
                    page[term] = pages[bucket][term]
                    size += estimate
                raw = canonical_bytes(page)
            if len(raw) > PAGE_BYTES:
                raise ValueError("index capacity exceeded; do not publish partial bank")
            _write_unique(output / kind / f"{bucket}.json", raw)
            manifest_pages[bucket] = {"sha256": sha256(raw).hexdigest(), "size": len(raw)}
        manifests[kind] = manifest_pages
    manifest = {
        "schema_version": ANSWER_BANK_SCHEMA,
        "record_count": len(accepted),
        "exact": manifests["exact"],
        "topics": manifests["topics"],
        "source_counts": dict(sorted(sources.items())),
        "license_counts": dict(sorted(licenses.items())),
    }
    raw_manifest = canonical_bytes(manifest)
    if len(raw_manifest) > 128 * 1024:
        raise ValueError("manifest capacity exceeded")
    _write_unique(output / "manifest.json", raw_manifest)
    report = {
        "schema_version": 1,
        "input_count": input_count,
        "record_count": len(accepted),
        "excluded_count": excluded_count,
        "duplicate_count": duplicates,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "skipped_topic_terms": skipped_topic_terms,
        "manifest_sha256": sha256(raw_manifest).hexdigest(),
        "source_counts": dict(sorted(sources.items())),
        "license_counts": dict(sorted(licenses.items())),
        "verification_scope": "source provenance and complete-question identity; no independent mathematical proof implied",
    }
    _write_unique(output / "build_report.json", canonical_bytes(report))
    return report


def _peak_rss_bytes() -> int:
    """Offline process metric only, no optional package/runtime dependency."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        counters = MemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
            raise OSError("offline RSS measurement failed")
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def probe_answer_bank(root: Path, expected_sha256: str, cases: list[dict]) -> dict:
    """Cold-interpreter probe. Captures metrics, never stores retrieved bodies."""
    before_rss = _peak_rss_bytes()
    latencies = []
    reads = []
    success = True
    hit_count = 0
    contexts = 0
    class MeteredBank(AnswerBank):
        def _read(self, name, digest, size, budget, **kwargs):
            reads[-1]["bytes"] += size
            reads[-1]["files"] += 1
            result = super()._read(name, digest, size, budget, **kwargs)
            reads[-1]["bodies"] = budget.bodies
            reads[-1]["postings"] = budget.postings
            return result
    for case in cases:
        reads.append({"bytes": 0, "files": 0, "bodies": 0, "postings": 0})
        start = perf_counter()
        result = MeteredBank(root, expected_sha256).material(case["problem"])
        latencies.append(perf_counter() - start)
        match = result["match"]
        hit_count += match is not None
        contexts += bool(result["context"])
        if case["expected_answer"] is None:
            success &= match is None
        else:
            success &= match is not None and match["answer"] == case["expected_answer"]
    peak_rss = _peak_rss_bytes()
    return {"success": bool(success), "case_count": len(cases), "exact_hits": hit_count,
            "reference_contexts": contexts,
            "first_query_seconds": latencies[0], "max_seconds": max(latencies),
            "p95_seconds": sorted(latencies)[max(0, (len(latencies) * 95 + 99) // 100 - 1)],
            "max_read_bytes": max(row["bytes"] for row in reads),
            "max_file_reads": max(row["files"] for row in reads),
            "max_record_bodies": max(row["bodies"] for row in reads),
            "max_postings": max(row["postings"] for row in reads),
            "base_peak_rss_bytes": before_rss, "peak_rss_bytes": peak_rss,
            "incremental_peak_rss_bytes": max(0, peak_rss - before_rss)}


def capacity_check(output: Path, count: int = 100000) -> dict:
    """Synthetic capacity evidence, entirely separate from answer accuracy."""
    if type(count) is not int or not 100000 <= count <= ANSWER_BANK_MAX_RECORDS:
        raise ValueError("capacity count must be 100000..1000000")
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("capacity output must be new or empty")
    def question(n):
        return f"Find the determinant of the matrix [[{n},2],[3,4]]."
    def rows():
        for n in range(count):
            yield {"id": f"capacity-{n}", "problem": question(n), "answer": str(4*n - 6),
                   "solution": "Use ad-bc for a 2 by 2 determinant.",
                   "source": "Project-authored synthetic capacity fixture",
                   "source_url": "https://example.org/capacity-fixture", "license": "CC0-1.0",
                   "source_revision": "capacity-v1", "source_sha256": "1" * 64,
                   "split": "synthetic_capacity_only", "domain": "linear_algebra",
                   "trust": "math_verified", "metadata": {"not_accuracy_evidence": True}}
    start = perf_counter()
    report = build_answer_bank(rows(), output / "bank")
    build_seconds = perf_counter() - start
    cases = []
    for n in [i * (count - 1) // 19 for i in range(20)]:
        cases.append({"problem": question(n), "expected_answer": str(4*n - 6)})
        cases.append({"problem": question(n).replace("[3,4]", "[3,5]"), "expected_answer": None})
    cases_path = output / "probe_cases.json"
    _write_unique(cases_path, canonical_bytes(cases))
    command = [sys.executable, "-m", "evaluation.xh_answer_bank", "--probe", "--output", str(output / "bank"),
               "--input", str(cases_path), "--manifest-sha", report["manifest_sha256"]]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(3)]
    results = []
    try:
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            if process.returncode or stderr:
                raise ValueError("capacity worker failed")
            results.append(json.loads(stdout))
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    result = {"record_count": report["record_count"], "build_seconds": build_seconds,
              "manifest_sha256": report["manifest_sha256"], "processes": results,
              "success": all(row["success"] and row["max_read_bytes"] <= 4*1024*1024
                             and row["max_record_bodies"] <= 8 and row["max_postings"] <= 4096
                             and row["p95_seconds"] <= 1.0
                             and row["incremental_peak_rss_bytes"] <= 128*1024*1024 for row in results),
              "scope": "synthetic capacity; three independent interpreters concurrently; not mathematical accuracy or cold OS cache evidence"}
    _write_unique(output / "capacity_report.json", canonical_bytes(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capacity-check", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--manifest-sha")
    parser.add_argument("--exclude", type=Path, action="append", default=[],
                        help="JSONL files whose problem texts must be excluded")
    args = parser.parse_args()
    if args.capacity_check:
        print(json.dumps(capacity_check(args.output), ensure_ascii=False, sort_keys=True))
        return
    if args.probe:
        with args.input.open("r", encoding="utf-8") as stream:
            cases = json.load(stream)
        print(json.dumps(probe_answer_bank(args.output, args.manifest_sha, cases), sort_keys=True))
        return
    if args.input is None:
        parser.error("--input is required when building")
    excluded = []
    for path in args.exclude:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                problem = row.get("problem")
                if type(problem) is not str:
                    raise ValueError("exclusion lacks problem")
                excluded.append(problem)
    report = build_answer_bank(read_records(args.input), args.output, exclude_problems=excluded)
    print(json.dumps({key: value for key, value in report.items() if key != "conflicts"},
                     ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
