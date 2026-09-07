"""Local-only bounded relay control. No network is started by importing or using its CLI.

A separately authorized network worker supplies a single-send transport to serve().
The controller and worker share durable admission state; neither role loads labels.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import time


class PilotStopped(BaseException):
    """A global stop must escape the agent's ordinary fallback handlers."""


@dataclass(frozen=True)
class Limits:
    requests: int
    output_tokens: int
    dispatch_seconds: float
    wait_seconds: float = 350.0

    def validate(self):
        if (type(self.requests) is not int or not 1 <= self.requests <= 10000
                or type(self.output_tokens) is not int or not 1 <= self.output_tokens <= self.requests * 8192
                or any(type(x) not in (int, float) or not math.isfinite(x) or x <= 0
                       for x in (self.dispatch_seconds, self.wait_seconds))
                or self.wait_seconds > 350):
            raise ValueError("invalid pilot limits")


def _read(path):
    raw = path.read_bytes()
    if len(raw) > 2_000_000:
        raise ValueError("oversized relay record")
    return json.loads(raw)


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _state(directory):
    plan = _read(directory / "plan.json")
    expected = plan.pop("sha256")
    state = _read(directory / "state.json")
    if (_digest(plan) != expected or state.get("plan_sha256") != expected
            or any(state.get(key) != plan[key] for key in ("model", "identity", "limits", "deadline"))
            or plan["controller_sha256"] != sha256(Path(__file__).read_bytes()).hexdigest()):
        raise ValueError("stale or modified relay plan")
    return state


def _write(path, value):
    data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    if len(data) > 2_000_000:
        raise ValueError("oversized relay record")
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


@contextmanager
def _gate(directory):
    """Cross-process admission lock; never held while awaiting the network."""
    with (directory / "gate.lock").open("r+b") as handle:
        until = time.monotonic() + 5
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= until:
                    raise TimeoutError("relay admission lock timeout") from None
                time.sleep(0.01)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def create(directory, limits, *, model, identity, clock=time.monotonic):
    limits.validate()
    if not isinstance(model, str) or not model.isascii() or not model.strip():
        raise ValueError("explicit model identity required")
    if not isinstance(identity, dict) or set(identity) != {"source_sha256", "config_sha256", "input_sha256"}:
        raise ValueError("bound source/config/input identity required")
    if any(not isinstance(x, str) or len(x) != 64 or any(c not in "0123456789abcdef" for c in x)
           for x in identity.values()):
        raise ValueError("invalid identity digest")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "gate.lock").write_bytes(b"0")
    plan = {"model": model, "identity": identity, "limits": asdict(limits),
            "deadline": clock()+limits.dispatch_seconds,
            "controller_sha256": sha256(Path(__file__).read_bytes()).hexdigest()}
    plan["sha256"] = _digest(plan)
    _write(directory / "plan.json", plan)
    state = {"schema_version": 1, "status": "running", "stop_reason": None, "model": model,
        "identity": identity, "limits": plan["limits"], "deadline": plan["deadline"], "plan_sha256": plan["sha256"],
        "attempts": 0, "completed_responses": 0, "requested_output_tokens": 0,
        "known_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "queued": None, "in_flight": None, "last_admitted_at": None, "paused_at": None}
    _write(directory / "state.json", state)
    return state


def status(directory):
    directory = Path(directory)
    with _gate(directory):
        state = _state(directory)
    state["unknown_usage_requests"] = state["attempts"]-state["completed_responses"]
    return state


def pause(directory, *, reason="user_pause", clock=time.monotonic):
    if reason not in ("user_pause", "dispatch_deadline", "relay_deadline", "finished", "request_limit", "output_limit"):
        raise ValueError("invalid stop category")
    directory = Path(directory)
    with _gate(directory):
        state = _state(directory)
        if state["status"] == "running":
            state.update(status="paused" if reason == "user_pause" else "stopped",
                         stop_reason=reason, paused_at=clock())
            _write(directory / "state.json", state)
    return {"status": state["status"], "last_admitted_ordinal": state["attempts"],
            "in_flight": state["in_flight"], "queued_not_sent": state["queued"]}


def _event(directory, value):
    # No messages, responses, provider request ids, headers or exception text.
    with (directory / "ledger.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+"\n")
        handle.flush()
        os.fsync(handle.fileno())


def _payload(messages, temperature, max_tokens):
    if (type(max_tokens) is not int or not 1 <= max_tokens <= 8192
            or type(temperature) not in (int, float) or not math.isfinite(temperature)
            or not 0 <= temperature <= 2 or type(messages) is not list or not 1 <= len(messages) <= 128):
        raise ValueError("invalid relay payload")
    for message in messages:
        if (type(message) is not dict or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant") or type(message["content"]) is not str):
            raise ValueError("invalid text message")
    result = {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if len(json.dumps(result, ensure_ascii=False).encode()) > 1_900_000:
        raise ValueError("oversized payload")
    return result


class RelayClient:
    """Offline controller side, compatible with the public three-argument contract."""
    def __init__(self, directory, *, clock=time.monotonic, sleep=time.sleep):
        self.directory, self.clock, self.sleep = Path(directory), clock, sleep

    def chat(self, *, messages, temperature, max_tokens,
             thinking_mode=None, tools=None, tool_choice=None):
        # 2026-09-06 公开协议修订：容忍扩展关键字，载荷仍按三键规范记录。
        payload = _payload(messages, temperature, max_tokens)
        with _gate(self.directory):
            state = _state(self.directory)
            if state["status"] != "running":
                raise PilotStopped(state["stop_reason"])
            if state["in_flight"] is not None or state["queued"] is not None:
                raise PilotStopped("concurrent_dispatch_forbidden")
            ordinal = state["attempts"]+1
            request = self.directory / f"request-{ordinal:04d}.json"
            if request.exists():
                raise PilotStopped("used_request_identity")
            _write(request, {"ordinal": ordinal, "payload": payload})
            state["queued"] = ordinal
            _write(self.directory / "state.json", state)
        response = self.directory / f"response-{ordinal:04d}.json"
        until = self.clock()+state["limits"]["wait_seconds"]
        while not response.exists():
            current = status(self.directory)
            if response.exists():
                break
            if current["status"] != "running" and current["in_flight"] != ordinal:
                raise PilotStopped(current["stop_reason"])
            if self.clock() >= until:
                pause(self.directory, reason="relay_deadline", clock=self.clock)
                raise PilotStopped("relay_deadline")
            self.sleep(0.01)
        result = _read(response)
        if result["status"] != "success":
            raise PilotStopped("transport_or_protocol_failure")
        raw, meta = result["response"], result["metadata"]
        if isinstance(raw, dict):
            reason = raw.get("finish_reason")
            if not reason or reason == "stop":
                reason = meta["finish_reason"]
            return {"content": raw.get("content"), "finish_reason": reason}
        return {"content": raw, "finish_reason": meta["finish_reason"]}


def project_response(body):
    """Project a provider JSON body without logging headers or hidden reasoning text."""
    if type(body) is not dict or type(body.get("choices")) is not list or len(body["choices"]) != 1:
        raise ValueError("invalid provider envelope")
    choice = body["choices"][0]
    if type(choice) is not dict or type(choice.get("message")) is not dict:
        raise ValueError("invalid provider message")
    message = choice["message"]
    projected = ({key: message[key] for key in ("content", "tool_calls", "finish_reason") if key in message}
                 if message.get("tool_calls") else message.get("content"))
    diagnostics = {}
    for name in ("content", "reasoning_content", "tool_calls"):
        value = message.get(name)
        diagnostics[name] = {"present": name in message, "type": type(value).__name__,
                             "length": len(value) if isinstance(value, (str, list)) else None}
    diagnostics["whitespace_only_content"] = isinstance(message.get("content"), str) and not message["content"].strip()
    return {"response": projected, "metadata": {"model": body.get("model"), "usage": body.get("usage"),
            "finish_reason": choice.get("finish_reason"), "attempts": 1}, "diagnostics": diagnostics}


def _validate_receipt(result, model):
    if type(result) is not dict or not {"response", "metadata"} <= result.keys():
        raise ValueError("invalid transport receipt")
    meta = result["metadata"]
    if (type(meta) is not dict or type(meta.get("model")) is not str or not meta["model"].isascii()
            or meta["model"].lower() != model.lower() or type(meta.get("attempts")) is not int or meta["attempts"] != 1
            or meta.get("finish_reason") not in ("stop", "length", "tool_calls", "content_filter")):
        raise ValueError("invalid receipt identity")
    usage = meta.get("usage")
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    if (type(usage) is not dict or any(type(usage.get(k)) is not int or not 0 <= usage[k] <= 10**9 for k in keys)
            or usage["prompt_tokens"]+usage["completion_tokens"] != usage["total_tokens"] or usage["total_tokens"] <= 0):
        raise ValueError("invalid usage receipt")
    if result["response"] is not None and not isinstance(result["response"], (str, dict)):
        raise ValueError("invalid response projection")
    diagnostics = {}
    supplied = result.get("diagnostics", {})
    if type(supplied) is not dict:
        raise ValueError("invalid diagnostics")
    for name in ("content", "reasoning_content", "tool_calls"):
        if name in supplied:
            fields = supplied[name]
            if (type(fields) is not dict or set(fields) != {"present", "type", "length"}
                    or type(fields["present"]) is not bool or fields["type"] not in ("str", "list", "dict", "int", "float", "bool", "NoneType")
                    or (fields["length"] is not None and (type(fields["length"]) is not int or not 0 <= fields["length"] <= 2_000_000))):
                raise ValueError("invalid field diagnostics")
            diagnostics[name] = fields
    if type(supplied.get("whitespace_only_content")) is bool:
        diagnostics["whitespace_only_content"] = supplied["whitespace_only_content"]
    return {"response": result["response"], "metadata": {"model": meta["model"], "attempts": 1,
        "usage": {key: usage[key] for key in keys}, "finish_reason": meta["finish_reason"]},
        "diagnostics": diagnostics}


def serve_once(directory, send_once, *, clock=time.monotonic):
    """Admit at most one request. The supplied transport must send once with bounded I/O."""
    directory = Path(directory)
    with _gate(directory):
        state = _state(directory)
        if state["status"] != "running":
            return False
        reason = ("dispatch_deadline" if clock() >= state["deadline"] else
                  "request_limit" if state["attempts"] >= state["limits"]["requests"] else None)
        if reason:
            state.update(status="stopped", stop_reason=reason)
            _write(directory / "state.json", state)
            return False
        if state["queued"] is None or state["in_flight"] is not None:
            return False
        ordinal = state["queued"]
        request = _read(directory / f"request-{ordinal:04d}.json")
        if ordinal != state["attempts"]+1 or request["ordinal"] != ordinal:
            raise ValueError("request sequence changed")
        payload = _payload(**request["payload"])
        if state["requested_output_tokens"]+payload["max_tokens"] > state["limits"]["output_tokens"]:
            state.update(status="stopped", stop_reason="output_limit")
            _write(directory / "state.json", state)
            return False
        state.update(attempts=ordinal, in_flight=ordinal, queued=None, last_admitted_at=clock())
        state["requested_output_tokens"] += payload["max_tokens"]
        _write(directory / "state.json", state)
        _event(directory, {"event": "start", "ordinal": ordinal, "at": clock(),
            "max_tokens": payload["max_tokens"], "request_sha256": sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()})
    try:
        result = _validate_receipt(send_once(payload), state["model"])
        result["status"] = "success"
        # Validate bounded serialization before declaring receipt/cost completion.
        _write(directory / f"pending-receipt-{ordinal:04d}.json", result)
    except Exception as error:
        result = {"status": "failed", "error_category": type(error).__name__}
        _write(directory / f"pending-receipt-{ordinal:04d}.json", result)
    with _gate(directory):
        state = _state(directory)
        state["in_flight"] = None
        if result["status"] == "success":
            state["completed_responses"] += 1
            for key, count in result["metadata"]["usage"].items():
                state["known_usage"][key] += count
            event = {"event": "complete", "ordinal": ordinal, "at": clock(), **result["metadata"]}
        else:
            state.update(status="stopped", stop_reason="transport_or_protocol_failure")
            event = {"event": "failed", "ordinal": ordinal, "at": clock(), **result}
        _event(directory, event)
        _write(directory / "state.json", state)
        (directory / f"pending-receipt-{ordinal:04d}.json").replace(directory / f"response-{ordinal:04d}.json")
    return True


def serve(directory, send_once, *, clock=time.monotonic, sleep=time.sleep):
    """Network worker loop. Stops without retrying any failed or uncertain request."""
    try:
        while status(directory)["status"] == "running":
            if not serve_once(directory, send_once, clock=clock):
                sleep(0.01)
    except Exception as error:
        directory = Path(directory)
        with _gate(directory):
            state = _read(directory / "state.json")
            state.update(status="stopped", stop_reason="relay_protocol_failure")
            _event(directory, {"event": "worker_failed", "error_category": type(error).__name__})
            _write(directory / "state.json", state)


def _http_once(payload, authorization, model):
    """One HTTP send, called only inside the bounded network child."""
    import requests
    from requests.adapters import HTTPAdapter
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=0))
        response = session.post("https://chat.intern-ai.org.cn/api/v1/chat/completions",
            headers={"Authorization": authorization, "Content-Type": "application/json"},
            data=json.dumps({"model": model, **payload}, ensure_ascii=False).encode(),
            timeout=(10, 300), allow_redirects=False)
        if 300 <= response.status_code < 400:
            raise ValueError("redirect forbidden")
        response.raise_for_status()
        return project_response(response.json())


def _http_child(payload, authorization, model, output):
    try:
        result = {"status": "success", "receipt": _http_once(payload, authorization, model)}
    except Exception as error:
        result = {"status": "failed", "error_category": type(error).__name__}
    _write(Path(output), result)


def _bounded_child(target, args, *, wait_seconds):
    import multiprocessing
    child = multiprocessing.get_context("spawn").Process(target=target, args=args, daemon=True)
    child.start()
    try:
        child.join(wait_seconds)
        if child.is_alive():
            raise TimeoutError("network child deadline")
        if child.exitcode != 0:
            raise RuntimeError("network child failed")
    finally:
        if child.is_alive():
            child.terminate()
            child.join(2)
        if child.is_alive():
            child.kill()
            child.join(2)
        if not child.is_alive():
            child.close()


def make_http_sender(authorization, model, *, wait_seconds=345):
    """Use only in a separately authorized worker. No dataset or environment reads.

    A fresh child sends once. Its 345 s join + up to 4 s termination cleanup fit
    inside the 350 s controller wait. Killing local I/O cannot cancel server cost;
    a missing receipt remains unknown and the experiment stops without retrying.
    """
    if type(authorization) is not str or not authorization.strip():
        raise ValueError("missing authorization")
    if type(wait_seconds) not in (int, float) or not math.isfinite(wait_seconds) or not 0 < wait_seconds <= 345:
        raise ValueError("invalid network child deadline")

    def send_once(payload):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory(prefix="math-agent-receipt-") as temporary:
            output = Path(temporary) / "receipt.json"
            _bounded_child(_http_child, (payload, authorization, model, str(output)), wait_seconds=wait_seconds)
            result = _read(output)
            if result["status"] != "success":
                # Never propagate response bodies, credentials or exception text.
                raise RuntimeError("network child transport failure")
            return result["receipt"]
    return send_once


def run_controlled(plan, variant, bundle, output, client, *, execution="fixture", run_ticket=None):
    """Controller-only Q1 integration. A paused partial run cannot become a complete Q2 slot."""
    from evaluation.q0_pipeline import digest
    from evaluation.q1_experiments import run_plan, source_hash
    state = status(client.directory)
    expected = {"source_sha256": source_hash(), "input_sha256": plan["input_sha256"],
                "config_sha256": digest(plan["variants"][variant])}
    if state["identity"] != expected or state["model"] != plan["model"] or plan["code_sha"] != expected["source_sha256"]:
        pause(client.directory, reason="finished")
        raise ValueError("controller identity differs from Q1 plan")
    try:
        return run_plan(plan, variant, Path(bundle), Path(output), client, execution=execution, run_ticket=run_ticket)
    except PilotStopped:
        summary_path = Path(output) / "_run/run_summary.json"
        if summary_path.exists():
            summary = _read(summary_path)
            summary.update(status="interrupted", stop_reason=status(client.directory)["stop_reason"])
            _write(summary_path, summary)
        return {"status": "interrupted", "control": status(client.directory)}
    finally:
        pause(client.directory, reason="finished")


def main():
    parser = argparse.ArgumentParser(description="Inspect or pause an existing local relay; never starts network work")
    parser.add_argument("command", choices=("status", "pause"))
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = status(args.directory) if args.command == "status" else pause(args.directory)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
