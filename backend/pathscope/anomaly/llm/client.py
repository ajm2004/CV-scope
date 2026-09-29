"""Calls to the selected vision language model.

Three wire protocols cover the supported providers:

* OpenAI-compatible chat completions: OpenAI, OpenRouter, DeepSeek, local
  servers (Ollama, LM Studio, vLLM, llama.cpp) and other compatible APIs
* Gemini ``generateContent``
* Anthropic Claude through the official ``anthropic`` package

Each call sends one event's pictures and observations and returns an
``Interpretation``. Nothing here keeps state; budgets and queues live in the
service.
"""

from __future__ import annotations

import base64
import time
from dataclasses import asdict, dataclass, field

import httpx

from pathscope.anomaly.llm.prompt import (
    ANSWER_SCHEMA,
    SYSTEM_PROMPT,
    build_user_text,
    parse_answer,
    prepare_image,
)
from pathscope.anomaly.llm.settings import LLMSettings

# Claude models that take output_config.effort (the answer is short: low effort is enough)
_CLAUDE_EFFORT = ("claude-opus-5", "claude-sonnet-5", "claude-fable-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6", "claude-sonnet-4-6")
# Claude models with server-side refusal fallbacks
_CLAUDE_FALLBACK = ("claude-opus-5", "claude-fable-5-1")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """The model could not be asked or gave no usable answer."""


@dataclass
class Interpretation:
    verdict: str
    category: str
    description: str
    confidence: float
    evidence: str
    provider: str
    model: str
    latency_ms: float
    images_sent: int
    usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _deep_merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in (extra or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _error_text(r: httpx.Response) -> str:
    try:
        data = r.json()
        err = data.get("error") if isinstance(data, dict) else None
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if err:
            return str(err)[:300]
        return str(data)[:300]
    except ValueError:
        return r.text[:300]


# ---------------------------------------------------------------------------- protocols
def _openai(s: LLMSettings, key: str | None, user_text: str, images: list[bytes], client: httpx.Client, system: str = SYSTEM_PROMPT) -> tuple[str, dict]:
    content: list[dict] = [{"type": "text", "text": user_text}]
    for img in images:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}})
    body: dict = {"model": s.resolved_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": content if images else user_text}]}
    if s.provider == "openai":
        body["max_completion_tokens"] = s.max_output_tokens  # current OpenAI models; no temperature for reasoning models
    else:
        body["max_tokens"] = s.max_output_tokens
        body["temperature"] = 0.2
    if s.json_mode:
        body["response_format"] = {"type": "json_object"}
    body = _deep_merge(body, s.extra_body)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if s.provider == "openrouter":
        headers["X-Title"] = "CV-Scope Anomaly Assistant"
    url = f"{s.resolved_base_url}/chat/completions"
    r = client.post(url, json=body, headers=headers)
    if r.status_code == 400 and "response_format" in body and "response_format" not in s.extra_body:
        body.pop("response_format")  # some servers do not know JSON mode; the prompt asks for JSON anyway
        r = client.post(url, json=body, headers=headers)
    if r.status_code >= 400:
        raise LLMError(f"{s.info.name} answered HTTP {r.status_code}: {_error_text(r)}")
    data = r.json()
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"unexpected answer from {s.info.name}: {str(data)[:200]}") from exc
    text = msg.get("content")
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    if not text and msg.get("refusal"):
        raise LLMError(f"the model declined: {msg['refusal'][:200]}")
    return text or "", data.get("usage") or {}


_OLLAMA_SEEN: dict[str, bool] = {}


def _is_ollama(root: str, client: httpx.Client) -> bool:
    """Is this local server Ollama (its native API can set the context size)?"""
    if root not in _OLLAMA_SEEN:
        try:
            r = client.get(f"{root}/api/version")
            _OLLAMA_SEEN[root] = r.status_code == 200 and "version" in r.json()
        except Exception:  # noqa: BLE001 - any failure: use the OpenAI-compatible endpoint
            return False
    return _OLLAMA_SEEN[root]


def _ollama(s: LLMSettings, root: str, user_text: str, images: list[bytes], client: httpx.Client, system: str = SYSTEM_PROMPT, schema: dict = ANSWER_SCHEMA) -> tuple[str, dict]:
    """Ollama's native chat API: context size, structured JSON answer, pictures."""
    user: dict = {"role": "user", "content": user_text}
    if images:
        user["images"] = [base64.b64encode(img).decode() for img in images]
    body = {
        "model": s.resolved_model, "stream": False, "format": schema,
        "messages": [{"role": "system", "content": system}, user],
        "options": {"num_ctx": s.context_tokens, "temperature": 0.2, "num_predict": s.max_output_tokens},
    }
    body = _deep_merge(body, s.extra_body)
    r = client.post(f"{root}/api/chat", json=body)
    if r.status_code >= 400:
        raise LLMError(f"Ollama answered HTTP {r.status_code}: {_error_text(r)}")
    data = r.json()
    usage = {"input_tokens": data.get("prompt_eval_count"), "output_tokens": data.get("eval_count"), "load_ms": round((data.get("load_duration") or 0) / 1e6)}
    return (data.get("message") or {}).get("content") or "", usage


def _gemini(s: LLMSettings, key: str | None, user_text: str, images: list[bytes], client: httpx.Client, system: str = SYSTEM_PROMPT) -> tuple[str, dict]:
    if not key:
        raise LLMError("Gemini needs an API key.")
    parts: list[dict] = [{"text": user_text}]
    for img in images:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(img).decode()}})
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": s.max_output_tokens, "responseMimeType": "application/json"},
    }
    body = _deep_merge(body, s.extra_body)
    r = client.post(f"{s.resolved_base_url}/models/{s.resolved_model}:generateContent", json=body, headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    if r.status_code >= 400:
        raise LLMError(f"Gemini answered HTTP {r.status_code}: {_error_text(r)}")
    data = r.json()
    cands = data.get("candidates") or []
    if not cands:
        block = (data.get("promptFeedback") or {}).get("blockReason")
        raise LLMError(f"Gemini returned no answer{f' (blocked: {block})' if block else ''}.")
    text = "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []) if isinstance(p, dict))
    return text, data.get("usageMetadata") or {}


def _anthropic_client(s: LLMSettings, key: str | None):
    try:
        import anthropic
    except ImportError as exc:  # optional dependency
        raise LLMError("Claude needs the anthropic package: pip install anthropic (or pip install -e backend[llm]).") from exc
    kwargs: dict = {"timeout": s.timeout_s, "max_retries": 1}
    if key:
        kwargs["api_key"] = key
    if s.base_url.strip():
        kwargs["base_url"] = s.resolved_base_url
    return anthropic.Anthropic(**kwargs)


def _anthropic(s: LLMSettings, key: str | None, user_text: str, images: list[bytes], client_factory=_anthropic_client, system: str = SYSTEM_PROMPT, schema: dict = ANSWER_SCHEMA) -> tuple[str, dict]:
    import anthropic

    client = client_factory(s, key)
    model = s.resolved_model
    content: list[dict] = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(img).decode()}} for img in images]
    content.append({"type": "text", "text": user_text})
    output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
    if model.startswith(_CLAUDE_EFFORT):
        output_config["effort"] = "low"  # a two-sentence description does not need deep thinking
    kwargs: dict = {"model": model, "max_tokens": s.max_output_tokens, "system": system, "messages": [{"role": "user", "content": content}], "output_config": output_config}
    if s.extra_body:
        kwargs["extra_body"] = dict(s.extra_body)

    def create(kw: dict):
        if model.startswith(_CLAUDE_FALLBACK):
            # A declined request is re-run server-side on Anthropic's recommended fallback model
            return client.beta.messages.create(**kw, betas=[FALLBACK_BETA], fallbacks="default")
        return client.messages.create(**kw)

    try:
        try:
            resp = create(kwargs)
        except anthropic.BadRequestError as exc:
            if "output_config" not in str(exc) and "effort" not in str(exc) and "format" not in str(exc):
                raise
            # An older model without structured output or effort: ask with the prompt alone
            kwargs.pop("output_config", None)
            resp = create(kwargs)
    except anthropic.AuthenticationError as exc:
        raise LLMError("Anthropic rejected the API key.") from exc
    except anthropic.NotFoundError as exc:
        raise LLMError(f"Anthropic does not know the model '{model}'.") from exc
    except anthropic.RateLimitError as exc:
        raise LLMError("Anthropic rate limit reached; the event keeps its computer-vision summary.") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"Anthropic answered HTTP {exc.status_code}: {str(exc.message)[:300]}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"Anthropic could not be reached: {exc}") from exc
    if resp.stop_reason == "refusal":
        category = getattr(getattr(resp, "stop_details", None), "category", None)
        raise LLMError(f"Claude declined to describe this event{f' ({category})' if category else ''}.")
    text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
    usage = getattr(resp, "usage", None)
    return text, {"input_tokens": getattr(usage, "input_tokens", None), "output_tokens": getattr(usage, "output_tokens", None)} if usage else {}


# ---------------------------------------------------------------------------- public
def interpret(settings: LLMSettings, key: str | None, record: dict, pictures: list[tuple[str, bytes]], http: httpx.Client | None = None) -> Interpretation:
    """Ask the configured model about one anomaly. ``pictures`` = [(evidence name, JPEG bytes)]."""
    if not settings.enabled:
        raise LLMError("No vision language model is selected.")
    info = settings.info
    if info.needs_key and not key:
        raise LLMError(f"{info.name} needs an API key (Anomaly Assistant settings, or the {' / '.join(info.key_env) or 'PATHSCOPE_LLM_API_KEY'} environment variable).")
    if not settings.resolved_model:
        raise LLMError("Choose a model name.")
    if info.protocol != "anthropic" and not settings.resolved_base_url:
        raise LLMError("Set the base URL of the API.")
    use = pictures if (settings.send_images and info.vision) else []
    t0 = time.perf_counter()
    own = http is None
    client = http or httpx.Client(timeout=settings.timeout_s)

    def ask(chosen: list[tuple[str, bytes]], max_px: int) -> tuple[str, dict, int]:
        images = [prepare_image(data, max_px) for _, data in chosen]
        user_text = build_user_text(record, [name for name, _ in chosen])
        if info.protocol == "openai":
            root = settings.resolved_base_url[:-3] if settings.resolved_base_url.endswith("/v1") else settings.resolved_base_url
            if settings.provider == "local" and _is_ollama(root, client):
                return (*_ollama(settings, root, user_text, images, client), len(images))
            return (*_openai(settings, key, user_text, images, client), len(images))
        if info.protocol == "gemini":
            return (*_gemini(settings, key, user_text, images, client), len(images))
        if info.protocol == "anthropic":
            return (*_anthropic(settings, key, user_text, images, client_factory=_anthropic_client), len(images))
        raise LLMError(f"unsupported provider {settings.provider}")

    try:
        try:
            text, usage, n_images = ask(use, settings.image_max_px)
        except LLMError as exc:
            if not use or "context" not in str(exc).lower():
                raise
            # A small local context window: fewer, smaller pictures
            text, usage, n_images = ask(use[:2], max(256, settings.image_max_px // 2))
            usage = {**usage, "reduced_pictures": True}
    except httpx.TimeoutException as exc:
        raise LLMError(f"{info.name} did not answer within {settings.timeout_s:.0f} s.") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{info.name} could not be reached at {settings.resolved_base_url}: {exc}") from exc
    finally:
        if own:
            client.close()
    try:
        answer = parse_answer(text)
    except ValueError as exc:
        raise LLMError(str(exc)) from exc
    return Interpretation(
        verdict=answer["verdict"], category=answer["category"], description=answer["description"], confidence=answer["confidence"], evidence=answer["evidence"],
        provider=settings.provider, model=settings.resolved_model, latency_ms=round((time.perf_counter() - t0) * 1000.0, 1), images_sent=n_images, usage=usage,
    )


def complete_json(settings: LLMSettings, key: str | None, system: str, user_text: str, schema: dict, http: httpx.Client | None = None) -> tuple[dict, dict]:
    """A text-only question with a JSON answer to the selected model (used for
    optional summaries of deterministic facts). Returns (answer, usage)."""
    import json

    if not settings.enabled:
        raise LLMError("No language model is selected (Anomaly Assistant settings).")
    info = settings.info
    if info.needs_key and not key:
        raise LLMError(f"{info.name} needs an API key (Anomaly Assistant settings).")
    own = http is None
    client = http or httpx.Client(timeout=settings.timeout_s)
    try:
        if info.protocol == "openai":
            root = settings.resolved_base_url[:-3] if settings.resolved_base_url.endswith("/v1") else settings.resolved_base_url
            if settings.provider == "local" and _is_ollama(root, client):
                text, usage = _ollama(settings, root, user_text, [], client, system=system, schema=schema)
            else:
                text, usage = _openai(settings, key, user_text, [], client, system=system)
        elif info.protocol == "gemini":
            text, usage = _gemini(settings, key, user_text, [], client, system=system)
        elif info.protocol == "anthropic":
            text, usage = _anthropic(settings, key, user_text, [], client_factory=_anthropic_client, system=system, schema=schema)
        else:
            raise LLMError(f"unsupported provider {settings.provider}")
    except httpx.TimeoutException as exc:
        raise LLMError(f"{info.name} did not answer within {settings.timeout_s:.0f} s.") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{info.name} could not be reached: {exc}") from exc
    finally:
        if own:
            client.close()
    t = (text or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        t = t[t.find("{"):] if "{" in t else t
    try:
        start, end = t.find("{"), t.rfind("}")
        data = json.loads(t[start:end + 1]) if start >= 0 and end > start else {}
    except ValueError as exc:
        raise LLMError("The model's answer was not the expected JSON.") from exc
    if not isinstance(data, dict):
        raise LLMError("The model's answer was not the expected JSON.")
    return data, usage


def list_models(settings: LLMSettings, key: str | None, timeout_s: float = 5.0) -> list[str]:
    """Models a local or OpenAI-compatible server offers (best effort)."""
    info = settings.info
    if info.protocol != "openai":
        return list(info.models)
    base = settings.resolved_base_url
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    with httpx.Client(timeout=timeout_s) as client:
        try:
            r = client.get(f"{base}/models", headers=headers)
            if r.status_code < 400:
                data = r.json().get("data") or []
                names = sorted({str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")})
                if names:
                    return names
        except (httpx.HTTPError, ValueError):
            pass
        if settings.provider == "local":  # Ollama's own listing
            root = base[:-3] if base.endswith("/v1") else base
            try:
                r = client.get(f"{root}/api/tags")
                if r.status_code < 400:
                    return sorted(str(m.get("name")) for m in r.json().get("models") or [] if m.get("name"))
            except (httpx.HTTPError, ValueError):
                pass
    raise LLMError(f"Could not list models at {base}. Is the server running?")


def sample_pictures() -> list[tuple[str, bytes]]:
    """A tiny synthetic before/after pair: an orange box appears on a grey floor."""
    import cv2
    import numpy as np

    before = np.full((240, 320, 3), 150, np.uint8)
    cv2.rectangle(before, (0, 160), (319, 239), (120, 130, 140), -1)
    after = before.copy()
    cv2.rectangle(after, (140, 150), (200, 210), (40, 120, 230), -1)
    over = after.copy()
    cv2.rectangle(over, (134, 144), (206, 216), (40, 40, 235), 2)
    enc = lambda img: cv2.imencode(".jpg", img)[1].tobytes()  # noqa: E731
    return [("before", enc(before)), ("overlay", enc(over))]


TEST_RECORD = {
    "zone_id": "test", "zone_name": "Test floor", "expected_state": "The floor is empty.", "kind": "appeared", "confidence": 0.9, "area_pct": 12.0,
    "bbox": [0.43, 0.62, 0.63, 0.88], "confirmed_after_s": 2.5, "duration_s": None, "subjects": [], "summary": "Something appeared in Test floor (12.0% of the zone).",
}
