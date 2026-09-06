import copy
from dataclasses import asdict
from hashlib import sha256
import json
from urllib.error import HTTPError

import pytest

from evaluation import import_umath, q0_pipeline as q0, q1_experiments as q1


def rows():
    return [{"idx": str(i), "problem": problem, "answer": "2", "subject": "a", "source": "fixture://source",
        "license": "MIT", "level": "university", "task_type": "free_response"}
        for i,problem in enumerate(["计算1+1", "求未知数", "判断是否收敛", "计算矩阵的秩"])]


def test_all_offline_commands_and_review_roundtrip(tmp_path, monkeypatch):
    source = tmp_path/"source.jsonl"
    source.write_text("\n".join(json.dumps(r) for r in rows()), encoding="utf-8")
    bundle, plan_path, run = tmp_path/"bundle", tmp_path/"plan.json", tmp_path/"run"
    monkeypatch.setattr(q0, "development_references", lambda: [])
    def command(module, *args):
        monkeypatch.setattr("sys.argv", ["offline", *map(str, args)])
        module.main()
    command(q0, "freeze", source, bundle, "--per-subject", 4)
    command(q0, "verify", bundle)
    command(q1, bundle, "--output", plan_path)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    class Client:
        def chat(self, *, messages, temperature, max_tokens):
            return "VERDICT: A" if "验证器" in messages[0]["content"] else "最终答案：2"
    q1.run_plan(plan, "baseline", bundle, run, Client())
    report, comparison, packet_path = (tmp_path/n for n in ("score.json", "pair.json", "packet.json"))
    command(q0, "score", bundle, run, plan_path, "--variant", "baseline", "--execution", "fixture", "--output", report)
    command(q0, "compare", report, report, "--output", comparison)
    command(q0, "review-packet", bundle, report, "--salt", "fixture", "--output", packet_path)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    for identity in ("a", "b"):
        (tmp_path/f"{identity}.json").write_text(json.dumps({"reviewer": identity,
            "packet_sha256": packet["packet_sha256"], "decisions": {r["review_id"]: "correct" for r in packet["items"]}}), encoding="utf-8")
    command(q0, "review-merge", packet_path, tmp_path/"a.json", tmp_path/"b.json", "--output", tmp_path/"merged.json")
    assert all(r["status"] == "correct" for r in json.loads((tmp_path/"merged.json").read_text()).values())
    with pytest.raises(ValueError, match="overwrite"):
        command(q1, bundle, "--output", plan_path)
    with pytest.raises(ValueError, match="overwrite"):
        command(q0, "compare", report, report, "--output", comparison)


@pytest.mark.parametrize("failure", [None, "truncated", "duplicate", "revision", "license", "size"])
def test_public_importer_validates_complete_licensed_snapshot(tmp_path, monkeypatch, failure):
    entries = [{"row": {"uuid": str(i), "subject": "a", "has_image": False, "problem_statement": "p",
        "golden_answer": "a", "image": None}, "truncated_cells": []} for i in range(101)]
    if failure == "truncated":
        entries[0]["truncated_cells"] = ["golden_answer"]
    if failure == "duplicate":
        entries[-1]["row"]["uuid"] = "0"
    calls = []
    def fetch(url):
        calls.append(url)
        if url == import_umath.API:
            revision = "b"*40 if failure == "revision" and calls.count(url) > 1 else "a"*40
            return json.dumps({"sha": revision}).encode()
        if url.endswith("README.md"):
            return b"unknown" if failure == "license" else b"MIT license"
        page = entries[100:] if "offset=100" in url else entries[:100]
        return json.dumps({"rows": page, "num_rows_total": 1 if failure == "size" else 101}).encode()
    monkeypatch.setattr(import_umath, "fetch", fetch)
    if failure:
        with pytest.raises(ValueError):
            import_umath.download(tmp_path/"source")
        assert not (tmp_path/"source").exists()
    else:
        assert import_umath.download(tmp_path/"source") == 101
        provenance = json.loads((tmp_path/"source"/"provenance.json").read_text())
        assert provenance["records_sha256"] == sha256((tmp_path/"source"/"records.jsonl").read_bytes()).hexdigest()
        with pytest.raises(ValueError):
            import_umath.download(tmp_path/"source")


@pytest.mark.parametrize("status,attempts", [(401, 1), (403, 1), (404, 1), (502, 3), (429, 3)])
def test_download_retry_is_bounded_and_skips_permanent_errors(monkeypatch, status, attempts):
    calls = []
    def open_url(*args, **kwargs):
        calls.append(1)
        raise HTTPError("https://example.invalid", status, "fixture", {}, None)
    monkeypatch.setattr(import_umath, "urlopen", open_url)
    monkeypatch.setattr(import_umath.time, "sleep", lambda n: None)
    with pytest.raises(HTTPError):
        import_umath.fetch("https://example.invalid")
    assert len(calls) == attempts


@pytest.mark.parametrize("key,value", [("license", "unknown"), ("source", ""), ("problem", 1),
    ("problem", "x"*20001), ("answer", None)])
def test_provenance_and_input_contract_fail_closed(key, value):
    data = rows()
    data[0][key] = value
    with pytest.raises(ValueError):
        q0.freeze_records(data, references=[])


def test_development_reference_inventory_contains_tests_and_prompts():
    refs = q0.development_references()
    assert any(r.source == "prompt_fewshot" for r in refs)
    assert any(r.source.startswith("test_literal:") for r in refs)
    assert q0.digest([asdict(r) for r in refs]) == q0.digest([asdict(r) for r in q0.development_references()])


def test_incomplete_review_duplicate_pairs_and_reference_mismatch():
    provenance = {"dataset_sha256": "a", "model": "m", "split": "dev", "execution": "fixture"}
    report = {"provenance": provenance, "results": [{"idx": "1", "expected": "2", "actual": "2", "status": "correct"}],
              "summary": {"usage": {}}}
    other = copy.deepcopy(report)
    other["results"].append(other["results"][0])
    with pytest.raises(ValueError, match="duplicate"):
        q0.paired_comparison(report, other)
    other = copy.deepcopy(report)
    other["results"][0]["expected"] = "3"
    with pytest.raises(ValueError, match="reference"):
        q0.paired_comparison(report, other)
    packet = q0.review_packet([{"idx": "1", "problem": "p", "answer": "2"}], report, salt="x")
    a = {"reviewer": "a", "packet_sha256": packet["packet_sha256"], "decisions": {}}
    b = {**a, "reviewer": "b"}
    with pytest.raises(ValueError, match="incomplete"):
        q0.reconcile_reviews(packet, a, b)
