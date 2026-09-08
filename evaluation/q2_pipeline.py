"""Offline preregistration, repeated paired analysis and a one-candidate holdout workflow.

CLI never calls an API. Execution/model receipts are local evidence, not a
cryptographic attestation of a provider or official platform.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import random
import time
from uuid import uuid4

from evaluation.q0_pipeline import digest, scoring_hash, score_bound_run
from evaluation.q1_experiments import make_plan, run_plan, VARIANTS

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RULES = {"min_delta": 0.02, "max_unusable_delta": 0.0,
                 "max_cost_ratio": 1.25, "alpha": 0.05, "bootstrap_samples": 5000,
                 "bootstrap_seed": 20260906, "min_items": 20}


def read(path):
    if path.stat().st_size > 40_000_000:
        raise ValueError("artifact exceeds bound")
    return json.loads(path.read_text(encoding="utf-8-sig"),
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def seal(value):
    return {**value, "sha256": digest(value)}


def unseal(value):
    value = dict(value)
    checksum = value.pop("sha256")
    if digest(value) != checksum:
        raise ValueError("artifact changed")
    return value


def analysis_hash():
    return digest({"q2": sha256(Path(__file__).read_bytes()).hexdigest(), "scoring": scoring_hash()})


def create_study(bundle, study, *, candidates=None, repeats=3):
    candidates = sorted(candidates if candidates is not None else VARIANTS[1:])
    if (not candidates or len(set(candidates)) != len(candidates)
            or any(v not in VARIANTS[1:] for v in candidates)
            or type(repeats) is not int or not 3 <= repeats <= 10):
        raise ValueError("invalid preregistered candidates/repeats")
    plans = {s: make_plan(bundle, split=s) for s in ("dev", "test")}
    protocol = seal({"schema_version": 1, "study_id": uuid4().hex, "created_at": time.time(),
        "bundle": str(bundle.resolve()), "plans": plans, "candidates": candidates,
        "repeats": repeats, "rules": dict(DEFAULT_RULES), "analysis_sha256": analysis_hash(),
        "request_ceiling_dev": plans["dev"]["per_variant_request_ceiling"] * repeats * (len(candidates)+1),
        "request_ceiling_holdout": plans["test"]["per_variant_request_ceiling"] * repeats * 2,
        "claim": "offline preparation; no API authorization or performance evidence"})
    study.mkdir(parents=True, exist_ok=False)
    write(study / "protocol.json", protocol)
    write(study / "state.json", seal({"protocol_sha256": protocol["sha256"], "phase": "development",
        "selected": None, "tickets": {}, "runs": {}, "selection": None}))
    return protocol


def load_study(study):
    protocol = read(study / "protocol.json")
    p = unseal(protocol)
    state = unseal(read(study / "state.json"))
    if (p["rules"] != DEFAULT_RULES or type(p["repeats"]) is not int or not 3 <= p["repeats"] <= 10
            or not p["candidates"] or p["candidates"] != sorted(set(p["candidates"]))
            or any(v not in VARIANTS[1:] for v in p["candidates"])
            or state["phase"] not in ("development", "selected", "holdout", "closed")
            or state["selected"] not in [None, *p["candidates"]]):
        raise ValueError("invalid frozen rules or state")
    if state["protocol_sha256"] != protocol["sha256"] or p["analysis_sha256"] != analysis_hash():
        raise ValueError("stale study or analysis code")
    for split in ("dev", "test"):
        if p["plans"][split] != make_plan(Path(p["bundle"]), split=split):
            raise ValueError("dataset/runtime/config changed since freeze")
    return protocol, state


@contextmanager
def locked(study):
    path = study / ".lock"
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        yield
    finally:
        os.close(fd)
        path.unlink()


def reserve(study, variant, repeat, *, split="dev"):
    with locked(study):
        p, state = load_study(study)
        if split not in ("dev", "test") or type(repeat) is not int or not 0 <= repeat < p["repeats"]:
            raise ValueError("invalid split/repeat")
        allowed = ["baseline", *p["candidates"]] if split == "dev" else ["baseline", state["selected"]]
        if variant not in allowed or (split == "dev" and state["phase"] != "development"):
            raise ValueError("candidate locked or unknown")
        if split == "test" and state["phase"] not in ("selected", "holdout"):
            raise ValueError("holdout requires a selected candidate")
        if split == "test" and evaluate(study) != state["selection"]:
            raise ValueError("selected development evidence changed")
        slot = f"{split}:{variant}:{repeat}"
        if slot in state["tickets"]:
            raise ValueError("slot already reserved; failures cannot be silently rerun")
        if split == "test":
            # Shared across studies using this bundle; crashes conservatively consume access.
            marker = Path(p["bundle"]) / ".q2-holdout-use.json"
            owner = {"protocol_sha256": p["sha256"], "study_id": p["study_id"]}
            try:
                with marker.open("x", encoding="utf-8") as handle:
                    json.dump(owner, handle)
            except FileExistsError:
                if read(marker) != owner:
                    raise ValueError("holdout already reserved by another study") from None
            state["phase"] = "holdout"
        ticket = {"protocol_sha256": p["sha256"], "slot": slot, "nonce": uuid4().hex, "reserved_at": time.time()}
        state["tickets"][slot] = ticket
        write(study / "state.json", seal(state))
        return ticket


class ObservedTextClient:
    """Explicit LOCAL owned client adapter; never wrap an unknown official client.

    The supplied local client must support request-bound meta_sink. No probing,
    nominal type checks, private getters, retries or tool capability inference.
    """
    def __init__(self, owned_local_client):
        self.owned_local_client = owned_local_client
        self.observations = []

    def chat(self, *, messages, temperature, max_tokens,
             thinking_mode=None, tools=None, tool_choice=None):
        if tools is not None or tool_choice is not None:
            raise ValueError("text-only observer does not support tool parameters")
        captured = []
        passthrough = {"meta_sink": captured.append}
        if thinking_mode is not None:
            passthrough["thinking_mode"] = thinking_mode
        response = self.owned_local_client.chat(messages=messages, temperature=temperature,
            max_tokens=max_tokens, **passthrough)
        self.observations.append(captured[0] if len(captured) == 1 else {})
        # Deliver request-bound finish_reason through the public response shape.
        if isinstance(response, str):
            return {"content": response, "finish_reason": captured[0].get("finish_reason") if len(captured) == 1 else None}
        return response


def receipt_from_observations(run_dir, observations):
    summary = read(run_dir / "_run" / "run_summary.json")
    valid = bool(observations)
    tokens, truncated, attempts = 0, 0, 0
    models = set()
    for item in observations:
        usage = item.get("usage", {}) if type(item) is dict else {}
        n = usage.get("total_tokens") if type(usage) is dict else None
        model = item.get("model") if type(item) is dict else None
        count = item.get("attempts") if type(item) is dict else None
        finish = item.get("finish_reason") if type(item) is dict else None
        good = (type(n) is int and 0 < n <= 10**9 and type(model) is str
                and model == summary["model"] and type(count) is int and 1 <= count <= 100
                and finish in ("stop", "length", "tool_calls", "content_filter"))
        valid = valid and good
        if good:
            tokens += n
            attempts += count
            truncated += finish == "length"
            models.add(model)
    return {"run_id": summary["run_id"], "output_sha256": digest(summary["output_files_sha256"]),
        "source": "explicit_local_request_metadata", "complete": valid,
        "model": next(iter(models)) if len(models) == 1 else None,
        "requests": len(observations), "attempts": attempts, "total_tokens": tokens if valid else None,
        "truncated_requests": truncated if valid else None, "elapsed_ms": summary["duration_ms"]}


def run_reserved(study, slot, output, client, *, execution="fixture"):
    """Caller owns API authorization. Q2 CLI deliberately exposes no execute command."""
    with locked(study):
        p, state = load_study(study)
        ticket = state["tickets"][slot]
        if slot in state["runs"] or execution not in ("fixture", "real") or output.exists():
            raise ValueError("already recorded or invalid execution/output")
        split, variant, _ = slot.split(":")
        if (split == "dev" and state["phase"] != "development") or (split == "test" and state["phase"] != "holdout"):
            raise ValueError("execution phase closed")
        if split == "test" and evaluate(study) != state["selection"]:
            raise ValueError("selected development evidence changed")
        # Nonce is only used after checking its alphabet; state is untrusted input.
        import re
        if not re.fullmatch(r"[a-f0-9]{32}", ticket["nonce"]):
            raise ValueError("invalid ticket nonce")
        claim = study / (ticket["nonce"] + ".attempt")
        with claim.open("x", encoding="utf-8") as handle:
            handle.write(digest(ticket))
    return run_plan(p["plans"][split], variant, Path(p["bundle"]), output, client,
                    execution=execution, run_ticket=ticket)


def load_run(p, ticket, run_dir, receipt):
    split, variant, _ = ticket["slot"].split(":")
    plan = p["plans"][split]
    summary = read(run_dir / "_run" / "run_summary.json")
    if (summary.get("run_ticket_sha256") != digest(ticket)
            or summary.get("execution") not in ("fixture", "real")
            or type(summary.get("started_at")) not in (float, int)
            or not math.isfinite(summary["started_at"]) or summary["started_at"] < ticket["reserved_at"]
            or not isinstance(summary.get("run_id"), str) or not summary["run_id"]):
        raise ValueError("run was not bound before execution")
    report = score_bound_run(Path(p["bundle"]), split, run_dir, model=plan["model"], code_sha=plan["code_sha"],
        config=plan["variants"][variant], execution=summary["execution"], local_tools=False)
    rows = [{"idx": str(r["idx"]), "status": r["status"], "reference_sha256": digest(r["expected"]),
             "subject": r["subject"], "invalid": r["invalid"], "truncated_observed": r["truncated"]}
            for r in report["results"]]
    requests = report["summary"]["usage"].get("model_requests")
    if receipt is not None:
        if (receipt.get("run_id") != summary["run_id"] or receipt.get("output_sha256") != report["provenance"]["output_sha256"]
                or receipt.get("source") != "explicit_local_request_metadata"):
            raise ValueError("receipt does not bind this run")
        if receipt.get("complete") is True:
            for key in ("requests", "attempts", "total_tokens", "truncated_requests", "elapsed_ms"):
                if type(receipt.get(key)) is not int or not 0 <= receipt[key] <= 10**12:
                    raise ValueError("invalid receipt metric")
            if (receipt["requests"] != requests or receipt["requests"] <= 0 or receipt["total_tokens"] <= 0
                    or receipt["attempts"] < receipt["requests"] or receipt["truncated_requests"] > receipt["requests"]
                    or receipt["elapsed_ms"] != summary["duration_ms"] or receipt.get("model") != plan["model"]):
                raise ValueError("inconsistent receipt")
    return {"run_id": summary["run_id"], "manifest_sha256": digest(summary),
        "report_sha256": digest(report), "execution": summary["execution"], "rows": rows, "receipt": receipt}


def record(study, slot, run_dir, receipt=None):
    with locked(study):
        p, state = load_study(study)
        if slot not in state["tickets"] or slot in state["runs"]:
            raise ValueError("missing ticket or already recorded")
        result = load_run(p, state["tickets"][slot], run_dir, receipt)
        if result["run_id"] in {r["data"]["run_id"] for r in state["runs"].values()}:
            raise ValueError("duplicate run identity")
        state["runs"][slot] = {"directory": str(run_dir.resolve()), "data": result}
        write(study / "state.json", seal(state))
        return {"slot": slot, "execution": result["execution"], "metrics_complete": bool(receipt and receipt.get("complete"))}


def paired_bootstrap(values, *, alpha, samples, seed):
    """Percentile interval over item clusters, not item-by-repeat pseudo-replicates."""
    if (not values or len(values) > 10000 or not 0 < alpha < 1
            or type(samples) is not int or not 100 <= samples <= 20000
            or any(type(v) not in (int, float) or not math.isfinite(v) or not -1 <= v <= 1 for v in values)):
        raise ValueError("invalid paired item effects")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n))/n for _ in range(samples))
    return [means[max(0, math.floor(samples*alpha/2))], means[min(samples-1, math.ceil(samples*(1-alpha/2))-1)]]


def compare_repeats(left, right, rules, *, comparisons=1):
    if len(left) != len(right) or not 3 <= len(left) <= 10 or type(comparisons) is not int or not 1 <= comparisons <= 9:
        raise ValueError("at least three matched repetitions required")
    indices = sorted(r["idx"] for r in left[0]["rows"])
    if not indices or len(indices) != len(set(indices)):
        raise ValueError("empty or duplicate items")
    deltas, worst, transitions, repeat_delta = Counter(), Counter(), Counter(), []
    unusable_delta, subjects, references = [], {}, {}
    for before, after in zip(left, right):
        a, b = ({r["idx"]: r for r in x["rows"]} for x in (before, after))
        if sorted(a) != indices or sorted(b) != indices or len(a) != len(before["rows"]) or len(b) != len(after["rows"]):
            raise ValueError("repeat item mismatch")
        rd, ud = 0, 0
        for idx in indices:
            x, y = a[idx], b[idx]
            if any(row["status"] not in ("correct", "wrong", "unknown", "no_answer", "error", "missing") for row in (x,y)):
                raise ValueError("invalid verdict status")
            if x["reference_sha256"] != y["reference_sha256"] or x["subject"] != y["subject"]:
                raise ValueError("paired label mismatch")
            if idx in subjects and subjects[idx] != x["subject"]:
                raise ValueError("subject changed across repeats")
            subjects[idx] = x["subject"]
            if idx in references and references[idx] != x["reference_sha256"]:
                raise ValueError("reference changed across repetitions")
            references[idx] = x["reference_sha256"]
            d = int(y["status"] == "correct") - int(x["status"] == "correct")
            deltas[idx] += d
            # Worst case for unresolved grading: baseline unknown correct, candidate unknown wrong.
            worst[idx] += int(y["status"] == "correct") - int(x["status"] in ("correct", "unknown"))
            rd += d
            ud += int(y["status"] in ("no_answer", "error", "missing") or y["invalid"]) - int(x["status"] in ("no_answer", "error", "missing") or x["invalid"])
            transitions[x["status"]+"->"+y["status"]] += 1
        repeat_delta.append(rd/len(indices))
        unusable_delta.append(ud/len(indices))
    values = [deltas[i]/len(left) for i in indices]
    lower_values = [worst[i]/len(left) for i in indices]
    interval = paired_bootstrap(lower_values, alpha=rules["alpha"]/comparisons,
        samples=rules["bootstrap_samples"], seed=rules["bootstrap_seed"])
    complete = all(r.get("receipt") and r["receipt"].get("complete") is True for r in left+right)
    ratios, trunc_delta = {}, None
    if complete:
        for metric in ("requests", "attempts", "total_tokens", "elapsed_ms"):
            before = sum(r["receipt"][metric] for r in left)
            after = sum(r["receipt"][metric] for r in right)
            ratios[metric] = after/before if before else None
        trunc_delta = (sum(r["receipt"]["truncated_requests"] for r in right)/sum(r["receipt"]["requests"] for r in right)
            - sum(r["receipt"]["truncated_requests"] for r in left)/sum(r["receipt"]["requests"] for r in left))
    mean = sum(values)/len(values)
    reasons = []
    if any(r["execution"] != "real" for r in left+right):
        reasons.append("fixture_or_unverified_execution")
    if not complete or any(v is None for v in ratios.values()):
        reasons.append("missing_cost_or_truncation_evidence")
    if len(indices) < rules["min_items"]:
        reasons.append("too_few_independent_items")
    regression = (mean < 0 or max(unusable_delta) > rules["max_unusable_delta"]
        or any(v is not None and v > rules["max_cost_ratio"] for v in ratios.values())
        or (trunc_delta is not None and trunc_delta > 0))
    if regression:
        reasons.append("observed_regression_or_cost_limit")
    if mean < rules["min_delta"] or interval[0] <= 0 or min(repeat_delta) < 0:
        reasons.append("insufficient_repeated_gain")
    status = "eligible" if not reasons else ("reject" if regression else "inconclusive")
    diagnostics = {}
    for name, runs in (("baseline", left), ("candidate", right)):
        rows = [row for run in runs for row in run["rows"]]
        diagnostics[name] = {"item_observations": len(rows),
            "statuses": dict(Counter(row["status"] for row in rows)),
            "invalid": sum(bool(row["invalid"]) for row in rows),
            "invalid_rate": sum(bool(row["invalid"]) for row in rows)/len(rows),
            "item_truncation_observed": sum(bool(row.get("truncated_observed")) for row in rows),
            "request_metrics": {metric: sum(run["receipt"][metric] for run in runs)
                for metric in ("requests", "attempts", "total_tokens", "truncated_requests", "elapsed_ms")}
                if complete else None}
    return {"status": status, "reasons": reasons, "independent_items": len(indices), "repeats": len(left),
        "mean_accuracy_delta": mean, "per_repeat_delta": repeat_delta, "unusable_delta": unusable_delta,
        "unknown_worst_case_cluster_interval": interval, "familywise_alpha": rules["alpha"],
        "comparisons": comparisons, "transitions": dict(transitions), "cost_ratios": ratios,
        "request_truncation_delta": trunc_delta, "diagnostics": diagnostics,
        "by_subject": {s: {"items": sum(subjects[i] == s for i in indices),
            "mean_delta": sum(deltas[i]/len(left) for i in indices if subjects[i] == s)/sum(subjects[i] == s for i in indices)} for s in sorted(set(subjects.values()))},
        "claim": "approximate paired item-cluster bootstrap; local evidence, not official performance"}


def evaluate(study, *, split="dev"):
    p, state = load_study(study)
    if split not in ("dev", "test") or (split == "test" and not state["selected"]):
        raise ValueError("invalid evaluation split")
    variants = p["candidates"] if split == "dev" else [state["selected"]]
    required = [f"{split}:{v}:{r}" for v in ["baseline", *variants] for r in range(p["repeats"])]
    missing = sorted(set(required)-state["runs"].keys())
    if missing:
        return {"status": "incomplete", "missing_slots": missing, "candidates": {}}
    collected = {}
    for slot in required:
        saved = state["runs"][slot]
        actual = load_run(p, state["tickets"][slot], Path(saved["directory"]), saved["data"]["receipt"])
        if actual != saved["data"]:
            raise ValueError("registered evidence changed")
        collected[slot] = actual
    results = {v: compare_repeats([collected[f"{split}:baseline:{r}"] for r in range(p["repeats"])],
        [collected[f"{split}:{v}:{r}"] for r in range(p["repeats"])], p["rules"], comparisons=len(variants)) for v in variants}
    return {"status": "analyzed", "protocol_sha256": p["sha256"], "split": split, "candidates": results,
            "evidence_sha256": digest(collected)}


def select(study, candidate):
    with locked(study):
        p, state = load_study(study)
        if state["phase"] != "development" or candidate not in p["candidates"]:
            raise ValueError("selection already locked or candidate unknown")
        result = evaluate(study)
        if result["status"] != "analyzed" or result["candidates"][candidate]["status"] != "eligible":
            raise ValueError("candidate has not met preregistered development gates")
        state.update(phase="selected", selected=candidate, selection=result)
        write(study / "state.json", seal(state))
        return {"selected": candidate, "status": "locked", "selection_sha256": digest(result)}


def acceptance(study):
    with locked(study):
        p, state = load_study(study)
        if state["phase"] != "holdout":
            raise ValueError("holdout has not started or is already closed")
        if evaluate(study) != state["selection"]:
            raise ValueError("selected development evidence changed")
        result = evaluate(study, split="test")
        if result["status"] != "analyzed":
            raise ValueError("holdout incomplete")
        state["phase"] = "closed"
        state["acceptance"] = result
        write(study / "state.json", seal(state))
        return result


def delivery_check(study, *, expected_commit, remote_commit, captured_commit=None):
    import subprocess
    p, state = load_study(study)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    accepted = state["phase"] == "closed" and state.get("acceptance", {}).get("candidates", {}).get(state["selected"], {}).get("status") == "eligible"
    if accepted and (evaluate(study) != state["selection"] or evaluate(study, split="test") != state["acceptance"]):
        raise ValueError("accepted evidence changed")
    return {"local_head": head, "dirty": dirty, "offline_holdout_accepted": accepted,
        "ready_for_submission_review": accepted and not dirty and expected_commit == head == remote_commit,
        "captured_matches": captured_commit == expected_commit if captured_commit else None,
        "evidence": "remote/captured values supplied by caller; no remote fetch or official submission performed",
        "remaining": "official compatibility, model receipt, dependency/security release checks and actual submission remain separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("freeze")
    create.add_argument("bundle", type=Path)
    create.add_argument("study", type=Path)
    create.add_argument("--candidates", nargs="+")
    create.add_argument("--repeats", type=int, default=3)
    for name in ("reserve", "record", "analyze", "select", "accept", "delivery"):
        mode = commands.add_parser(name)
        mode.add_argument("study", type=Path)
        if name == "reserve":
            mode.add_argument("variant")
            mode.add_argument("repeat", type=int)
            mode.add_argument("--split", choices=("dev", "test"), default="dev")
        if name == "record":
            mode.add_argument("slot")
            mode.add_argument("run", type=Path)
            mode.add_argument("--receipt", type=Path)
        if name == "analyze":
            mode.add_argument("--split", choices=("dev", "test"), default="dev")
        if name == "select":
            mode.add_argument("candidate")
        if name == "delivery":
            mode.add_argument("--expected-commit", required=True)
            mode.add_argument("--remote-commit", required=True)
            mode.add_argument("--captured-commit")
    args = parser.parse_args()
    if args.command == "freeze":
        result = create_study(args.bundle, args.study, candidates=args.candidates, repeats=args.repeats)
        result = {k: result[k] for k in ("sha256", "request_ceiling_dev", "request_ceiling_holdout", "claim")}
    elif args.command == "reserve":
        result = reserve(args.study, args.variant, args.repeat, split=args.split)
    elif args.command == "record":
        result = record(args.study, args.slot, args.run, read(args.receipt) if args.receipt else None)
    elif args.command == "analyze":
        result = evaluate(args.study, split=args.split)
    elif args.command == "select":
        result = select(args.study, args.candidate)
    elif args.command == "accept":
        result = acceptance(args.study)
    else:
        result = delivery_check(args.study, expected_commit=args.expected_commit, remote_commit=args.remote_commit, captured_commit=args.captured_commit)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
