import json

import pytest

from evaluation.q0_pipeline import reconcile_reviews
from evaluation.xh202627_review_issues import assemble


def fixture():
    labels = [{"idx": "item-1", "problem": "Find all roots over the reals.", "answer": "1"}]
    issues = [{"idx": "item-1", "category": "reference_error", "basis": "PRIVATE_EARLIER_DIAGNOSIS"}]
    items = [{"idx": "item-1", "variant": variant, "actual": answer}
             for variant, answer in (("baseline", "1"), ("candidate", "-1,1"))]
    checkpoints = {(row["variant"], row["idx"]): {"idx": row["idx"], "final_response": "Saved reasoning: " + row["actual"]}
                   for row in items}
    return labels, issues, items, checkpoints


def test_packets_blind_variant_and_prior_diagnosis_without_mutating_originals():
    inputs = fixture()
    original = repr(inputs)
    artifacts = assemble(*inputs, salt="private-fixture-review-salt")
    assert repr(inputs) == original
    for key in ("packet-final", "packet-full"):
        serialized = json.dumps(artifacts[key])
        assert not any(x in serialized for x in ("baseline", "candidate", "item-1", "PRIVATE_EARLIER_DIAGNOSIS"))
        assert len(artifacts[key]["items"]) == 2
    assert all(not row["solution"] for row in artifacts["packet-final"]["items"])
    assert all(row["solution"] for row in artifacts["packet-full"]["items"])
    assert artifacts["packet-final"]["packet_sha256"] != artifacts["packet-full"]["packet_sha256"]
    assert artifacts["catalog"]["automatic_scores_overridden"] is False


@pytest.mark.parametrize("failure", ["duplicate_issue", "unknown_item", "duplicate_result", "missing_result", "checkpoint_mismatch"])
def test_incomplete_or_ambiguous_issue_binding_is_rejected(failure):
    labels, issues, items, checkpoints = fixture()
    if failure == "duplicate_issue":
        issues.append(issues[0])
    elif failure == "unknown_item":
        issues[0]["idx"] = "missing"
    elif failure == "duplicate_result":
        items.append(items[0])
    elif failure == "missing_result":
        items = []
    else:
        checkpoints[("baseline", "item-1")]["idx"] = "different"
    with pytest.raises(ValueError):
        assemble(labels, issues, items, checkpoints, salt="private-fixture-review-salt")


def test_prepared_packets_use_existing_independent_review_gate():
    packet = assemble(*fixture(), salt="private-fixture-review-salt")["packet-final"]
    first = {"reviewer": "reviewer-one", "packet_sha256": packet["packet_sha256"],
             "decisions": {row["review_id"]: "correct" for row in packet["items"]}}
    with pytest.raises(ValueError, match="distinct reviewers"):
        reconcile_reviews(packet, first, first)
    second = {**first, "reviewer": "reviewer-two", "decisions": dict.fromkeys(first["decisions"], "unknown")}
    assert all(row["status"] == "unknown" for row in reconcile_reviews(packet, first, second).values())
    packet["items"][0]["actual"] = "tampered"
    with pytest.raises(ValueError, match="packet changed"):
        reconcile_reviews(packet, first, second)
