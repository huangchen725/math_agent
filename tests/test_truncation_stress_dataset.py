import hashlib
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "evaluation" / "data" / "truncation_stress.jsonl"
MANIFEST = ROOT / "evaluation" / "data" / "truncation_stress_manifest.json"


def test_truncation_stress_set_is_frozen_and_balanced():
    records = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert len(records) == manifest["items"] == 36
    assert set(Counter(record["subject"] for record in records).values()) == {2}
    assert len({record["subject"] for record in records}) == manifest["subjects"] == 18
    assert len({record["idx"] for record in records}) == 36
    assert all(record["split"] == "dev" for record in records)
    assert all(record["license"] == "CC0-1.0" for record in records)
    assert all(len(record["problem"]) >= 50 for record in records)
    canonical_bytes = b"\n".join(DATASET.read_bytes().splitlines()) + b"\n"
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    assert digest == manifest["sha256"]
