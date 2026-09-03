import argparse
import asyncio
import hashlib
import json
import os
import re
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agent import ReasoningAgent
from llm_client import InternChatClient


def _positive_env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer, got {value}")
    return value


LOCAL_MAX_CONCURRENCY = _positive_env_int("LOCAL_MAX_CONCURRENCY", 3)
_SAFE_INDEX = re.compile(r"[A-Za-z0-9_-]{1,128}")


def _normalized_idx(value: object) -> str:
    idx = str(value)
    if not _SAFE_INDEX.fullmatch(idx):
        raise ValueError(
            "idx must be 1-128 ASCII letters, digits, underscores, or hyphens"
        )
    return idx


def load_jsonl(path: Path) -> List[Dict]:
    items = []
    seen_indexes = set()
    with path.open("r", encoding="utf-8-sig") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc
            if not isinstance(item, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            item.setdefault("idx", line_number - 1)
            idx = _normalized_idx(item["idx"])
            if idx in seen_indexes:
                raise ValueError(f"Duplicate idx {idx!r} on line {line_number}")
            seen_indexes.add(idx)
            problem = item.get("problem")
            if not isinstance(problem, str) or not problem.strip():
                raise ValueError(f"Line {line_number} must contain a non-empty problem string")
            items.append(item)
    return items


def result_path(output_dir: Path, item: Dict) -> Path:
    return output_dir / f"{_normalized_idx(item['idx'])}.json"


def is_processed(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        record = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(record, dict)
        and record.get("status") == "success"
        and isinstance(record.get("final_response"), str)
        and bool(record["final_response"].strip())
    )


def write_json(path: Path, record: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp_path.replace(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_run_summary(
    *,
    statuses: List[str],
    input_path: Path,
    input_sha256: str,
    model: str,
    duration_ms: int,
    started_at: str,
) -> Dict:
    counts = Counter(statuses)
    error_count = counts["error"]
    return {
        "status": "complete" if error_count == 0 else "completed_with_errors",
        "started_at": started_at,
        "duration_ms": duration_ms,
        "input_file": input_path.name,
        "input_sha256": input_sha256,
        "model": model,
        "local_max_concurrency": LOCAL_MAX_CONCURRENCY,
        "total_items": len(statuses),
        "success": counts["success"],
        "error": error_count,
        "skipped": counts["skipped"],
    }


def build_output_record(item: Dict, agent_result: Dict) -> Dict:
    final_response = agent_result.get("final_response", "")
    if not isinstance(final_response, str) or not final_response.strip():
        raise ValueError("agent.solve must return a non-empty string field: final_response")
    if final_response.strip() == "未解出":
        return {
            "idx": item["idx"],
            "status": "error",
            "final_response": final_response,
            "error": {
                "type": "Unsolved",
                "message": "agent.solve returned the unsolved sentinel",
            },
            "trace": agent_result.get("trace", []),
        }

    output = {
        "idx": item["idx"],
        "status": "success",
        "final_response": final_response,
        "trace": agent_result.get("trace", []),
    }
    return output


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Competition sample reasoning agent.")
    parser.add_argument("--input_file", required=True, help="Path to input JSONL.")
    parser.add_argument("--output_dir", required=True, help="Directory for per-problem JSON outputs.")
    return parser.parse_args()


def solve_item(agent: ReasoningAgent, item: Dict) -> Dict:
    result = agent.solve(
        problem=item["problem"],
        metadata={"idx": item["idx"]},
    )
    return build_output_record(item, result)


async def process_item(
    agent: ReasoningAgent,
    item: Dict,
    output_dir: Path,
    semaphore: asyncio.Semaphore,
) -> str:
    path = result_path(output_dir, item)
    if is_processed(path):
        print(f"Skip idx={item['idx']} because {path} already exists.")
        return "skipped"

    async with semaphore:
        try:
            record = await asyncio.to_thread(solve_item, agent, item)
        except Exception as exc:
            record = {
                "idx": item["idx"],
                "status": "error",
                "final_response": "",
                "error": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "trace": [],
            }
        await asyncio.to_thread(write_json, path, record)
        print(f"Finished idx={item['idx']}")
        return str(record["status"])


async def run(args: argparse.Namespace) -> None:
    input_path = Path(args.input_file)
    output_dir = Path(args.output_dir)
    started_at = datetime.now(timezone.utc).isoformat()
    started_monotonic = time.monotonic()

    items = load_jsonl(input_path)
    input_digest = file_sha256(input_path)

    client = InternChatClient()
    agent = ReasoningAgent(client=client)
    semaphore = asyncio.Semaphore(LOCAL_MAX_CONCURRENCY)

    print(f"Loaded {len(items)} items. Max concurrency: {LOCAL_MAX_CONCURRENCY}.")
    tasks = [process_item(agent, item, output_dir, semaphore) for item in items]
    statuses = await asyncio.gather(*tasks)
    summary = build_run_summary(
        statuses=statuses,
        input_path=input_path,
        input_sha256=input_digest,
        model=client.model,
        duration_ms=round((time.monotonic() - started_monotonic) * 1000),
        started_at=started_at,
    )
    await asyncio.to_thread(write_json, output_dir / "_run" / "run_summary.json", summary)
    print(f"Saved outputs to {output_dir}")


def main() -> None:
    asyncio.run(run(parse_args()))


if __name__ == "__main__":
    main()
