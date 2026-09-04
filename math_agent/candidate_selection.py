"""Evidence-first candidate selection with the original majority fallback."""

from __future__ import annotations

from .agent_types import Candidate
from .budget import ExecutionBudget


def select_candidate(
    scored: list[Candidate],
    trace: list[dict],
    *,
    budget: ExecutionBudget | None = None,
) -> tuple[str, str]:
    if not scored:
        return "", ""
    eligible = [
        candidate
        for candidate in scored
        if candidate.answer.raw and not candidate.metadata.get("truncated", False)
    ]
    if not eligible:
        return "", ""

    deterministic_passes = [
        candidate
        for candidate in eligible
        if any(
            evidence.source.startswith("deterministic:") and evidence.status == "pass"
            for evidence in candidate.verifications
        )
    ]
    if deterministic_passes:
        passed_keys = {candidate.answer.canonical for candidate in deterministic_passes}
        if len(passed_keys) == 1:
            selected = max(deterministic_passes, key=lambda item: item.confidence)
            trace.append({
                "step": "deterministic_selection",
                "content": {
                    "status": "selected",
                    "candidate_ids": [
                        candidate.metadata.get("candidate_id")
                        for candidate in deterministic_passes
                    ],
                    "evidence_sources": sorted({
                        evidence.source
                        for candidate in deterministic_passes
                        for evidence in candidate.verifications
                        if evidence.source.startswith("deterministic:")
                        and evidence.status == "pass"
                    }),
                },
            })
            record_final_source(selected, trace, budget)
            return selected.answer.normalized, selected.content
        trace.append({
            "step": "deterministic_selection",
            "content": {
                "status": "conflict_fallback",
                "candidate_ids": [
                    candidate.metadata.get("candidate_id")
                    for candidate in deterministic_passes
                ],
            },
        })

    groups = {}
    for candidate in eligible:
        groups.setdefault(candidate.answer.canonical, []).append(candidate)
    best_key = max(
        groups,
        key=lambda key: (
            len(groups[key]),
            max(candidate.confidence for candidate in groups[key]),
        ),
    )
    best_group = groups[best_key]
    if len(best_group) >= 2:
        trace.append({
            "step": "self_consistency",
            "content": f"答案 '{best_group[0].answer.normalized}' 获得 {len(best_group)} 票一致",
        })
        selected = max(best_group, key=lambda item: item.confidence)
        record_final_source(selected, trace, budget)
        return best_group[0].answer.normalized, selected.content

    selected = max(eligible, key=lambda item: item.confidence)
    trace.append({
        "step": "select_final",
        "content": f"选最高分: {selected.answer.normalized}",
    })
    record_final_source(selected, trace, budget)
    return selected.answer.normalized, selected.content


def record_final_source(
    candidate: Candidate,
    trace: list[dict],
    budget: ExecutionBudget | None = None,
) -> None:
    source = str(candidate.metadata.get("source") or candidate.strategy)
    if budget is not None:
        budget.set_final_answer_source(source)
    trace.append({
        "step": "final_answer_source",
        "content": {
            "source": source,
            "candidate_id": candidate.metadata.get("candidate_id"),
            "reasoning_included": True,
        },
    })
