import pytest
import requests

import llm_client
from llm_client import InternChatClient


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


def test_client_returns_text_when_tool_calls_is_empty(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    payload = {"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _http_response(200, payload))
    client = InternChatClient(retry=1)
    assert client.chat([{"role": "user", "content": "hello"}]) == "ok"


def test_client_exposes_usage_without_changing_text_contract(monkeypatch):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    payload = {
        "id": "request-1",
        "model": "test-model",
        "choices": [{"message": {"content": "ok"}}],
        "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
    }
    monkeypatch.setattr(llm_client.requests, "post", lambda *a, **k: _http_response(200, payload))
    client = InternChatClient(retry=1)

    assert client.chat([{"role": "user", "content": "hello"}]) == "ok"
    assert client.get_last_response_meta()["usage"]["total_tokens"] == 5


@pytest.mark.parametrize("kwargs", [{"stream": True}, {"n": 2}])
def test_client_rejects_competition_incompatible_options(monkeypatch, kwargs):
    monkeypatch.setenv("INTERN_API_KEY", "test-key")
    client = InternChatClient(retry=1)
    with pytest.raises(ValueError):
        client.chat([{"role": "user", "content": "hello"}], **kwargs)
