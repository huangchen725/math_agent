"""Bounded formatting-repair confirmation, never a full-pair rerun.

It carries forward the completed first-day batch's cost and deadline. The eight
fixed probes are unchanged; source labels remain outside model execution.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import threading
import time

from evaluation import xh_day1_diagnostic as day1
from evaluation import xh_accuracy_diagnostic as helper
from evaluation import xh202627_pilot_control as control


def preceding_batch(directory):
    day1.check(directory)
    prior = helper.read(directory / "live/execution.json")
    hit_plan, _ = helper.unseal(directory / "hit-plan.json")
    if hit_plan["input_sha256"] != helper.file_hash(directory / "hit-inputs.json"):
        raise ValueError("original fixed probes changed")
    if (prior["status"] != "completed" or prior["unknown_usage_requests"]
            or prior.get("phases") != list(day1.PHASES)
            or prior.get("plan_sha256") != helper.file_hash(directory / "live/plan.json")
            or any(type(prior.get(k)) is not int or prior[k] < 0
                   for k in ("attempts", "completed_responses", "requested_output_tokens"))
            or prior["attempts"] != prior["completed_responses"]
            or prior["attempts"] > day1.CAPS["requests"]
            or prior["requested_output_tokens"] > day1.CAPS["output_tokens"]):
        raise ValueError("preceding batch must be completed and reconciled")
    if (any(type(prior.get(k)) not in (int, float) or not math.isfinite(prior[k])
            for k in ("started_at", "deadline"))
            or not 0 < prior["deadline"] - prior["started_at"] <= day1.CAPS["seconds"]):
        raise ValueError("invalid original time allowance")
    return prior


def prepare(directory):
    directory = Path(directory).resolve()
    prior = preceding_batch(directory)
    day1.inputs(directory / "hit-inputs.json", 8)
    target = directory / "confirmation"
    target.mkdir(exist_ok=False)
    snapshot = day1.frozen_source(target / "snapshot", day1.ROOT)
    manifest = {"reason": "documented exact-answer formatting failures; no full-pair resampling",
                "prior_state_sha256": helper.file_hash(directory / "live/execution.json"),
                "original_hit_plan_sha256": helper.file_hash(directory / "hit-plan.json"),
                "input_sha256": helper.file_hash(directory / "hit-inputs.json"),
                "source_sha256": snapshot["source_sha256"], "model": day1.MODEL,
                "global_caps": day1.CAPS, "additional_request_cap": 8,
                "tool_sha256": helper.file_hash(__file__),
                "admission_sha256": helper.file_hash(day1.__file__),
                "helper_sha256": helper.file_hash(helper.__file__),
                "controller_sha256": helper.file_hash(control.__file__)}
    helper.write(target / "plan.json", helper.seal(manifest))
    return {"status": "prepared_not_executed", "additional_requests": 8,
            "preceding_attempts": prior["attempts"], "original_deadline": prior["deadline"]}


def check(directory):
    target = directory / "confirmation"
    plan, _ = helper.unseal(target / "plan.json")
    for name, path in (("tool_sha256", Path(__file__)), ("admission_sha256", Path(day1.__file__)),
                       ("helper_sha256", Path(helper.__file__)), ("controller_sha256", Path(control.__file__)),
                       ("prior_state_sha256", directory / "live/execution.json"),
                       ("original_hit_plan_sha256", directory / "hit-plan.json"),
                       ("input_sha256", directory / "hit-inputs.json")):
        if plan[name] != helper.file_hash(path):
            raise ValueError("modified confirmation binding")
    if plan["global_caps"] != day1.CAPS or plan["additional_request_cap"] != 8 or plan["model"] != day1.MODEL:
        raise ValueError("modified confirmation allowance")
    snapshot, _ = helper.check_snapshot(target / "snapshot")
    if snapshot["source_sha256"] != plan["source_sha256"]:
        raise ValueError("modified confirmation source")
    rows = day1.inputs(directory / "hit-inputs.json", 8)
    return plan, snapshot, rows


def run(directory, sender, *, clock=time.time):
    directory = Path(directory).resolve()
    plan, snapshot, rows = check(directory)
    target = directory / "confirmation"
    prior = preceding_batch(directory)
    if (prior["attempts"] + 8 > day1.CAPS["requests"]
            or prior["requested_output_tokens"] + 8 * 8192 > day1.CAPS["output_tokens"]
            or clock() + 360 >= prior["deadline"]):
        raise ValueError("remaining original allowance insufficient")
    lock = target / "active.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    state_path = target / "execution.json"
    try:
        if state_path.exists():
            raise ValueError("confirmation cannot restart or resume")
        state = {"status": "running", "started_at": clock(), "deadline": prior["deadline"],
                 "prior_state_sha256": plan["prior_state_sha256"], "preceding_attempts": prior["attempts"],
                 "attempts": prior["attempts"], "completed_responses": prior["completed_responses"],
                 "requested_output_tokens": prior["requested_output_tokens"],
                 "known_usage": dict(prior["known_usage"])}
        helper.write(state_path, state)
        admission = day1.Admission(state_path, state, sender, clock)

        def job(position, row):
            output = target / f"item-{position:02d}"
            output.mkdir(exist_ok=False)
            if state["status"] == "stopped" or clock()+360 >= state["deadline"]:
                helper.write(output / "result.json", {"status": "not_started"})
                return
            relay = output / "relay"
            control.create(relay, control.Limits(1, 8192, state["deadline"]-clock()-360, 350), model=day1.MODEL,
                           identity={"source_sha256": snapshot["source_sha256"], "config_sha256": snapshot["config_sha256"],
                                     "input_sha256": sha256(row["problem"].encode()).hexdigest()})
            worker = threading.Thread(target=control.serve, args=(relay, admission.send), daemon=True)
            worker.start()
            events, result, error = [], None, None
            began = clock()
            try:
                module = helper.load_source(target / "snapshot")
                result = helper.observed_agent(module, control.RelayClient(relay), events).solve(row["problem"], {})
            except control.PilotStopped:
                error = "probe_rejected_or_transport_stopped"
            except BaseException as exc:
                error = type(exc).__name__
                admission.stop("local_execution_failure")
            finally:
                control.pause(relay, reason="finished")
                worker.join(timeout=355)
                receipt = control.status(relay)
                helper.write(output / "result.json", {"position": position, "idx": row["idx"],
                    "problem_sha256": sha256(row["problem"].encode()).hexdigest(),
                    "source_sha256": snapshot["source_sha256"], "config": snapshot["config"],
                    "status": "completed" if result is not None else "rejected", "error_category": error,
                    "seconds": clock()-began, "observation": events, "result": result, "receipt": receipt})
                print(json.dumps({"position": position, "completed": result is not None, "requests": receipt["attempts"]}), flush=True)

        def guarded_job(position, row):
            try:
                return job(position, row)
            except BaseException:
                # Stop in the failing worker itself, even if an earlier future
                # is still awaiting I/O. Already in-flight sends remain counted.
                admission.stop("local_execution_failure")
                raise

        failure = None
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(guarded_job, i, row) for i, row in enumerate(rows)]
            try:
                for future in futures:
                    future.result()
            except BaseException as exc:
                admission.stop("local_execution_failure")
                for future in futures:
                    future.cancel()
                failure = type(exc).__name__
        with admission.lock:
            if state["status"] == "running":
                state["status"] = "completed"
            state["additional_attempts"] = state["attempts"] - prior["attempts"]
            state["unknown_usage_requests"] = state["attempts"] - state["completed_responses"]
            helper.write(state_path, state)
        if failure:
            raise RuntimeError("confirmation local preparation failed") from None
        return state
    finally:
        os.close(descriptor)
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.directory)
    elif not args.execute:
        check(args.directory.resolve())
        result = {"status": "validated_not_executed"}
    else:
        from dotenv import dotenv_values
        key = os.environ.get("INTERN_API_KEY") or dotenv_values(day1.ROOT / ".env").get("INTERN_API_KEY")
        if not key or not key.strip():
            raise ValueError("missing credential")
        authorization = key.strip() if key.strip().startswith("Bearer ") else "Bearer " + key.strip()
        result = run(args.directory, control.make_http_sender(authorization, day1.MODEL, wait_seconds=345))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
