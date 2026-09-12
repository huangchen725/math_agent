"""One-shot, source-frozen full-solve diagnostics; network requires --execute.

The eight public examples are development/probe evidence, never a hidden-test
accuracy estimate. Execution reads only input questions. Separate analysis reads
the frozen references and uses the conservative Q0 judge.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from uuid import uuid4

from evaluation import xh_accuracy_diagnostic as helpers
from evaluation import xh202627_pilot_control as control
from evaluation.audit_dataset import normalize_problem

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "1841685526e6f4d9c7211fb867d4db0aa65155d4"
MODEL = "intern-s2-preview-397b"
CAPS = {"requests": 120, "output_tokens": 360000, "dispatch_seconds": 5400,
        "request_wait_seconds": 350, "concurrency": 2}
POSITIONS = (2, 18, 35, 44, 53, 60)
HIT_IDS = ("diffyqs-001281b8de4368d6e7ffee06", "dmoi3-0664af3f3a1a08259d162765")
Q0_HASH = "b821cdddd56ef3276788e7307bdd7838f0fbe7f3817d0835eab4c092f5b5db27"
Q0_FILES = {"dev.input.jsonl": "71fb79af638ed64fdbb2d52a6d368aa25c51ad8cfd06d38e4641ee69af7beaa6",
            "dev.labels.jsonl": "8132d641a93757dc795d3597973b9ccb62b196d7c7631fc0f526c8d416adb628"}
TOOL_FILES = ("evaluation/solver_v2_diagnostic.py", "evaluation/xh_accuracy_diagnostic.py",
              "evaluation/xh202627_pilot_control.py", "evaluation/judge.py",
              "evaluation/audit_dataset.py",
              "answer_equivalence.py", "deterministic_verifier.py", "math_tools.py",
              "tool_executor.py", "agent_types.py")
# Independent derivations, not a model's correctness labels. Multi-part and
# non-polynomial notation remains manual/unknown when the Q0 judge cannot prove it.
REFERENCES = {
    2: ("5/4", "Exclude x=-3,-1; common-denominator subtraction is (4*x-5)/"
         "(10*(x+1)*(x+3)), hence x=5/4."),
    18: ("1/6", "1/(exp(2*x)-1)=1/(2*x)-1/2+x/6+O(x^3); poles cancel."),
    35: ("8*pi/15", "Set x=2*t^2, y=2*(1-t)^2, 0<=t<=1. Volume is "
          "16*pi*integral(t*(1-t)^4,0,1)=16*pi*(1/30)."),
    44: ("439/120", "Integrate z then y to obtain 35*x^2/2-59*x^3/6+17*x^4/12; "
          "integrating x gives 35/6-59/24+17/60=439/120."),
    53: ("{-3,3}", "Set t=abs(x)>=0. Then (t-3)*(t+1)=0, so t=3 "
          "and the complete real solution set is {-3,3}."),
    60: ("1. 1/3; 2. 4/3", "The kth-root coefficient tends to 1/4, so "
          "|1-3*x|<4; center 1/3, radius 4/3. Endpoints were not requested."),
}
HIT_REFERENCES = {
    HIT_IDS[0]: ("-9*exp(8*s)", "Derivative is eight times the function; at s=0 "
                "it is -9. Uniqueness follows for the linear constant-coefficient IVP."),
    HIT_IDS[1]: ("2", "Color the two nonempty parts separately; an edge rules out one color."),
}


def tool_hashes():
    return {name: helpers.file_hash(ROOT / name) for name in TOOL_FILES}


def read_inputs(path):
    rows = helpers.read(path)
    if type(rows) is not list or not 1 <= len(rows) <= 8:
        raise ValueError("invalid input count")
    identities = set()
    for row in rows:
        if (type(row) is not dict or set(row) != {"idx", "problem"}
                or type(row["idx"]) is not str or not 0 < len(row["idx"]) <= 160
                or type(row["problem"]) is not str or not 0 < len(row["problem"]) <= 20000
                or row["idx"] in identities):
            raise ValueError("unsupported, duplicate or label-bearing input")
        identities.add(row["idx"])
    return rows


def freeze_source(target, *, revision=None):
    """Copy only six formal sources and public resources, never the working .env."""
    target = Path(target)
    target.mkdir(parents=True, exist_ok=False)
    if revision is not None:
        get = lambda name: helpers.git_bytes(revision, name)
        resources = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", revision, "resources"],
            cwd=ROOT, text=True).splitlines()
    else:
        def get(name):
            path = helpers.safe_path(ROOT, name)
            if path.is_symlink() or path.stat().st_size > 32_000_000:
                raise ValueError("unsafe candidate artifact")
            return path.read_bytes()
        resources = [p.relative_to(ROOT).as_posix() for p in sorted((ROOT / "resources").rglob("*"))
                     if p.is_file()]
    names = list(helpers.formal_files(get("user_agent.py")))
    if len(names) != 6 or len(resources) > 10000:
        raise ValueError("unexpected formal closure or resource count")
    hashes, total = {}, 0
    for name in names + resources:
        data = get(name)
        total += len(data)
        if len(data) > 32_000_000 or total > 250_000_000:
            raise ValueError("source snapshot size limit")
        path = helpers.safe_path(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        hashes[name] = helpers.file_hash(path)
    module = helpers.load_source(target)
    agent = module.ReasoningAgent(object())
    config = {"agent": asdict(agent.config), "policy": asdict(agent.local_policy)}
    manifest = {"origin": revision or "working-tree", "files": hashes,
                "source_sha256": helpers.digest(hashes), "config": config,
                "config_sha256": helpers.digest(config), "constructor": "ReasoningAgent(client)"}
    helpers.write(target / "snapshot.json", helpers.seal(manifest))
    return manifest, module


def prepare(directory):
    """Create a new attempt and audited public inputs. No model calls."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    baseline, module = freeze_source(directory / "snapshots/baseline", revision=BASELINE)
    bundle = ROOT / "outputs/q0-umath-v4"
    dataset = helpers.read(bundle / "manifest.json")
    if dataset["dataset_sha256"] != Q0_HASH:
        raise ValueError("unrecognized public development dataset")
    for name, expected in Q0_FILES.items():
        if helpers.file_hash(bundle / name) != expected or dataset["files"][name] != expected:
            raise ValueError("modified public development dataset")
    inputs = [json.loads(line) for line in (bundle / "dev.input.jsonl").read_text(encoding="utf-8").splitlines()]
    labels = [json.loads(line) for line in (bundle / "dev.labels.jsonl").read_text(encoding="utf-8").splitlines()]
    selected, references, selection = [], [], []
    for position in POSITIONS:
        row, label = inputs[position], labels[position]
        if (row["idx"] != label["idx"] or row["problem"] != label["problem"]
                or label["split"] != "dev" or label["license"] != "MIT"
                or helpers.digest(normalize_problem(row["problem"])) != label["problem_sha256"]):
            raise ValueError("development provenance mismatch")
        expected, review = REFERENCES[position]
        selected.append({"idx": row["idx"], "problem": row["problem"]})
        references.append({**label, "expected": expected, "independent_review": review,
                           "reference_status": "independently_reviewed_notation"})
        selection.append({"idx": row["idx"], "stratum": "nonhit", "subject": label["subject"],
                          "position": position, "previously_exposed": True,
                          "selection": "one per frozen Q0 subject; item44 is a known regression"})
    bank = module._dependencies["xh202627_corpus"].load_answer_bank()
    records = {}
    for path in sorted((directory / "snapshots/baseline/resources/answer_bank/records").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if row["id"] in HIT_IDS:
                validated = bank.material(row["problem"])["match"]
                if validated != row or row["license"] != "CC-BY-SA-4.0":
                    raise ValueError("unverified bank probe")
                records[row["id"]] = row
    for identity in HIT_IDS:
        row = records[identity]
        expected, review = HIT_REFERENCES[identity]
        selected.append({"idx": identity, "problem": row["problem"]})
        references.append({**row, "idx": identity, "expected": expected,
                           "independent_review": review,
                           "reference_status": "independently_reviewed_notation"})
        selection.append({"idx": identity, "stratum": "hit", "subject": row["domain"],
                          "previously_exposed": identity == HIT_IDS[0],
                          "selection": "public corpus mechanism probe; not generalization"})
    helpers.write(directory / "inputs.json", selected)
    helpers.write(directory / "reference-audit.json", references)
    plan = {"schema_version": 1, "attempt_id": uuid4().hex, "baseline": BASELINE,
            "caps": CAPS, "model": MODEL, "tools": tool_hashes(), "selection": selection,
            "input_sha256": helpers.file_hash(directory / "inputs.json"),
            "reference_sha256": helpers.file_hash(directory / "reference-audit.json"),
            "dataset_sha256": Q0_HASH, "baseline_source_sha256": baseline["source_sha256"],
            "authorization": "2026-09-13 user approved one new bounded batch; no retry/resume",
            "scope": "6 exposed public dev pairs plus 2 public corpus pairs, strata separate",
            "order": "pair order fixed; baseline first on even positions, candidate first on odd"}
    helpers.write(directory / "plan.json", helpers.seal(plan))
    return {"status": "prepared_not_executed", "attempt_id": plan["attempt_id"], "pairs": 8, "caps": CAPS}


def check_plan(directory):
    plan, _ = helpers.unseal(directory / "plan.json")
    rows = read_inputs(directory / "inputs.json")
    if (plan["caps"] != CAPS or plan["model"] != MODEL or plan["baseline"] != BASELINE
            or plan["tools"] != tool_hashes()
            or plan["input_sha256"] != helpers.file_hash(directory / "inputs.json")
            or [r["idx"] for r in rows] != [s["idx"] for s in plan["selection"]]
            or any(s["stratum"] not in {"nonhit", "hit"} for s in plan["selection"])):
        raise ValueError("stale diagnostic plan")
    return plan, rows


def freeze(directory):
    directory = Path(directory).resolve()
    plan, rows = check_plan(directory)
    baseline, base_module = helpers.check_snapshot(directory / "snapshots/baseline")
    if baseline["origin"] != BASELINE or baseline["source_sha256"] != plan["baseline_source_sha256"]:
        raise ValueError("baseline identity changed")
    candidate, candidate_module = freeze_source(directory / "snapshots/candidate")
    if not candidate["config"]["policy"].get("solver_v2"):
        raise ValueError("candidate solver-v2 is not enabled")
    retrieval = {}
    for variant, module in (("baseline", base_module), ("candidate", candidate_module)):
        bank = module._dependencies["xh202627_corpus"].load_answer_bank()
        values = []
        for row, selected in zip(rows, plan["selection"]):
            match = bank.material(row["problem"])["match"]
            if bool(match) != (selected["stratum"] == "hit"):
                raise ValueError("retrieval stratum changed")
            values.append({"idx": row["idx"], "exact_match": bool(match)})
        retrieval[variant] = values
    result = {"plan_sha256": helpers.file_hash(directory / "plan.json"),
              "snapshots": {v: helpers.file_hash(directory / f"snapshots/{v}/snapshot.json")
                            for v in ("baseline", "candidate")},
              "identities": {v: {key: manifest[key] for key in ("source_sha256", "config_sha256")}
                             for v, manifest in (("baseline", baseline), ("candidate", candidate))},
              "retrieval": retrieval, "candidate_source_sha256": candidate["source_sha256"]}
    helpers.write(directory / "freeze.json", helpers.seal(result))
    return {"status": "frozen_not_executed", **result}


def check_freeze(directory):
    plan, rows = check_plan(directory)
    frozen, _ = helpers.unseal(directory / "freeze.json")
    if frozen["plan_sha256"] != helpers.file_hash(directory / "plan.json"):
        raise ValueError("modified freeze binding")
    modules = {}
    for variant in ("baseline", "candidate"):
        path = directory / "snapshots" / variant
        if helpers.file_hash(path / "snapshot.json") != frozen["snapshots"][variant]:
            raise ValueError("modified source binding")
        manifest, modules[variant] = helpers.check_snapshot(path)
        if frozen["identities"][variant] != {
                key: manifest[key] for key in ("source_sha256", "config_sha256")}:
            raise ValueError("modified source/config identity")
    return plan, rows, frozen, modules


class Admission:
    """Reserve uncertain sends durably; all workers share one nonrenewable cap."""
    def __init__(self, path, state, sender, clock=time.time):
        self.path, self.state, self.sender, self.clock = path, state, sender, clock
        self.lock = threading.Lock()

    def stop(self, reason):
        with self.lock:
            if self.state["status"] == "running":
                self.state.update(status="stopped", stop_reason=reason)
            helpers.write(self.path, self.state)

    def send(self, payload, *, job_key=None):
        helpers.strict_sender(lambda p: p)(payload)
        with self.lock:
            reason = None
            if self.state["status"] != "running":
                reason = self.state.get("stop_reason", "stopped")
            elif self.clock() >= self.state["dispatch_deadline"]:
                reason = "dispatch_deadline"
            elif self.state["attempts"] >= CAPS["requests"]:
                reason = "request_limit"
            elif self.state["requested_output_tokens"] + payload["max_tokens"] > CAPS["output_tokens"]:
                reason = "output_limit"
            if reason:
                self.state.update(status="stopped", stop_reason=reason)
                helpers.write(self.path, self.state)
                raise RuntimeError("diagnostic admission stopped")
            self.state["attempts"] += 1
            self.state["requested_output_tokens"] += payload["max_tokens"]
            if job_key is not None:
                counts = self.state.setdefault("sent_by_job", {})
                counts[job_key] = counts.get(job_key, 0) + 1
            helpers.write(self.path, self.state)
        try:
            receipt = control._validate_receipt(self.sender(payload), MODEL)
        except BaseException:
            self.stop("transport_or_protocol_failure")
            raise
        with self.lock:
            self.state["completed_responses"] += 1
            for key, value in receipt["metadata"]["usage"].items():
                self.state["known_usage"][key] += value
            if receipt["metadata"]["finish_reason"] == "length":
                self.state["truncations"] += 1
            helpers.write(self.path, self.state)
        return receipt


def observed_agent(module, client, events):
    """Observe ordinary solver calls without modifying request or return values."""
    agent = helpers.observed_agent(module, client, events)
    original = module.ReasoningAgent._chat

    def chat(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        system = args[0] if args else kwargs.get("system_prompt", "")
        stage = "other"
        for constant, label in (("V2_ROUTE_PROMPT", "route"), ("V2_REPAIR_PROMPT", "repair"),
                                ("V2_REVIEW_PROMPT", "review")):
            marker = getattr(module, constant, None)
            if isinstance(marker, str) and marker and marker in system:
                stage = label
        # Raw public answer text is stored only under this local diagnostic directory.
        events.append({"stage": "chat", "kind": stage, "response": str(result)[:100000],
                       "finish_reason": getattr(result, "finish_reason", None)})
        return result
    type(agent)._chat = chat
    return agent


def run(directory, sender, *, clock=time.time):
    directory = Path(directory).resolve()
    plan, rows, frozen, modules = check_freeze(directory)
    # This claim survives success, error and process death. There is no phase resume.
    descriptor = os.open(directory / "attempt.claim", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    now = clock()
    state = {"attempt_id": plan["attempt_id"], "status": "running", "started_at": now,
             "dispatch_deadline": now + CAPS["dispatch_seconds"], "attempts": 0,
             "completed_responses": 0, "requested_output_tokens": 0, "truncations": 0,
             "known_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
             "freeze_sha256": helpers.file_hash(directory / "freeze.json")}
    state_path = directory / "execution.json"
    helpers.write(state_path, state)
    admission = Admission(state_path, state, sender, clock)

    def job(position, row, variant):
        output = directory / "runs" / f"item-{position:02d}" / variant
        output.mkdir(parents=True, exist_ok=False)
        began, events, result, error = clock(), [], None, None
        if clock() >= state["dispatch_deadline"]:
            admission.stop("dispatch_deadline")
        if state["status"] != "running":
            helpers.write(output / "result.json", {"status": "not_started", "idx": row["idx"]})
            return
        relay = output / "relay"
        control.create(relay, control.Limits(16, 16 * 8192,
                       max(0.001, state["dispatch_deadline"] - clock()), 350), model=MODEL,
                       identity={**frozen["identities"][variant],
                                 "input_sha256": helpers.sha256(row["problem"].encode()).hexdigest()})
        job_key = f"item-{position:02d}/{variant}"
        worker = threading.Thread(target=control.serve,
                                  args=(relay, lambda p: admission.send(p, job_key=job_key)), daemon=True)
        worker.start()
        try:
            result = observed_agent(modules[variant], control.RelayClient(relay), events).solve(row["problem"], {})
        except control.PilotStopped:
            error = "pilot_stopped"
            admission.stop("local_relay_stopped")
        except BaseException as exc:
            error = type(exc).__name__
            admission.stop("local_execution_failure")
        finally:
            control.pause(relay, reason="finished")
            worker.join(timeout=355)
            if worker.is_alive():
                admission.stop("worker_finish_timeout")
                raise RuntimeError("network worker did not finish")
            receipt = control.status(relay)
            completed = (isinstance(result, dict) and isinstance(result.get("final_response"), str)
                         and bool(result["final_response"].strip()) and isinstance(result.get("trace"), list))
            if result is not None and not completed:
                admission.stop("invalid_public_result")
            helpers.write(output / "result.json", {
                "status": "completed" if completed else "interrupted", "error_category": error,
                "position": position, "idx": row["idx"], "variant": variant,
                "problem_sha256": helpers.sha256(row["problem"].encode()).hexdigest(),
                "seconds": clock() - began, "observation": events, "result": result, "receipt": receipt,
                "requests_sent": state.get("sent_by_job", {}).get(job_key, 0)})
            print(json.dumps({"position": position, "variant": variant, "completed": completed,
                              "requests": receipt["attempts"]}), flush=True)

    def pair(position, row):
        variants = ("baseline", "candidate") if position % 2 == 0 else ("candidate", "baseline")
        for variant in variants:
            job(position, row, variant)

    try:
        # Start only two complete pairs at a time; later strata cannot consume
        # quota ahead of earlier nonhit pairs.
        for offset in range(0, len(rows), CAPS["concurrency"]):
            with ThreadPoolExecutor(max_workers=CAPS["concurrency"]) as pool:
                futures = [pool.submit(pair, p, rows[p])
                           for p in range(offset, min(offset + CAPS["concurrency"], len(rows)))]
                for future in futures:
                    future.result()
    except BaseException:
        admission.stop("local_execution_failure")
        raise
    finally:
        with admission.lock:
            if state["status"] == "running":
                state["status"] = "completed"
            state["finished_at"] = clock()
            state["unknown_usage_requests"] = state["attempts"] - state["completed_responses"]
            state["result_hashes"] = {
                p.relative_to(directory).as_posix(): helpers.file_hash(p)
                for p in sorted((directory / "runs").glob("item-*/*/result.json"))}
            helpers.write(state_path, state)
    return state


def answer_body(text):
    """Judge the canonical delivered answer only, never a substring of reasoning."""
    if not isinstance(text, str) or len(text) > 100000:
        return ""
    markers = list(re.finditer(r"(?m)^\s*最终答案[：:]", text))
    if len(markers) != 1:
        return ""
    body = text[markers[0].end():].strip()
    return body if 0 < len(body) <= 2048 else ""


def candidate_answers(events):
    candidates = []
    for event in events:
        if (event.get("stage") == "chat" and event.get("kind") in {"route", "repair"}
                and event.get("finish_reason") in {None, "", "stop"}):
            candidate = answer_body(event["response"])
            if candidate:
                candidates.append(candidate)
        elif event.get("stage") == "_aggregate":
            # Legacy _aggregate receives admitted typed Candidate records.
            before = event.get("before", [])
            for candidate in before[0] if before and isinstance(before[0], list) else []:
                answer = candidate.get("answer") if isinstance(candidate, dict) else None
                if isinstance(answer, dict) and isinstance(answer.get("raw"), str):
                    candidates.append(answer["raw"])
    return list(dict.fromkeys(candidates))


def analyze(directory):
    from evaluation.judge import judge_answer

    directory = Path(directory).resolve()
    plan, rows = check_plan(directory)
    if helpers.file_hash(directory / "reference-audit.json") != plan["reference_sha256"]:
        raise ValueError("modified reference audit")
    references = helpers.read(directory / "reference-audit.json")
    if [r["idx"] for r in references] != [r["idx"] for r in rows]:
        raise ValueError("reference identity mismatch")
    state = helpers.read(directory / "execution.json")
    if state["status"] not in {"completed", "stopped"}:
        raise ValueError("execution is not terminal")
    for name, expected in state["result_hashes"].items():
        if helpers.file_hash(helpers.safe_path(directory, name)) != expected:
            raise ValueError("modified execution result")
    results = []
    for position, (row, reference, selection) in enumerate(zip(rows, references, plan["selection"])):
        item = {"idx": row["idx"], "stratum": selection["stratum"], "subject": selection["subject"],
                "reference_review": reference["independent_review"], "variants": {}}
        for variant in ("baseline", "candidate"):
            path = directory / "runs" / f"item-{position:02d}" / variant / "result.json"
            if not path.exists():
                item["variants"][variant] = {"status": "not_started", "grade": "not_run"}
                continue
            run_result = helpers.read(path)
            final = (run_result.get("result") or {}).get("final_response", "")
            actual = answer_body(final)
            grade = asdict(judge_answer(reference["expected"], actual))
            candidates = candidate_answers(run_result.get("observation", []))
            candidate_grades = [asdict(judge_answer(reference["expected"], c)) for c in candidates]
            coverage = True if any(g["status"] == "correct" for g in candidate_grades) else (
                None if not candidates or any(g["status"] == "unknown" for g in candidate_grades) else False)
            item["variants"][variant] = {
                "status": run_result["status"], "grade": grade["status"], "judge": grade,
                "final_response": final, "candidate_answers": candidates, "candidate_grades": candidate_grades,
                "correct_candidate_coverage": coverage,
                "selection_loss": coverage is True and grade["status"] in {"wrong", "no_answer"},
                "manual_review_required": grade["status"] == "unknown",
                "requests": run_result.get("requests_sent", 0),
                "relay_attempts": run_result.get("receipt", {}).get("attempts", 0),
                "seconds": run_result.get("seconds"),
                "trace": (run_result.get("result") or {}).get("trace", [])}
        results.append(item)
    strata = {}
    for stratum in ("nonhit", "hit"):
        selected = [item for item in results if item["stratum"] == stratum]
        complete = [item for item in selected if all(v["status"] == "completed" for v in item["variants"].values())]
        strata[stratum] = {"planned_pairs": len(selected), "complete_pairs": len(complete)}
        for variant in ("baseline", "candidate"):
            grades = [item["variants"][variant]["grade"] for item in complete]
            strata[stratum][variant] = {status: grades.count(status) for status in
                                        ("correct", "wrong", "unknown", "no_answer")}
    report = {"status": "local_diagnostic_not_official_accuracy", "attempt_id": plan["attempt_id"],
              "strata": strata, "budget": state, "items": results,
              "limitations": ["Selected exposed public data; not blind or representative of official questions.",
                              "Unknown grades need independent manual review, never counted as wrong or correct.",
                              "Candidate coverage is observed delivered candidates only; missing observation is unknown.",
                              "No single-component causal attribution from the combined strategy."]}
    helpers.write(directory / "analysis.json", report)
    return {"status": report["status"], "strata": strata, "analysis": str(directory / "analysis.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "freeze", "run", "analyze"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.directory)
    elif args.command == "freeze":
        result = freeze(args.directory)
    elif args.command == "analyze":
        result = analyze(args.directory)
    elif not args.execute:
        check_freeze(args.directory.resolve())
        result = {"status": "validated_not_executed", "caps": CAPS}
    else:
        from dotenv import dotenv_values
        key = os.environ.get("INTERN_API_KEY") or dotenv_values(ROOT / ".env").get("INTERN_API_KEY")
        if not key or not key.strip():
            raise ValueError("missing credential")
        authorization = key.strip() if key.strip().startswith("Bearer ") else "Bearer " + key.strip()
        result = run(args.directory, control.make_http_sender(authorization, MODEL, wait_seconds=345))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
