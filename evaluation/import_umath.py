"""Explicit public-data download; never imports a client or reads credentials."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

API = "https://huggingface.co/api/datasets/toloka/u-math"
ROWS = "https://datasets-server.huggingface.co/rows?dataset=toloka%2Fu-math&config=default&split=test"


def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                data = response.read(20_000_001)
                if len(data) > 20_000_000:
                    raise ValueError("public response too large")
                return data
        except HTTPError as exc:
            if exc.code not in (429, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(attempt+1)


def download(output: Path):
    if output.exists():
        raise ValueError("source destination already exists")
    revision = json.loads(fetch(API))["sha"]
    first = json.loads(fetch(ROWS + "&offset=0&length=100"))
    count = first["num_rows_total"]
    if not 100 <= count <= 10_000:
        raise ValueError("unexpected source size")
    with ThreadPoolExecutor(max_workers=3) as pool:
        pages = [first] + list(pool.map(lambda offset: json.loads(fetch(
            ROWS + f"&offset={offset}&length=100")), range(100, count, 100)))
    if json.loads(fetch(API))["sha"] != revision:
        raise ValueError("source changed during download")
    entries = [entry for page in pages for entry in page["rows"]]
    if any(set(entry.get("truncated_cells", [])) & {"problem_statement", "golden_answer"} for entry in entries):
        raise ValueError("source text truncated by rows API")
    rows = [entry["row"] for entry in entries]
    if len(rows) != count or len({row["uuid"] for row in rows}) != count:
        raise ValueError("incomplete or duplicate source rows")
    card_url = f"https://huggingface.co/datasets/toloka/u-math/raw/{revision}/README.md"
    card = fetch(card_url)
    if b"MIT license" not in card:
        raise ValueError("dataset licensing statement requires review")
    records = [{"idx": row["uuid"], "problem": row["problem_statement"],
        "answer": row["golden_answer"], "subject": row["subject"],
        "level": "university_source_label", "task_type": "free_response",
        "source": f"https://huggingface.co/datasets/toloka/u-math/tree/{revision}",
        "license": "MIT", "source_split": "test", "source_revision": revision,
        "language": "en"} for row in rows if row["has_image"] is False]
    output.mkdir(parents=True)
    data = ("\n".join(json.dumps(row, ensure_ascii=False) for row in records)+"\n").encode()
    (output / "records.jsonl").write_bytes(data)
    (output / "SOURCE_README.md").write_bytes(card)
    (output / "provenance.json").write_text(json.dumps({
        "source": API, "revision": revision, "retrieval": ROWS,
        "total_source_rows": count, "text_only_rows": len(records),
        "truncated_text_cells": 0,
        "records_sha256": sha256(data).hexdigest(),
        "readme_sha256": sha256(card).hexdigest(),
        "source_claim": "Rows API snapshot; revision checked before/after; snapshot hash is definitive",
        "limitations": "English, six university subjects; public exposure; not unseen/competition calibrated",
    }, indent=2)+"\n", encoding="utf-8")
    return len(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    print("text_only_rows=" + str(download(parser.parse_args().output)))
