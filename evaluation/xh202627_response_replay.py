"""Bounded, offline response diagnostics. Never imports an HTTP transport."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import re

import user_agent as runtime
from evaluation.q1_experiments import source_hash

_UNSET = object()
_REQUIRED_REQUEST_KEYS = {"messages", "temperature", "max_tokens"}
_REQUEST_KEYS = _REQUIRED_REQUEST_KEYS | {"thinking_mode", "tools", "tool_choice"}


def _request_payload(record):
    """Read legacy flat records or queue envelopes without guessing omitted settings."""
    if type(record) is not dict:
        raise ValueError("invalid recorded request")
    if "payload" in record:
        if set(record) - {"ordinal", "payload"}:
            raise ValueError("ambiguous recorded request envelope")
        payload = record["payload"]
    else:
        payload = {key: value for key, value in record.items() if key != "ordinal"}
    if (type(payload) is not dict or not _REQUIRED_REQUEST_KEYS <= payload.keys()
            or payload.keys() - _REQUEST_KEYS):
        raise ValueError("unsupported recorded request parameters")
    return payload


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 8_000_000:
        raise ValueError("oversized diagnostic input")
    return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("diagnostic path escapes root")
    return path


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def inspect_response(record):
    """Classify parser behavior, not mathematical correctness."""
    if record.get("status") != "success":
        return {"answer": "", "formatted": "", "kind": "transport_or_protocol_failure"}
    try:
        text = runtime._response_text(record["response"], record["metadata"])
        answer = runtime.ReasoningAgent._extract_answer(text)
        formatted = runtime.format_answer_for_output(answer) if answer else ""
        kind = ("explicit_incomplete" if runtime.ReasoningAgent._response_cutoff(text) else
                "empty_content" if not text.strip() else "extractable" if answer else "unextractable")
        return {"answer": answer, "formatted": formatted, "kind": kind}
    except (KeyError, TypeError, ValueError):
        return {"answer": "", "formatted": "", "kind": "invalid_response"}


class ReplayDivergence(BaseException):
    """Escape ordinary solver recovery; a new request has no recorded answer."""


class MatchingReplayClient:
    def __init__(self, entries):
        self.entries = entries
        self.position = 0
        self.mismatch = None

    def chat(self, *, messages, temperature, max_tokens,
             thinking_mode=_UNSET, tools=_UNSET, tool_choice=_UNSET):
        sent = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        sent.update({key: value for key, value in (
            ("thinking_mode", thinking_mode), ("tools", tools), ("tool_choice", tool_choice)
        ) if value is not _UNSET})
        if self.position >= len(self.entries):
            self.mismatch = "recorded_sequence_exhausted"
            raise ReplayDivergence(self.mismatch)
        request, response = self.entries[self.position]
        try:
            expected = _request_payload(request)
        except ValueError:
            self.mismatch = "unsupported_recorded_request"
            raise ReplayDivergence(self.mismatch) from None
        if digest(sent) != digest(expected):
            self.mismatch = "request_changed"
            raise ReplayDivergence(self.mismatch)
        self.position += 1
        if response.get("status") != "success":
            raise RuntimeError("recorded transport failure")
        text = runtime._response_text(response["response"], response["metadata"])
        return {"content": str(text), "finish_reason": text.finish_reason}


def capture(pilot, output):
    pilot, output = Path(pilot).resolve(), Path(output).resolve()
    if output.is_relative_to(pilot):
        raise ValueError("do not write into the original experiment")
    audit = read(pilot / "audited-result.json")
    if audit["status"] not in ("stopped", "completed"):
        raise ValueError("only terminal experiments can be captured")
    if sha256((pilot / "request-ledger.jsonl").read_bytes()).hexdigest() != audit["ledger_sha256"]:
        raise ValueError("ledger changed since audit")
    ledger_path = pilot / "request-ledger.jsonl"
    if ledger_path.stat().st_size > 8_000_000:
        raise ValueError("oversized ledger")
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    starts = [row for row in events if row["event"] == "start"]
    if len(starts) > 10_000 or [r["ordinal"] for r in starts] != list(range(1, len(starts)+1)):
        raise ValueError("invalid request sequence")
    files = {}

    def bind(relative):
        path = inside(pilot, relative)
        if path.stat().st_size > 8_000_000:
            raise ValueError("oversized bound file")
        files[relative] = sha256(path.read_bytes()).hexdigest()
        return read(path)

    for relative in ("audited-result.json", "pilot-plan.json", "assistant-review.json", "study/protocol.json"):
        bind(relative)
    protocol = read(pilot / "study/protocol.json")
    inputs = Path(protocol["bundle"]) / "dev.input.jsonl"
    input_hash = sha256(inputs.read_bytes()).hexdigest()
    if input_hash != protocol["plans"]["dev"]["input_sha256"]:
        raise ValueError("development inputs changed")
    files["request-ledger.jsonl"] = audit["ledger_sha256"]
    observations = []
    for row in starts:
        ordinal = row["ordinal"]
        request = bind(f"model-relay/request-{ordinal:04d}.json")
        if request["ordinal"] != ordinal:
            raise ValueError("request identity mismatch")
        payload = _request_payload(request)
        relative = f"model-relay/response-{ordinal:04d}.json"
        if not inside(pilot, relative).exists():
            observations.append({"ordinal": ordinal, "variant": row["variant"],
                                 "stage": row["stage"], "missing": True})
            continue
        response = bind(relative)
        observations.append({"ordinal": ordinal, "variant": row["variant"],
            "stage": row["stage"], "max_tokens": payload["max_tokens"],
            "request_sha256": digest(payload),
            "thinking_mode_recorded": "thinking_mode" in payload,
            "before": inspect_response(response)})
    items = audit["completed_item_diagnostics"]["items"]
    for item in items:
        if not re.fullmatch(r"[a-z_]{1,32}", item["variant"]):
            raise ValueError("invalid variant")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", item["idx"]):
            raise ValueError("invalid item identity")
        folder = f"runs/{item['variant']}-0"
        relative = f"{folder}/{item['idx']}.json"
        checkpoint = bind(relative)
        if files[relative] != item["checkpoint_sha256"] or checkpoint["idx"] != item["idx"]:
            raise ValueError("checkpoint binding mismatch")
        bind(f"{folder}/_run/run_summary.json")
    manifest = {"schema_version": 2, "pilot": str(pilot), "input_path": str(inputs), "input_sha256": input_hash,
        "generation_source_sha256": audit["generation_source_sha256"],
        "capture_source_sha256": source_hash(), "files": files, "responses": observations, "items": items,
        "scope": "Offline parser diagnostics and exact recorded-parameter replay; missing settings are not inferred; no new model accuracy."}
    manifest["sha256"] = digest(manifest)
    write_new(output, manifest)
    return {"responses": len(observations), "completed_items": len(items), "sha256": manifest["sha256"]}


def verify_snapshot(snapshot):
    manifest = read(snapshot)
    expected = manifest.pop("sha256")
    if digest(manifest) != expected:
        raise ValueError("snapshot changed")
    pilot = Path(manifest["pilot"])
    for relative, fingerprint in manifest["files"].items():
        if sha256(inside(pilot, relative).read_bytes()).hexdigest() != fingerprint:
            raise ValueError("original evidence changed")
    if sha256(Path(manifest["input_path"]).read_bytes()).hexdigest() != manifest["input_sha256"]:
        raise ValueError("development inputs changed")
    return manifest


def compare(snapshot, output, *, solve=False):
    manifest = verify_snapshot(snapshot)
    pilot = Path(manifest["pilot"])
    if Path(output).resolve().is_relative_to(pilot.resolve()):
        raise ValueError("do not write into the original experiment")
    rows = []
    for original in manifest["responses"]:
        row = dict(original)
        if row.get("missing"):
            rows.append(row)
            continue
        now = inspect_response(read(pilot / f"model-relay/response-{row['ordinal']:04d}.json"))
        before = row["before"]
        change = ("unchanged" if before == now else "newly_extractable" if not before["answer"] and now["answer"] else
                  "no_longer_extractable" if before["answer"] and not now["answer"] else "changed")
        row.update(after=now, change=change)
        rows.append(row)
    replays = []
    if solve:
        inputs = Path(manifest["input_path"])
        if inputs.stat().st_size > 8_000_000:
            raise ValueError("oversized development inputs")
        problems = {}
        for line in inputs.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if item["idx"] in problems or not isinstance(item["problem"], str):
                raise ValueError("invalid development input")
            problems[item["idx"]] = item["problem"]
        for item in manifest["items"]:
            variant, idx = item["variant"], item["idx"]
            settings = read(pilot / f"runs/{variant}-0/_run/run_summary.json")["config"]
            entries = [(read(pilot / f"model-relay/request-{n:04d}.json"),
                        read(pilot / f"model-relay/response-{n:04d}.json")) for n in item["request_ordinals"]]
            client = MatchingReplayClient(entries)
            agent = runtime.ReasoningAgent(client, runtime.AgentConfig(**settings["agent"]),
                                           local_policy=runtime.Q1Policy(**settings["policy"]))
            result = {"variant": variant, "idx": idx, "original_actual": item["actual"]}
            try:
                response = agent.solve(problems[idx], {"idx": idx})["final_response"]
                result.update(status="finished_with_recorded_prefix", actual=agent._extract_answer(response),
                              final_response_sha256=sha256(response.encode()).hexdigest())
            except ReplayDivergence:
                result.update(status="diverged", reason=client.mismatch)
            result.update(consumed=client.position, recorded=len(entries))
            replays.append(result)
    verify_snapshot(snapshot)
    result = {"source_sha256": source_hash(), "replay_tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "snapshot_sha256": digest(manifest),
        "response_changes": dict(Counter(row.get("change", "missing") for row in rows)),
        "responses": rows, "item_replays": replays,
        "replay_contract": "exact_recorded_parameters" if solve else "parser_only",
        "original_evidence_unchanged": True, "actual_api_requests": 0,
        "claim": "Changed parser acceptance is not new correct solves. Diverging requests cannot reuse later responses."}
    write_new(output, result)
    return {key: result[key] for key in ("response_changes", "actual_api_requests", "original_evidence_unchanged")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "compare"))
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--solve", action="store_true", help="Match all recorded request parameters; stop on differences, including omitted settings")
    args = parser.parse_args()
    result = capture(args.input, args.output) if args.mode == "capture" else compare(args.input, args.output, solve=args.solve)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
