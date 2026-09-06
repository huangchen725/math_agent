"""The diagnostic must measure truncation without copying response text or calling an API."""
import copy

import pytest

from evaluation.truncation_diagnostic import CASES, payload_for, response_summary


@pytest.mark.parametrize("thinking", [None, False])
def test_thinking_omission_is_distinct_from_false(thinking):
    request = {"messages": [{"role": "user", "content": "synthetic"}],
               "temperature": 0.0, "max_tokens": 512, "thinking_mode": thinking}
    original = copy.deepcopy(request)
    result = payload_for({"model": "synthetic"}, request)
    assert ("thinking_mode" in result) is (thinking is not None)
    assert result.get("thinking_mode") is thinking
    assert request == original
    assert not {"stream", "tools", "n", "meta_sink"} & result.keys()


@pytest.mark.parametrize("content", [None, "", "最终答案：2"])
@pytest.mark.parametrize("finish", ["length", "stop"])
def test_truncation_and_text_are_separate_observations(content, finish):
    result = response_summary({"model": "intern-s2-preview-397b", "choices": [
        {"finish_reason": finish, "message": {"content": content, "reasoning_content": "PRIVATE SYNTHETIC REASONING"}}],
        "usage": {"completion_tokens": 512}}, {"max_tokens": 512})
    assert result["finish_reason"] == finish
    assert result["reasoning_chars"] == len("PRIVATE SYNTHETIC REASONING")
    assert "PRIVATE" not in str(result)
    assert result["usage"]["prompt_tokens"] is None
    assert result["reported_completion_hits_requested_limit"]
    if finish == "length":
        assert not result["answer_eligible"]


@pytest.mark.parametrize("usage", [{}, {"total_tokens": True}, {"completion_tokens": -1}, {"prompt_tokens": float("nan")}])
def test_missing_or_invalid_usage_does_not_become_zero(usage):
    result = response_summary({"choices": [{"message": {"content": ""}}], "usage": usage}, {"max_tokens": 512})
    assert all(v is None for v in result["usage"].values())
    assert result["model_receipt"] is None
    assert result["finish_reason"] == "unknown"


def test_request_ceiling_is_explicit_and_bounded():
    assert len(CASES) * 2 == 18
    assert sum(limit for _, limit, _ in CASES) * 2 == 63488
    assert all(1 <= limit <= 8192 for _, limit, _ in CASES)


@pytest.mark.parametrize("limit", [8193, 16384, True])
def test_diagnostic_never_sends_above_official_bound(limit):
    with pytest.raises(ValueError):
        payload_for({"model": "synthetic"}, {"max_tokens": limit})
