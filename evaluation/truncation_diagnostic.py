"""Bounded local Chat API diagnosis; planning is offline, execution is explicit.

This does not change or probe the competition-injected client. No raw responses,
reasoning, answers, credentials or error messages are written to result files.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import time

from evaluation.audit_dataset import load_jsonl
from evaluation.q0_pipeline import digest, verify_bundle
import user_agent as runtime

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://chat.intern-ai.org.cn/api/v1/chat/completions"
MODEL = "intern-s2-preview-397b"
CASES = (
    ("fallback", 512, None), ("fallback", 512, False), ("fallback", 4096, None),
    ("verifier", 1024, None), ("verifier", 1024, False), ("verifier", 4096, None),
    ("generation", 8192, None), ("generation", 8192, False), ("generation", 4096, None),
)


def make_plan(bundle: Path):
    manifest = verify_bundle(bundle)
    rows = load_jsonl(bundle / "dev.input.jsonl")[:2]
    labels = {row["idx"]: row for row in load_jsonl(bundle / "dev.labels.jsonl")}
    if len(rows) != 2:
        raise ValueError("two development items required")
    agent = runtime.ReasoningAgent(None)
    requests = []
    # Alternate item order between conditions to reduce a fixed time-order bias.
    for case_index, (stage, limit, thinking) in enumerate(CASES):
        for row in rows[::1 if case_index % 2 == 0 else -1]:
            problem = row["problem"]
            if stage == "generation":
                system = runtime.get_domain_prompt(agent._detect_domain(problem)) or runtime.POLICY_NO_TOOL_PROMPT
                user = problem + "\n\n请给出完整解答。"
                temperature = 0.6
            elif stage == "fallback":
                system = runtime.POLICY_NO_TOOL_PROMPT
                user = problem + "\n\n请直接给出最终答案，不要详细推导。单独一行按“最终答案：XXX”输出，XXX 只写答案本体。"
                temperature = 0.0
            else:
                system = runtime.VERIFIER_PROMPT
                # Public dev reference is only a verifier input, never a generation input.
                candidate = agent._review_excerpt(labels[row["idx"]]["answer"])
                user = f"题目：\n{problem}\n\n候选解答：\n{candidate}\n\n判断是否正确。只输出：VERDICT: A 或 VERDICT: B"
                temperature = 0.0
            requests.append({"idx": row["idx"], "stage": stage,
                "thinking_mode": thinking, "max_tokens": limit, "temperature": temperature,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    files = ("evaluation/truncation_diagnostic.py", "user_agent.py", "domain_prompts.py",
             "agent_types.py", "budget.py", "answer_equivalence.py", "evaluation/q0_pipeline.py",
             "evaluation/audit_dataset.py")
    return {"schema_version": 1, "status": "planned_not_executed", "model": MODEL,
        "endpoint": ENDPOINT, "split": "dev", "dataset_sha256": manifest["dataset_sha256"],
        "dev_input_sha256": manifest["files"]["dev.input.jsonl"],
        "dev_labels_sha256": manifest["files"]["dev.labels.jsonl"],
        "source_sha256": {p: sha256((ROOT / p).read_bytes()).hexdigest() for p in files},
        "request_ceiling": len(requests), "retry_ceiling": 0,
        "output_token_ceiling": sum(r["max_tokens"] for r in requests),
        "input_token_ceiling": None, "currency_cost": None,
        "scope": "two-item completion diagnostic, not an accuracy or official compatibility evaluation",
        "requests": requests}


def payload_for(plan, request):
    if type(request["max_tokens"]) is not int or not 1 <= request["max_tokens"] <= runtime.MAX_OUTPUT_TOKENS:
        raise ValueError("diagnostic output limit exceeds official bound")
    payload = {"model": plan["model"], "messages": request["messages"],
               "temperature": request["temperature"], "max_tokens": request["max_tokens"]}
    if request["thinking_mode"] is not None:
        payload["thinking_mode"] = request["thinking_mode"]
    return payload


def response_summary(data, request):
    if type(data) is not dict or type(data.get("choices")) is not list or len(data["choices"]) != 1:
        raise ValueError("invalid response envelope")
    choice = data["choices"][0]
    if type(choice) is not dict or type(choice.get("message")) is not dict:
        raise ValueError("invalid response choice")
    message = choice["message"]
    content = message.get("content")
    reasoning = message.get("reasoning_content")
    if content is not None and type(content) is not str:
        raise ValueError("invalid content")
    finish = choice.get("finish_reason")
    finish = finish if finish in ("stop", "length", "tool_calls", "content_filter") else "unknown"
    model = data.get("model")
    model = model if type(model) is str and re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", model) else None
    usage = data.get("usage") if type(data.get("usage")) is dict else {}
    counters = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = usage.get(key)
        counters[key] = value if type(value) is int and 0 <= value <= 10**9 else None
    text = content or ""
    return {"model_receipt": model, "finish_reason": finish, "usage": counters,
        "content_is_null": content is None, "content_chars": len(text),
        "reasoning_chars": len(reasoning) if type(reasoning) is str else None,
        "has_final_marker": bool(re.search(r"最终答案\s*[:：]|\\boxed\{", text)),
        "answer_eligible": bool(runtime.ReasoningAgent._extract_answer(
            runtime._response_text({"content": text, "finish_reason": finish}))),
        "exact_verdict": bool(re.fullmatch(r"\s*VERDICT\s*:\s*[AB]\s*", text)),
        "reported_completion_hits_requested_limit": counters["completion_tokens"] is not None
            and counters["completion_tokens"] >= request["max_tokens"]}


def write_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def execute(plan, bundle: Path, output: Path, approved_sha: str):
    # Recreate the entire specification before loading credentials or contacting the network.
    if digest(plan) != approved_sha or plan != make_plan(bundle):
        raise ValueError("stale or modified diagnostic plan")
    if output.exists():
        raise ValueError("fresh output directory required; never resume/retry paid probes")
    import os
    from dotenv import dotenv_values
    import requests

    raw_key = (os.environ.get("INTERN_API_KEY") or dotenv_values(ROOT / ".env").get("INTERN_API_KEY") or "").strip()
    if not raw_key:
        raise ValueError("missing credential")
    authorization = raw_key if raw_key.startswith("Bearer ") else "Bearer " + raw_key
    output.mkdir(parents=True)
    summary = {"execution": "real", "status": "running", "plan_sha256": approved_sha,
               "model_requested": plan["model"], "attempt_count": 0, "records": []}
    write_json(output / "summary.json", summary)
    for index, request in enumerate(plan["requests"]):
        record = {"index": index, "idx": request["idx"], "stage": request["stage"],
                  "thinking_mode": request["thinking_mode"], "max_tokens": request["max_tokens"]}
        summary["attempt_count"] += 1
        write_json(output / "summary.json", summary)
        started = time.monotonic()
        try:
            # stream here bounds HTTP response reading; payload never requests model streaming.
            with requests.post(ENDPOINT, headers={"Authorization": authorization},
                    json=payload_for(plan, request), timeout=(10, 180), allow_redirects=False,
                    stream=True) as response:
                record["http_status"] = response.status_code
                if response.status_code != 200:
                    raise ValueError("non-success status")
                chunks, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 2_000_000 or time.monotonic() - started > 240:
                        raise ValueError("response bound exceeded")
                    chunks.append(chunk)
                record.update(response_summary(json.loads(b"".join(chunks)), request))
            if record["model_receipt"] != plan["model"]:
                raise ValueError("missing or mismatched model receipt")
            record["status"] = "complete"
        except Exception:
            # Stop on the first uncertain, transport, rate or protocol failure. No retries.
            record["status"] = "stopped_error"
            summary["status"] = "stopped_error"
        record["elapsed_ms"] = round((time.monotonic() - started) * 1000)
        summary["records"].append(record)
        write_json(output / "summary.json", summary)
        print(json.dumps({k: record[k] for k in ("index", "stage", "max_tokens", "status", "elapsed_ms")}), flush=True)
        if summary["status"] == "stopped_error":
            break
    else:
        summary["status"] = "complete"
    write_json(output / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approved-plan-sha")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.execute:
        if not args.approved_plan_sha or not args.output:
            parser.error("execution requires --approved-plan-sha and --output")
        execute(json.loads(args.plan.read_text(encoding="utf-8")), args.bundle, args.output, args.approved_plan_sha)
    else:
        if args.plan.exists():
            parser.error("refusing to overwrite a frozen plan")
        plan = make_plan(args.bundle)
        args.plan.parent.mkdir(parents=True, exist_ok=True)
        write_json(args.plan, plan)
        print(json.dumps({"plan_sha256": digest(plan), "requests": plan["request_ceiling"],
                          "output_token_ceiling": plan["output_token_ceiling"], "status": plan["status"]}))


if __name__ == "__main__":
    main()
