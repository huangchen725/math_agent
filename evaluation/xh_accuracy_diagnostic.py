"""Local full-solve observation on three exposed public development questions.

Preparation never starts network work. Only ``run --execute`` sends requests.
The observer calls the frozen source's ordinary default constructor, never reads
labels, and records private diagnostics separately from the public trace.
"""
from __future__ import annotations

import argparse
import ast
import copy
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from uuid import uuid4

from evaluation import xh202627_pilot_control as control

ROOT = Path(__file__).resolve().parents[1]
MODEL = "intern-s2-preview-397b"
BASELINE = "b87e4b9f2f7383960c659b887c39daa809f228cb"
POSITIONS = (0, 27, 29)
ALLOWANCE = {"requests_per_variant": 48, "output_tokens_per_variant": 150000,
             "variants": 2, "wall_seconds": 5400, "request_wait_seconds": 350}
# Windows readers can prevent replacing an open destination. Coordinate only
# same-process file handles; do not hold this lock during JSON work or network I/O.
_JSON_IO_LOCK = threading.RLock()


def digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    data = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode()
    if len(data) > 8_000_000:
        raise ValueError("oversized diagnostic record")
    temporary = path.with_suffix(".tmp")
    with _JSON_IO_LOCK:
        temporary.write_bytes(data)
        temporary.replace(path)


def read(path):
    with _JSON_IO_LOCK:
        data = Path(path).read_bytes()
    if len(data) > 8_000_000:
        raise ValueError("oversized diagnostic record")
    return json.loads(data)


def safe_path(root, name):
    if type(name) is not str or not name or "\\" in name or ":" in name:
        raise ValueError("invalid relative artifact path")
    target = (root / name).resolve()
    if not target.is_relative_to(root.resolve()) or target == root.resolve():
        raise ValueError("artifact path escapes root")
    return target


def seal(value):
    return {**value, "sha256": digest(value)}


def unseal(path):
    value = read(path)
    expected = value.pop("sha256")
    if digest(value) != expected:
        raise ValueError("modified manifest")
    return value, expected


def git_bytes(revision, name):
    return subprocess.check_output(["git", "show", f"{revision}:{name}"], cwd=ROOT)


def formal_files(source):
    tree = ast.parse(source)
    for item in tree.body:
        if isinstance(item, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_FORMAL_SOURCE_FILES" for t in item.targets):
            names = ast.literal_eval(item.value)
            if type(names) is not tuple or any(type(n) is not str or Path(n).name != n or not n.endswith(".py") for n in names):
                raise ValueError("invalid formal source closure")
            return ("user_agent.py", *names)
    raise ValueError("formal source closure missing")


def prepare(directory):
    """Freeze exposed dev inputs; references remain in a separate audit file."""
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    bundle = ROOT / "outputs/q0-umath-v4"
    dataset = read(bundle / "manifest.json")
    for name in ("dev.input.jsonl", "dev.labels.jsonl"):
        if file_hash(bundle / name) != dataset["files"][name]:
            raise ValueError("modified public development dataset")
    inputs = [json.loads(line) for line in (bundle / "dev.input.jsonl").read_text(encoding="utf-8").splitlines()]
    labels = [json.loads(line) for line in (bundle / "dev.labels.jsonl").read_text(encoding="utf-8").splitlines()]
    selected, audit = [], []
    for position in POSITIONS:
        item, label = inputs[position], labels[position]
        if item["idx"] != label["idx"] or item["problem"] != label["problem"] or label["split"] != "dev" or label["license"] != "MIT":
            raise ValueError("public development provenance mismatch")
        selected.append({"idx": item["idx"], "problem": item["problem"]})
        audit.append({**label, "input_position": position, "selection": "previously exposed diagnostic failure; not holdout",
                      "reference_status": "unreviewed source answer; mathematical review separate"})
    write(directory / "inputs.json", selected)
    write(directory / "reference-audit.json", audit)
    plan = {"schema_version": 1, "model": MODEL, "allowance": ALLOWANCE,
            "input_sha256": file_hash(directory / "inputs.json"),
            "source_dataset_sha256": dataset["dataset_sha256"],
            "reference_audit_sha256": file_hash(directory / "reference-audit.json"),
            "tool_sha256": file_hash(__file__), "controller_sha256": file_hash(control.__file__),
            "scope": "three selected exposed public dev diagnostics, full default solve; no official accuracy estimate",
            "authorization": "2026-09-10 user requested execution with necessary live diagnostics; at most two variants, 96 sends, 300000 requested output tokens, 90 minutes; no retry or resume"}
    write(directory / "plan.json", seal(plan))
    return {"status": "prepared_not_executed", "inputs": len(selected), **ALLOWANCE}


def check_plan(directory):
    plan, _ = unseal(directory / "plan.json")
    if (plan["allowance"] != ALLOWANCE or plan["model"] != MODEL
            or plan["tool_sha256"] != file_hash(__file__)
            or plan["controller_sha256"] != file_hash(control.__file__)
            or plan["input_sha256"] != file_hash(directory / "inputs.json")):
        raise ValueError("stale diagnostic plan")
    inputs = read(directory / "inputs.json")
    if len(inputs) != 3 or len({r["idx"] for r in inputs}) != 3:
        raise ValueError("three unique diagnostic inputs required")
    for row in inputs:
        if (set(row) != {"idx", "problem"} or type(row["idx"]) is not str
                or type(row["problem"]) is not str or not 0 < len(row["problem"]) <= 20000):
            raise ValueError("input contains unsupported fields")
    return plan, inputs


def snapshot(directory, variant):
    """Baseline uses git objects; candidate freezes the current working source."""
    directory = Path(directory).resolve()
    check_plan(directory)
    if variant not in ("baseline", "candidate"):
        raise ValueError("invalid variant")
    target = directory / "snapshots" / variant
    target.mkdir(parents=True, exist_ok=False)
    get = (lambda name: git_bytes(BASELINE, name)) if variant == "baseline" else (lambda name: (ROOT / name).read_bytes())
    files = list(formal_files(get("user_agent.py")))
    revision = BASELINE if variant == "baseline" else "HEAD"
    resources = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", revision, "resources"], cwd=ROOT, text=True).splitlines()
    files += resources
    hashes = {}
    for name in files:
        path = safe_path(target, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(get(name))
        hashes[name] = file_hash(path)
    module = load_source(target)
    agent = module.ReasoningAgent(object())
    config = {"agent": asdict(agent.config), "policy": asdict(agent.local_policy)}
    if variant == "baseline" and any(config["policy"].values()):
        raise ValueError("baseline policy is not all false")
    manifest = {"variant": variant, "origin": BASELINE if variant == "baseline" else "working-tree",
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "files": hashes, "source_sha256": digest(hashes), "config": config,
                "config_sha256": digest(config), "constructor": "ReasoningAgent(client)"}
    write(target / "snapshot.json", seal(manifest))
    return {"status": "frozen", **manifest}


def load_source(directory):
    name = "xh202627_diagnostic_" + uuid4().hex
    spec = importlib.util.spec_from_file_location(name, directory / "user_agent.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def check_snapshot(directory):
    manifest, _ = unseal(directory / "snapshot.json")
    for name, expected in manifest["files"].items():
        if file_hash(safe_path(directory, name)) != expected:
            raise ValueError("modified frozen source or resource")
    expected_files = formal_files((directory / "user_agent.py").read_bytes())
    if any(name not in manifest["files"] for name in expected_files):
        raise ValueError("unbound formal dependency")
    module = load_source(directory)
    agent = module.ReasoningAgent(object())
    config = {"agent": asdict(agent.config), "policy": asdict(agent.local_policy)}
    if (digest(manifest["files"]) != manifest["source_sha256"] or config != manifest["config"]
            or digest(config) != manifest["config_sha256"]):
        raise ValueError("modified default configuration")
    return manifest, module


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, (list, tuple)):
        return [plain(x) for x in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if value is None or type(value) in (str, bool, int, float):
        return value
    # Canonical answer keys may contain Fraction; no executable deserialization.
    return str(value)


def observed_agent(module, client, events):
    """Observer oracle: same constructor, arguments, returns and exceptions."""
    class Observed(module.ReasoningAgent):
        pass

    def wrap(name):
        original = getattr(module.ReasoningAgent, name)

        def call(self, *args, **kwargs):
            before = plain(copy.deepcopy(args))
            try:
                result = original(self, *args, **kwargs)
            except BaseException as error:
                events.append({"stage": name, "before": before, "status": "interrupted",
                               "error_category": type(error).__name__})
                raise
            events.append({"stage": name, "before": before, "result": plain(result), "status": "completed"})
            return result
        return call

    for name in ("_detect_domain", "_generate_candidates", "_verify", "_reflect", "_apply_exact_evidence", "_aggregate"):
        if hasattr(module.ReasoningAgent, name):
            setattr(Observed, name, wrap(name))
    return Observed(client)


def strict_sender(sender):
    def send(payload):
        if (type(payload) is not dict
                or set(payload) != {"messages", "temperature", "max_tokens", "thinking_mode"}
                or payload["thinking_mode"] is not False
                or type(payload["max_tokens"]) is not int
                or not 1 <= payload["max_tokens"] <= 8192):
            raise ValueError("diagnostic request violates frozen public protocol")
        return sender(payload)
    return send


def run(directory, variant, sender, *, clock=time.time):
    """Run once with a supplied single-send transport. Never reads reference data."""
    directory = Path(directory).resolve()
    plan, inputs = check_plan(directory)
    if variant not in ("baseline", "candidate"):
        raise ValueError("invalid variant")
    manifest, module = check_snapshot(directory / "snapshots" / variant)
    lock = directory / "active.lock"
    lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    state_path = directory / "execution.json"
    thread = None
    ipc = None
    state = None
    try:
        state = read(state_path) if state_path.exists() else {
            "started_at": clock(), "deadline": clock() + ALLOWANCE["wall_seconds"],
            "used_variants": [], "status": "ready", "runs": {}}
        remaining = state["deadline"] - clock()
        if state["status"] == "stopped" or variant in state["used_variants"] or len(state["used_variants"]) >= 2:
            raise ValueError("used or stopped execution; no automatic resume")
        if remaining <= ALLOWANCE["request_wait_seconds"]:
            state.update(status="stopped", stop_reason="batch_deadline")
            write(state_path, state)
            raise ValueError("batch deadline exhausted")
        state["used_variants"].append(variant)
        state["status"] = "running"
        write(state_path, state)
        output = directory / "runs" / variant
        output.mkdir(parents=True, exist_ok=False)
        ipc = output / "relay"
        control.create(ipc, control.Limits(48, 150000, remaining - 350, 350), model=MODEL,
                       identity={"source_sha256": manifest["source_sha256"],
                                 "config_sha256": manifest["config_sha256"], "input_sha256": plan["input_sha256"]})
        thread = threading.Thread(target=control.serve, args=(ipc, strict_sender(sender)), daemon=True)
        thread.start()
        client = control.RelayClient(ipc)
        completed = []
        for position, row in enumerate(inputs):
            events = []
            before = control.status(ipc)["attempts"]
            began = clock()
            result = None
            try:
                agent = observed_agent(module, client, events)
                result = agent.solve(row["problem"], {})
            finally:
                receipt = control.status(ipc)
                item = {"position": position, "idx": row["idx"], "problem_sha256": sha256(row["problem"].encode()).hexdigest(),
                        "source_sha256": manifest["source_sha256"], "config": manifest["config"],
                        "request_ordinals": list(range(before + 1, receipt["attempts"] + 1)),
                        "seconds": clock() - began, "observation": events, "result": result,
                        "status": "completed" if result is not None else "interrupted"}
                write(output / f"item-{position:02d}.json", item)
            completed.append(position)
            print(json.dumps({"variant": variant, "completed": len(completed), "of": len(inputs), "requests": receipt["attempts"]}), flush=True)
        state["status"] = "completed" if len(state["used_variants"]) == 2 else "ready"
    except BaseException as error:
        if state is not None and state.get("status") == "running":
            state.update(status="stopped", stop_reason=type(error).__name__)
        raise
    finally:
        if ipc is not None and (ipc / "state.json").exists():
            control.pause(ipc, reason="finished")
            if thread is not None:
                thread.join(timeout=5)
            state["runs"][variant] = control.status(ipc)
            state["runs"][variant]["snapshot_sha256"] = file_hash(directory / "snapshots" / variant / "snapshot.json")
            state["runs"][variant]["artifact_hashes"] = {
                str(path.relative_to(output)).replace("\\", "/"): file_hash(path)
                for path in sorted(output.rglob("*.json"))
            }
        if state is not None:
            write(state_path, state)
        os.close(lock_fd)
        lock.unlink()
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "snapshot", "run"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("--variant", choices=("baseline", "candidate"), default="baseline")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.directory)
    elif args.command == "snapshot":
        result = snapshot(args.directory, args.variant)
    elif not args.execute:
        check_plan(args.directory)
        check_snapshot(args.directory / "snapshots" / args.variant)
        result = {"status": "validated_not_executed", "variant": args.variant, "limits": ALLOWANCE}
    else:
        # Credentials stay in the worker memory, absent from manifests and diagnostics.
        from dotenv import dotenv_values
        key = os.environ.get("INTERN_API_KEY") or dotenv_values(ROOT / ".env").get("INTERN_API_KEY")
        if not key or not key.strip():
            raise ValueError("missing credential")
        authorization = key.strip() if key.strip().startswith("Bearer ") else "Bearer " + key.strip()
        result = run(args.directory, args.variant, control.make_http_sender(authorization, MODEL, wait_seconds=345))
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    try:
        main()
    except control.PilotStopped:
        print(json.dumps({"status": "stopped", "action": "inspect receipts; no automatic retry"}), flush=True)
        raise SystemExit(2)
