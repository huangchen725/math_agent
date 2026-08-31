import pytest
import requests

from math_agent import llm_client
from math_agent.competition_policy import FORMAL_COMPETITION_MODEL, OFFICIAL_API_BASE
from math_agent.llm_client import InternChatClient


@pytest.fixture(autouse=True)
def _formal_client_environment(monkeypatch):
    monkeypatch.setenv("COMPETITION_MODE", "1")
    monkeypatch.setenv("INTERN_MODEL", FORMAL_COMPETITION_MODEL)
    monkeypatch.setenv("INTERN_API_BASE", OFFICIAL_API_BASE)


def _http_response(status: int, payload=None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://example.invalid/chat"
    if payload is not None:
        response._content = llm_client.json.dumps(payload).encode("utf-8")
        response.headers["Content-Type"] = "application/json"
    return response


def test_client_does_not_retry_authentication_error(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return _http_response(401)

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = InternChatClient(retry=3)
    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "hello"}])
    assert len(calls) == 1


def test_client_retries_server_error(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return _http_response(500)

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
    client = InternChatClient(retry=2)
    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "hello"}])
    assert len(calls) == 2


def test_client_retries_platform_rate_limit_returned_as_400(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    calls = []
    limited = {
        "error": {
            "type": "invalid_request_error",
            "message": "请求过于频繁，请稍后再试",
        }
    }
    success = {"choices": [{"message": {"content": "ok"}}]}

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return _http_response(400, limited)
        return _http_response(200, success)

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda _: None)
    client = InternChatClient(retry=2)

    assert client.chat([{"role": "user", "content": "hello"}]) == "ok"
    assert len(calls) == 2


def test_client_does_not_retry_generic_bad_request(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return _http_response(
            400,
            {"error": {"type": "invalid_request_error", "message": "invalid n"}},
        )

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    client = InternChatClient(retry=3)

    with pytest.raises(RuntimeError):
        client.chat([{"role": "user", "content": "hello"}])
    assert len(calls) == 1


def test_client_returns_text_when_tool_calls_is_empty(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    payload = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _http_response(200, payload))
    client = InternChatClient(retry=1)
    assert client.chat([{"role": "user", "content": "hello"}]) == "ok"


def test_client_returns_usage_atomically_without_changing_text_contract(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    payload = {
        "id": "request-1",
        "model": "test-model",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _http_response(200, payload))
    client = InternChatClient(retry=1)

    response, metadata = client.chat_with_metadata(
        [{"role": "user", "content": "hello"}]
    )

    assert response == "ok"
    assert metadata["usage"]["total_tokens"] == 5
    assert metadata["finish_reason"] == "length"
    assert not hasattr(client, "get_last_response_meta")


@pytest.mark.parametrize("kwargs", [{"stream": True}, {"n": 2}])
def test_client_rejects_competition_incompatible_options(monkeypatch, kwargs):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    client = InternChatClient(retry=1)
    with pytest.raises(ValueError):
        client.chat([{"role": "user", "content": "hello"}], **kwargs)


def test_client_rejects_non_s1_model_in_default_competition_mode(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    monkeypatch.setenv("INTERN_MODEL", "intern-s2-preview")

    with pytest.raises(RuntimeError, match="Competition mode permits only intern-s1"):
        InternChatClient(retry=1)


def test_client_allows_explicit_non_submission_model_experiment(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    monkeypatch.setenv("COMPETITION_MODE", "0")
    monkeypatch.setenv("INTERN_MODEL", "intern-s2-preview")

    client = InternChatClient(retry=1)

    assert client.model == "intern-s2-preview"
    assert client.competition_mode is False


def test_client_rejects_non_official_api_base_even_for_experiments(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    monkeypatch.setenv("COMPETITION_MODE", "0")
    monkeypatch.setenv("INTERN_API_BASE", "https://example.invalid/chat")

    with pytest.raises(RuntimeError, match="official Intern API endpoint"):
        InternChatClient(retry=1)
