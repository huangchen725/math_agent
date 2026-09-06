"""Frozen ablation plans and an injected-client runner. CLI is offline only."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import time
from uuid import uuid4

from evaluation.audit_dataset import load_jsonl
from evaluation.q0_pipeline import digest, verify_bundle
from user_agent import AgentConfig, Q1Policy, ReasoningAgent

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("baseline", "recover_plain", "deterministic", "compact_routing",
            "calibrated_verifier", "diverse_candidates", "no_critic", "no_reflection",
            "no_tools", "combined")


def source_hash():
    files = ("user_agent.py", "agent_types.py", "budget.py", "answer_equivalence.py",
             "domain_prompts.py", "llm_client.py", "math_tools.py", "tool_executor.py",
             "local_support/xh202627_local_adapter.py", "evaluation/q1_experiments.py",
             "evaluation/q0_pipeline.py", "evaluation/score_run.py", "evaluation/judge.py",
             "deterministic_verifier.py")
    return digest({name: sha256((ROOT/name).read_bytes()).hexdigest() for name in files})


def make_plan(bundle: Path, *, split="dev", model="intern-s2-preview-397b", local_tools=False):
    if split not in {"dev", "test"} or type(model) is not str or not model.strip() or type(local_tools) is not bool:
        raise ValueError("invalid split/model")
    manifest = verify_bundle(bundle)
    total = len(load_jsonl(bundle/f"{split}.input.jsonl"))
    variants = {}
    for name in VARIANTS:
        config = asdict(AgentConfig())
        policy = asdict(Q1Policy())
        if name in policy:
            policy[name] = True
        elif name == "combined":
            policy = dict.fromkeys(policy, True)
        elif name == "no_critic":
            config["enable_critic"] = False
        elif name == "no_reflection":
            config["enable_reflection"] = False
        elif name == "no_tools":
            config["enable_tools"] = False
        variants[name] = {"agent": config, "policy": policy}
    return {"schema_version": 1, "dataset_sha256": manifest["dataset_sha256"],
        "input_sha256": manifest["files"][f"{split}.input.jsonl"], "split": split,
        "code_sha": source_hash(), "model": model, "total_items": total,
        "per_variant_request_ceiling": total*AgentConfig().max_model_requests,
        "all_variants_request_ceiling": total*AgentConfig().max_model_requests*len(variants),
        "variants": variants, "local_tools": local_tools,
        "status": "planned_not_executed", "promotion": "require real paired evidence; fixtures cannot promote",
        "scope": "explicit local adapter experiment" if local_tools else "text-only injected protocol"}


def run_plan(plan, variant, bundle: Path, output: Path, client, *, execution="fixture", local_adapter=None, run_ticket=None):
    """Call only a supplied client; caller owns real-API authorization outside this offline CLI."""
    manifest = verify_bundle(bundle)
    if execution not in {"fixture", "real"} or variant not in plan["variants"]:
        raise ValueError("invalid run type or variant")
    if (manifest["dataset_sha256"] != plan["dataset_sha256"]
            or manifest["files"][f"{plan['split']}.input.jsonl"] != plan["input_sha256"]
            or source_hash() != plan["code_sha"]):
        raise ValueError("stale plan")
    if bool(local_adapter is not None) != plan["local_tools"]:
        raise ValueError("tool capability differs from plan")
    expected_plan = make_plan(bundle, split=plan["split"], model=plan["model"], local_tools=plan["local_tools"])
    if plan != expected_plan:
        raise ValueError("plan differs from frozen ablation specification")
    if output.exists():
        raise ValueError("fresh run directory required; no mixed checkpoints")
    if run_ticket is not None and (type(run_ticket) is not dict or
            set(run_ticket) != {"protocol_sha256", "slot", "nonce", "reserved_at"}):
        raise ValueError("invalid offline experiment ticket")
    settings = plan["variants"][variant]
    agent = ReasoningAgent(client, AgentConfig(**settings["agent"]),
        local_policy=Q1Policy(**settings["policy"]), local_adapter=local_adapter)
    rows = load_jsonl(bundle/f"{plan['split']}.input.jsonl")
    output.mkdir(parents=True)
    summary_dir = output/"_run"
    summary_dir.mkdir()
    summary = {"input_sha256": plan["input_sha256"], "dataset_sha256": plan["dataset_sha256"],
        "run_id": uuid4().hex, "started_at": time.time(),
        "run_ticket_sha256": digest(run_ticket) if run_ticket is not None else None,
        "model": plan["model"], "code_sha": plan["code_sha"], "config": settings,
        "execution": execution, "variant": variant, "plan_sha256": digest(plan), "local_tools": plan["local_tools"],
        "status": "running", "completed_items": 0}
    def write_summary():
        path = summary_dir/"run_summary.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        temporary.replace(path)
    write_summary()
    started = time.monotonic()
    for row in rows:
        result = agent.solve(row["problem"], {"idx": row["idx"]})
        record = {"idx": row["idx"], "status": "error" if result["final_response"] == "未解出" else "success", **result}
        path = output/(row["idx"]+".json")
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False)+"\n", encoding="utf-8")
        temporary.replace(path)
        summary["completed_items"] += 1
        write_summary()
    summary.update(status="complete", duration_ms=round((time.monotonic()-started)*1000),
        output_files_sha256={r["idx"]+".json": sha256((output/(r["idx"]+".json")).read_bytes()).hexdigest() for r in rows})
    write_summary()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split", choices=("dev", "test"), default="dev")
    parser.add_argument("--local-tools", action="store_true", help="Plan an explicit local-adapter experiment")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite plan")
    plan = make_plan(args.bundle, split=args.split, local_tools=args.local_tools)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: plan[k] for k in ("total_items", "per_variant_request_ceiling", "status")}))


if __name__ == "__main__":
    main()
