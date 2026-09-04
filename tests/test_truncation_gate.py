from evaluation.scoring.truncation_gate import (
    combine_summaries,
    evaluate_truncation_gate,
    wilson_upper_one_sided,
)


def report(rate_percent: int):
    requests = 2000
    truncated = requests * rate_percent // 100
    return {
        "summary": {
            "total": 100,
            "correct": 22,
            "no_answer": 0,
            "invalid": 0,
            "conservative_accuracy": 0.22,
            "truncation": {
                "request_count": requests,
                "truncated_count": truncated,
                "candidate_generation": {
                    "request_count": 1200,
                    "truncated_count": 1200 * rate_percent // 100,
                },
                "by_stage": {
                    "policy_plain": {
                        "request_count": 1200,
                        "truncated_count": 1200 * rate_percent // 100,
                    }
                },
                "problems_with_truncation": 20,
                "recovery": {
                    "required": truncated,
                    "handled": truncated,
                    "succeeded": truncated,
                    "failed": 0,
                },
                "truncated_problems_with_valid_answer": 20,
                "truncated_fragments_in_final": 0,
            },
        }
    }


def test_four_percent_simulation_passes_formal_gate():
    result = evaluate_truncation_gate(report(4))

    assert result["passed"] is True
    assert result["metrics"]["one_sided_wilson_95_upper"] < 0.05


def test_six_percent_simulation_fails_formal_gate():
    result = evaluate_truncation_gate(report(6))

    assert result["passed"] is False
    assert result["checks"]["point_rate_below_target"] is False


def test_leaked_fragment_forces_gate_failure():
    data = report(4)
    data["summary"]["truncation"]["truncated_fragments_in_final"] = 1

    result = evaluate_truncation_gate(data)

    assert result["passed"] is False
    assert result["checks"]["truncated_fragments_in_final_zero"] is False


def test_1082_requests_accept_at_most_42_truncations():
    assert wilson_upper_one_sided(42, 1082) < 0.05
    assert wilson_upper_one_sided(43, 1082) >= 0.05


def test_combining_three_reports_preserves_stage_and_recovery_counts():
    combined = combine_summaries([report(4), report(4), report(4)])

    assert combined["truncation"]["request_count"] == 6000
    assert combined["truncation"]["by_stage"]["policy_plain"]["request_count"] == 3600
    assert combined["truncation"]["recovery"]["coverage"] == 1.0
