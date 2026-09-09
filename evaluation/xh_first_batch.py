"""Frozen first-batch stage experiments. Prepare is offline; execute is explicit."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import threading

from evaluation import xh202627_pilot_control as control
from evaluation.q1_experiments import source_hash
from user_agent import Q1Policy, ReasoningAgent

ROOT = Path(__file__).resolve().parents[1]
MODEL = "intern-s2-preview-397b"
ENDPOINT = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
BATCHES = {"b1": (8, 65536), "b2": (16, 8192), "conditions": (12, 98304)}


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def write(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class Capture:
    def __init__(self):
        self.calls = []

    def chat(self, *, messages, temperature, max_tokens, thinking_mode):
        self.calls.append(dict(messages=messages, temperature=temperature, max_tokens=max_tokens, thinking_mode=thinking_mode))
        return "最终答案：2"


def stage_payload(problem, batch, enabled):
    flags = {"b1": "tool_aware_prompts", "b2": "concise_recovery", "conditions": "condition_checks"}
    capture = Capture()
    policy = Q1Policy(**{flags[batch]: enabled})
    agent = ReasoningAgent(capture, local_policy=policy)
    domain = agent._detect_domain(problem)
    # Use the actual runtime domain function, not a synthetic benchmark prompt.
    from user_agent import get_domain_prompt
    prompt = get_domain_prompt(domain)
    if batch == "b1":
        agent._solve_tools(problem, 0, prompt)
    elif batch == "b2":
        agent._quick_fallback(problem, [])
    else:
        agent._solve_plain(problem, prompt)
    if len(capture.calls) != 1:
        raise ValueError("stage extraction changed request count")
    return capture.calls[0], asdict(policy)


def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "live-plan.json"
    if path.exists():
        raise ValueError("fresh plan required")
    input_path = ROOT / "outputs/q0-umath-v4/dev.input.jsonl"
    rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    indices = {"b1": [0, 18, 36, 54], "b2": [0, 9, 18, 27, 36, 45, 54, 63], "conditions": [5, 17, 29, 41, 53, 65]}
    batches = {}
    for batch, positions in indices.items():
        requests = []
        for pair, index in enumerate(positions):
            row = rows[index]
            for enabled in ((False, True) if pair % 2 == 0 else (True, False)):
                payload, policy = stage_payload(row["problem"], batch, enabled)
                requests.append({"pair": pair, "input_idx": row["idx"], "input_position": index,
                    "problem_sha256": sha256(row["problem"].encode()).hexdigest(), "enabled": enabled,
                    "policy": policy, "payload": payload})
        if len(requests) != BATCHES[batch][0] or sum(r["payload"]["max_tokens"] for r in requests) != BATCHES[batch][1]:
            raise ValueError("batch allowance mismatch")
        batches[batch] = requests
    plan = {"schema_version": 1, "model": MODEL, "runtime_sha256": source_hash(),
        "experiment_sha256": sha256(Path(__file__).read_bytes()).hexdigest(), "input_sha256": sha256(input_path.read_bytes()).hexdigest(),
        "scope": "single-stage B1/B2/conditions; no full-agent accuracy or retrieval promotion",
        "authorization": "User approved first-batch implementation, full validation, and needed online API checks; total capped at 36",
        "retrieval": "not run unless coverage gate passes; remaining 12 requests allocated to first-batch condition-check pairs",
        "request_ceiling": 36, "output_token_ceiling": 172032, "dispatch_seconds_per_batch": 600,
        "batches": batches}
    plan["sha256"] = digest(plan)
    write(path, plan)
    return {"plan_sha256": plan["sha256"], "requests": 36, "output_token_ceiling": 172032, "status": "prepared_not_executed"}


def execute(directory):
    # This function is called only by explicit --execute, never by tests or import.
    plan = json.loads((directory / "live-plan.json").read_text(encoding="utf-8"))
    claimed = plan.pop("sha256")
    if (digest(plan) != claimed or plan["runtime_sha256"] != source_hash()
            or plan["experiment_sha256"] != sha256(Path(__file__).read_bytes()).hexdigest()
            or plan["request_ceiling"] != 36 or plan["output_token_ceiling"] != 172032):
        raise ValueError("stale or unauthorized plan")
    if (directory / "execution.json").exists():
        raise ValueError("execution already used; no automatic resume")
    from dotenv import dotenv_values
    settings = dotenv_values(ROOT / ".env")
    key = os.environ.get("INTERN_API_KEY") or settings.get("INTERN_API_KEY")
    if not key or not key.strip():
        raise ValueError("missing credential")
    authorization = key.strip() if key.strip().startswith("Bearer ") else "Bearer " + key.strip()
    execution = {"plan_sha256": claimed, "status": "running", "batches": {}}
    write(directory / "execution.json", execution)
    sender = control.make_http_sender(authorization, MODEL)
    try:
        for batch, (request_limit, output_limit) in BATCHES.items():
            ipc = directory / batch
            expected = plan["batches"][batch]
            control.create(ipc, control.Limits(request_limit, output_limit, 600), model=MODEL,
                identity={"source_sha256": plan["runtime_sha256"], "config_sha256": digest([r["policy"] for r in expected]),
                          "input_sha256": digest([r["payload"] for r in expected])})
            thread = threading.Thread(target=control.serve, args=(ipc, sender), daemon=True)
            thread.start()
            client = control.RelayClient(ipc)
            completed = []
            try:
                for number, item in enumerate(expected, 1):
                    response = client.chat(**item["payload"])
                    completed.append({"ordinal": number, "pair": item["pair"], "input_idx": item["input_idx"],
                                      "enabled": item["enabled"], "response": response})
                    write(ipc / "stage-results.json", completed)
                    print(json.dumps({"batch": batch, "completed": number, "limit": request_limit}), flush=True)
            except control.PilotStopped as error:
                execution["status"] = "stopped"
                execution["stop_reason"] = str(error)
            finally:
                control.pause(ipc, reason="finished")
                thread.join(timeout=5)
                execution["batches"][batch] = control.status(ipc)
                write(directory / "execution.json", execution)
            if execution["status"] == "stopped":
                return execution
        execution["status"] = "completed"
        write(directory / "execution.json", execution)
        return execution
    finally:
        # Each sender already owns a bounded subprocess and closes its HTTP session.
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    result = execute(args.directory) if args.execute else prepare(args.directory)
    print(json.dumps({k: v for k, v in result.items() if k != "batches"}), flush=True)


if __name__ == "__main__":
    main()
