"""Offline CLI smoke and denial paths; no real network or model requests."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from evaluation import q2_pipeline as q2
from test_q2_pipeline import bundle_at, OwnedFixtureClient

ROOT = Path(__file__).resolve().parents[1]


def command(*args, success=True):
    result = subprocess.run([sys.executable,"-m","evaluation.q2_pipeline",*map(str,args)],
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True, timeout=30)
    assert (result.returncode == 0) is success, result.stderr
    return json.loads(result.stdout) if success else result.stderr


def test_cli_freeze_reserve_record_analyze_and_denials(tmp_path):
    bundle=bundle_at(tmp_path/"bundle",count=4)
    study=tmp_path/"study"
    frozen=command("freeze",bundle,study,"--candidates","calibrated_verifier")
    assert frozen["request_ceiling_dev"]==2*16*3*2
    ticket=command("reserve",study,"baseline",0)
    client=q2.ObservedTextClient(OwnedFixtureClient())
    run=tmp_path/"run"
    q2.run_reserved(study,ticket["slot"],run,client)
    receipt=tmp_path/"receipt.json"
    q2.write(receipt,q2.receipt_from_observations(run,client.observations))
    record=command("record",study,ticket["slot"],run,"--receipt",receipt)
    assert record["execution"]=="fixture" and record["metrics_complete"]
    assert command("analyze",study)["status"]=="incomplete"
    command("select",study,"calibrated_verifier",success=False)
    command("reserve",study,"baseline",0,"--split","test",success=False)
    command("accept",study,success=False)
    delivery=command("delivery",study,"--expected-commit","bad","--remote-commit","bad")
    assert not delivery["ready_for_submission_review"]
    assert delivery["captured_matches"] is None


@pytest.mark.parametrize("repeats", [0,1,2,11,True])
def test_repeat_limit_validated_before_mutation(tmp_path,repeats):
    with pytest.raises(ValueError):
        q2.create_study(tmp_path/"absent",tmp_path/"study",repeats=repeats)
    assert not (tmp_path/"study").exists()


@pytest.mark.parametrize("values", [[], ["baseline"], ["unknown"], ["no_tools","no_tools"]])
def test_invalid_candidates_never_create_study(tmp_path,values):
    with pytest.raises(ValueError):
        q2.create_study(tmp_path/"absent",tmp_path/"study",candidates=values)


def test_reader_rejects_nonfinite_json(tmp_path):
    path=tmp_path/"bad.json"
    path.write_text('{"metric": NaN}',encoding="utf-8")
    with pytest.raises(ValueError):q2.read(path)


def test_cli_has_no_paid_execute_mode():
    command("execute",success=False)
