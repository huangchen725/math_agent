"""Frozen, bounded first-day diagnostics; network requires explicit --execute.

Full pairs and one-call hit probes are reported separately. References are never
read by execution. Earlier diagnostics and their receipts remain untouched.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time

from evaluation import xh_accuracy_diagnostic as helpers
from evaluation import xh202627_pilot_control as control

ROOT = Path(__file__).resolve().parents[1]
MODEL = helpers.MODEL
CAPS = {"requests": 200, "output_tokens": 650000, "seconds": 10800,
        "concurrency": 3, "request_wait": 350}
PHASES = ("baseline", "candidate", "hits")


def frozen_source(directory, source):
    directory, source = Path(directory), Path(source)
    directory.mkdir(parents=True, exist_ok=False)
    files = list(helpers.formal_files((source / "user_agent.py").read_bytes()))
    resources = source / "resources"
    files += [p.relative_to(source).as_posix() for p in sorted(resources.rglob("*")) if p.is_file()]
    hashes = {}
    for name in files:
        original = helpers.safe_path(source, name)
        if original.is_symlink() or original.stat().st_size > 32_000_000:
            raise ValueError("unsafe or oversized source artifact")
        target = helpers.safe_path(directory, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(original.read_bytes())
        hashes[name] = helpers.file_hash(target)
    module = helpers.load_source(directory)
    agent = module.ReasoningAgent(object())
    config = {"agent": asdict(agent.config), "policy": asdict(agent.local_policy)}
    manifest = {"files": hashes, "source_sha256": helpers.digest(hashes), "config": config,
                "config_sha256": helpers.digest(config), "constructor": "ReasoningAgent(client)"}
    helpers.write(directory / "snapshot.json", helpers.seal(manifest))
    return manifest


def inputs(path, count):
    rows = helpers.read(path)
    if type(rows) is not list or len(rows) != count or len({r["idx"] for r in rows}) != count:
        raise ValueError("unexpected input matrix")
    for row in rows:
        if (set(row) != {"idx", "problem"} or type(row["idx"]) is not str
                or type(row["problem"]) is not str or not 0 < len(row["problem"]) <= 20000):
            raise ValueError("references or unsupported fields in input")
    return rows


def prepare(directory):
    directory = Path(directory).resolve()
    inputs(directory / "day1-inputs.json", 6)
    target = directory / "live"
    target.mkdir(exist_ok=False)
    frozen_source(target / "snapshots/baseline", directory / "baseline")
    plan = {"caps": CAPS, "model": MODEL, "input_sha256": helpers.file_hash(directory / "day1-inputs.json"),
            "tool_sha256": helpers.file_hash(__file__), "helper_sha256": helpers.file_hash(helpers.__file__),
            "controller_sha256": helpers.file_hash(control.__file__),
            "authorization": "2026-09-10 user approved first-day plan before midnight; no retry/resume",
            "scope": "six public non-bank full pairs and eight separate one-call bank probes"}
    helpers.write(target / "plan.json", helpers.seal(plan))
    return {"status": "prepared_not_executed", "caps": CAPS}


def check(directory):
    plan, _ = helpers.unseal(directory / "live/plan.json")
    if (plan["caps"] != CAPS or plan["model"] != MODEL
            or plan["tool_sha256"] != helpers.file_hash(__file__)
            or plan["helper_sha256"] != helpers.file_hash(helpers.__file__)
            or plan["controller_sha256"] != helpers.file_hash(control.__file__)
            or plan["input_sha256"] != helpers.file_hash(directory / "day1-inputs.json")):
        raise ValueError("stale diagnostic plan")
    return plan


class Admission:
    """One durable budget shared by all three local workers and all phases."""
    def __init__(self, path, state, sender, clock=time.time):
        self.path, self.state, self.sender, self.clock = path, state, sender, clock
        self.lock = threading.Lock()

    def stop(self, reason):
        with self.lock:
            self.state.update(status="stopped", stop_reason=reason)
            helpers.write(self.path, self.state)

    def send(self, payload):
        helpers.strict_sender(lambda value: value)(payload)
        with self.lock:
            reason = None
            if self.state["status"] == "stopped":
                reason = self.state.get("stop_reason", "stopped")
            elif self.clock() + CAPS["request_wait"] + 10 >= self.state["deadline"]:
                reason = "dispatch_deadline"
            elif self.state["attempts"] >= CAPS["requests"]:
                reason = "request_limit"
            elif self.state["requested_output_tokens"] + payload["max_tokens"] > CAPS["output_tokens"]:
                reason = "output_limit"
            if reason:
                self.state.update(status="stopped", stop_reason=reason)
                helpers.write(self.path, self.state)
                raise RuntimeError("shared diagnostic admission stopped")
            self.state["attempts"] += 1
            self.state["requested_output_tokens"] += payload["max_tokens"]
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
            helpers.write(self.path, self.state)
        return receipt


def run(directory, phase, sender, *, clock=time.time):
    directory = Path(directory).resolve()
    plan = check(directory)
    if phase not in PHASES:
        raise ValueError("unknown phase")
    live = directory / "live"
    source = live / "snapshots" / ("candidate" if phase == "hits" else phase)
    manifest, _ = helpers.check_snapshot(source)
    rows = inputs(directory / ("hit-inputs.json" if phase == "hits" else "day1-inputs.json"), 8 if phase == "hits" else 6)
    if phase == "hits":
        hit_plan, _ = helpers.unseal(directory / "hit-plan.json")
        if (hit_plan["input_sha256"] != helpers.file_hash(directory / "hit-inputs.json")
                or hit_plan["source_sha256"] != manifest["source_sha256"]):
            raise ValueError("stale hit selection")
    lock = live / "active.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    state_path = live / "execution.json"
    try:
        if state_path.exists():
            state = helpers.read(state_path)
        else:
            now = clock()
            local = time.localtime(now)
            midnight = time.mktime((local.tm_year, local.tm_mon, local.tm_mday + 1, 0, 0, 0, 0, 0, -1))
            state = {"started_at": now, "deadline": min(now + CAPS["seconds"], midnight - 1200),
                     "status": "ready", "phases": [], "attempts": 0, "completed_responses": 0,
                     "requested_output_tokens": 0, "known_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                     "plan_sha256": helpers.file_hash(live / "plan.json")}
        if state["plan_sha256"] != helpers.file_hash(live / "plan.json"):
            raise ValueError("modified execution binding")
        if state["status"] not in ("ready",) or phase in state["phases"]:
            raise ValueError("no retry or automatic resume")
        if clock() + 360 >= state["deadline"]:
            raise ValueError("insufficient bounded finish time")
        state["phases"].append(phase)
        state["status"] = "running"
        helpers.write(state_path, state)
        admission = Admission(state_path, state, sender, clock)

        def job(position, row):
            output = live / "runs" / phase / f"item-{position:02d}"
            output.mkdir(parents=True, exist_ok=False)
            began, events, result, error = clock(), [], None, None
            remaining = state["deadline"] - clock() - 360
            if remaining <= 0 or state["status"] == "stopped":
                helpers.write(output / "result.json", {"status": "not_started"})
                return
            relay = output / "relay"
            count = 1 if phase == "hits" else 16
            control.create(relay, control.Limits(count, count * 8192, remaining, 350), model=MODEL,
                           identity={"source_sha256": manifest["source_sha256"], "config_sha256": manifest["config_sha256"],
                                     "input_sha256": sha256(row["problem"].encode()).hexdigest()})
            worker = threading.Thread(target=control.serve, args=(relay, admission.send), daemon=True)
            worker.start()
            try:
                module = helpers.load_source(source)
                agent = helpers.observed_agent(module, control.RelayClient(relay), events)
                result = agent.solve(row["problem"], {})
            except control.PilotStopped:
                error = "bounded_probe_rejected" if phase == "hits" else "pilot_stopped"
            except BaseException as exc:
                error = type(exc).__name__
                admission.stop("local_execution_failure")
            finally:
                control.pause(relay, reason="finished")
                worker.join(timeout=355)
                receipt = control.status(relay)
                helpers.write(output / "result.json", {
                    "status": "completed" if result is not None else "interrupted", "error_category": error,
                    "position": position, "idx": row["idx"], "problem_sha256": sha256(row["problem"].encode()).hexdigest(),
                    "source_sha256": manifest["source_sha256"], "config": manifest["config"],
                    "seconds": clock() - began, "observation": events, "result": result, "receipt": receipt})
                print(json.dumps({"phase": phase, "position": position, "completed": result is not None,
                                  "requests": receipt["attempts"]}), flush=True)

        def guarded_job(position, row):
            try:
                return job(position, row)
            except BaseException:
                admission.stop("local_execution_failure")
                raise

        with ThreadPoolExecutor(max_workers=CAPS["concurrency"]) as pool:
            futures = [pool.submit(guarded_job, i, row) for i, row in enumerate(rows)]
            for future in futures:
                future.result()
        with admission.lock:
            if state["status"] == "running":
                state["status"] = "completed" if set(state["phases"]) == set(PHASES) else "ready"
            state["unknown_usage_requests"] = state["attempts"] - state["completed_responses"]
            helpers.write(state_path, state)
        return state
    finally:
        os.close(descriptor)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "snapshot", "run"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--phase", choices=PHASES, default="baseline")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.directory)
    elif args.command == "snapshot":
        check(args.directory)
        result = frozen_source(args.directory / "live/snapshots/candidate", ROOT)
    elif not args.execute:
        check(args.directory)
        result = {"status": "validated_not_executed", "caps": CAPS}
    else:
        from dotenv import dotenv_values
        key = os.environ.get("INTERN_API_KEY") or dotenv_values(ROOT / ".env").get("INTERN_API_KEY")
        if not key or not key.strip():
            raise ValueError("missing credential")
        authorization = key.strip() if key.strip().startswith("Bearer ") else "Bearer " + key.strip()
        result = run(args.directory, args.phase, control.make_http_sender(authorization, MODEL, wait_seconds=345))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
