"""Vision language model clients of the Anomaly Assistant (no network: mocked transports and a fake Claude client)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from pathscope.anomaly.llm import client as llm_client
from pathscope.anomaly.llm.client import (
    FALLBACK_BETA,
    LLMError,
    interpret,
    list_models,
    sample_pictures,
)
from pathscope.anomaly.llm.settings import KeyStore, LLMSettings

ANSWER = {"verdict": "confirmed", "category": "object_added", "description": "An orange box appeared on the Test floor.", "confidence": 0.9, "evidence": "new box"}
RECORD = {**llm_client.TEST_RECORD}


def mock_http(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def openai_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}], "usage": {"prompt_tokens": 900, "completion_tokens": 40}})


def test_openai_compatible_request_carries_pictures_and_reads_json():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return openai_reply(json.dumps(ANSWER))

    s = LLMSettings(provider="openai", model="gpt-5-mini")
    r = interpret(s, "sk-test", RECORD, sample_pictures(), http=mock_http(handler))
    body = seen["body"]
    assert seen["url"] == "https://api.openai.com/v1/chat/completions" and seen["auth"] == "Bearer sk-test"
    assert body["model"] == "gpt-5-mini" and body["max_completion_tokens"] == 2048 and "temperature" not in body
    assert body["response_format"] == {"type": "json_object"}
    parts = body["messages"][1]["content"]
    assert parts[0]["type"] == "text" and "Test floor" in parts[0]["text"]
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"] and parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert r.verdict == "confirmed" and r.images_sent == 2 and r.provider == "openai" and r.latency_ms >= 0


def test_local_server_without_json_mode_is_retried_without_it():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"error": {"message": "response_format not supported"}})
        return openai_reply("Sure! " + json.dumps(ANSWER))

    s = LLMSettings(provider="local", model="qwen2.5vl:3b", extra_body={"keep_alive": "10m"})
    r = interpret(s, None, RECORD, sample_pictures(), http=mock_http(handler))
    assert len(calls) == 2 and "response_format" not in calls[1]
    assert calls[1]["max_tokens"] == 2048 and calls[1]["temperature"] == 0.2 and calls[1]["keep_alive"] == "10m"
    assert r.description.startswith("An orange box")


def test_text_only_providers_get_no_pictures():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        return openai_reply(json.dumps({**ANSWER, "verdict": "uncertain"}))

    r = interpret(LLMSettings(provider="deepseek"), "k", RECORD, sample_pictures(), http=mock_http(handler))
    user = seen["body"]["messages"][1]["content"]
    assert isinstance(user, str) and "No pictures are available" in user
    assert r.images_sent == 0 and seen["body"]["model"] == "deepseek-chat"
    # A user can also keep pictures on premises with any provider
    r2 = interpret(LLMSettings(provider="openai", send_images=False), "k", RECORD, sample_pictures(), http=mock_http(handler))
    assert r2.images_sent == 0


def test_gemini_request_and_blocked_answers():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-goog-api-key")
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}}]})

    s = LLMSettings(provider="gemini", extra_body={"generationConfig": {"thinkingConfig": {"thinkingBudget": 0}}})
    r = interpret(s, "g-key", RECORD, sample_pictures(), http=mock_http(handler))
    assert seen["url"].endswith("/models/gemini-2.5-flash:generateContent") and seen["key"] == "g-key"
    gen = seen["body"]["generationConfig"]
    assert gen["responseMimeType"] == "application/json" and gen["thinkingConfig"] == {"thinkingBudget": 0} and gen["maxOutputTokens"] == 2048
    assert [list(p) for p in seen["body"]["contents"][0]["parts"]] == [["text"], ["inline_data"], ["inline_data"]]
    assert r.category == "object_added"
    blocked = mock_http(lambda req: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(LLMError, match="blocked: SAFETY"):
        interpret(s, "g-key", RECORD, sample_pictures(), http=blocked)


class FakeClaude:
    def __init__(self, stop_reason="end_turn", text=json.dumps(ANSWER)):
        self.calls = []
        reply = SimpleNamespace(stop_reason=stop_reason, stop_details=SimpleNamespace(category="cyber") if stop_reason == "refusal" else None,
                                content=[SimpleNamespace(type="text", text=text)], usage=SimpleNamespace(input_tokens=1200, output_tokens=60))

        def create(**kw):
            self.calls.append(kw)
            return reply

        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: create(beta=True, **kw)))


def test_claude_uses_structured_output_low_effort_and_refusal_fallbacks(monkeypatch):
    fake = FakeClaude()
    monkeypatch.setattr(llm_client, "_anthropic_client", lambda s, key: fake)
    r = interpret(LLMSettings(provider="anthropic"), "sk-ant", RECORD, sample_pictures())
    call = fake.calls[-1]
    assert call["model"] == "claude-opus-5" and call.get("beta") is True
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert call["output_config"]["effort"] == "low" and call["output_config"]["format"]["type"] == "json_schema"
    content = call["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"] and content[0]["source"]["media_type"] == "image/jpeg"
    assert r.verdict == "confirmed" and r.usage == {"input_tokens": 1200, "output_tokens": 60}
    # Haiku: no effort parameter, no fallbacks, the plain endpoint
    interpret(LLMSettings(provider="anthropic", model="claude-haiku-4-5"), "sk-ant", RECORD, sample_pictures())
    call = fake.calls[-1]
    assert "beta" not in call and "fallbacks" not in call and "effort" not in call["output_config"]


def test_claude_refusal_is_reported(monkeypatch):
    monkeypatch.setattr(llm_client, "_anthropic_client", lambda s, key: FakeClaude(stop_reason="refusal", text=""))
    with pytest.raises(LLMError, match="declined"):
        interpret(LLMSettings(provider="anthropic"), "sk-ant", RECORD, sample_pictures())


def test_missing_keys_and_bad_answers_are_clear_errors():
    with pytest.raises(LLMError, match="needs an API key"):
        interpret(LLMSettings(provider="openai"), None, RECORD, [])
    with pytest.raises(LLMError, match="No vision language model"):
        interpret(LLMSettings(), None, RECORD, [])
    with pytest.raises(LLMError, match="Set the base URL"):
        interpret(LLMSettings(provider="custom", model="m"), None, RECORD, [])
    prose = mock_http(lambda req: openai_reply("Something appeared, I think."))
    with pytest.raises(LLMError, match="did not answer with JSON"):
        interpret(LLMSettings(provider="local"), None, RECORD, [], http=prose)
    server_error = mock_http(lambda req: httpx.Response(500, json={"error": "model not loaded"}))
    with pytest.raises(LLMError, match="HTTP 500: model not loaded"):
        interpret(LLMSettings(provider="local"), None, RECORD, [], http=server_error)


def test_keys_are_kept_apart_and_env_wins(tmp_path, monkeypatch):
    store = KeyStore(tmp_path)
    for name in ("PATHSCOPE_LLM_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    store.set("openai", "sk-from-file-1234")
    assert store.get("openai") == ("sk-from-file-1234", "file")
    assert store.describe("openai") == {"set": True, "source": "file", "hint": "…1234"}
    assert store.get("gemini") == (None, "none")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert store.get("openai") == ("sk-env", "env:OPENAI_API_KEY")
    store.set("openai", "")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert store.get("openai") == (None, "none")


def test_models_of_a_local_server_are_listed(monkeypatch):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/models":
            return httpx.Response(404)
        return httpx.Response(200, json={"models": [{"name": "qwen2.5vl:3b"}, {"name": "gemma3:4b"}]})

    real = httpx.Client
    monkeypatch.setattr(llm_client.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler)))
    assert list_models(LLMSettings(provider="local"), None) == ["gemma3:4b", "qwen2.5vl:3b"]


def test_ollama_uses_its_native_api_with_a_larger_context():
    llm_client._OLLAMA_SEEN.clear()
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.34.3"})
        seen["path"], seen["body"] = req.url.path, json.loads(req.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": json.dumps(ANSWER)}, "prompt_eval_count": 4900, "eval_count": 50, "load_duration": 2_000_000})

    r = interpret(LLMSettings(provider="local", model="qwen2.5vl:7b"), None, RECORD, sample_pictures(), http=mock_http(handler))
    body = seen["body"]
    assert seen["path"] == "/api/chat" and body["options"]["num_ctx"] == 8192 and body["format"]["required"][0] == "verdict"
    assert len(body["messages"][1]["images"]) == 2 and r.usage["input_tokens"] == 4900 and r.verdict == "confirmed"
    llm_client._OLLAMA_SEEN.clear()


def test_a_too_small_context_is_retried_with_fewer_smaller_pictures():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(404)
        body = json.loads(req.content)
        calls.append(len(body["messages"][1]["content"]) - 1)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"message": "request (4888 tokens) exceeds the available context size (4096 tokens)"}})
        return openai_reply(json.dumps(ANSWER))

    four = sample_pictures() * 2
    r = interpret(LLMSettings(provider="local", json_mode=False), None, RECORD, four, http=mock_http(handler))
    assert calls == [4, 2] and r.images_sent == 2 and r.usage.get("reduced_pictures") is True
