"""Which vision language model interprets anomalies: one provider and model at a time.

The deployment chooses one active provider. Everything works without one:
the deterministic detection, the evidence and the one-line summaries do not
depend on a model. API keys are kept in their own file in the data directory
(``anomaly/llm_keys.json``, never in the database or an export) or come from
the environment; the API never returns them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

ProviderId = Literal["none", "local", "openai", "anthropic", "gemini", "openrouter", "deepseek", "custom"]
Protocol = Literal["openai", "anthropic", "gemini"]

SETTING_KEY = "anomaly.llm"


class ProviderInfo(BaseModel):
    id: ProviderId
    name: str
    protocol: Protocol | None
    base_url: str = ""
    default_model: str = ""
    models: list[str] = Field(default_factory=list)  # suggestions; any model name can be typed
    key_env: list[str] = Field(default_factory=list)
    needs_key: bool = True
    vision: bool = True  # False: only the written observations are sent, no pictures
    local: bool = False  # runs on this machine or network: pictures stay on premises
    note: str = ""


PROVIDERS: list[ProviderInfo] = [
    ProviderInfo(id="none", name="No model (deterministic only)", protocol=None, needs_key=False, vision=False, note="Events carry the computer-vision summary only. Nothing leaves this machine."),
    ProviderInfo(
        id="local", name="Local model (Ollama, LM Studio, vLLM, llama.cpp)", protocol="openai", base_url="http://127.0.0.1:11434/v1", default_model="qwen2.5vl:7b",
        models=["qwen2.5vl:3b", "gemma3:4b", "qwen2.5vl:7b", "llama3.2-vision:11b", "gemma3:12b", "qwen2.5vl:32b"], needs_key=False, local=True,
        note="Any server with an OpenAI-compatible /v1/chat/completions endpoint and a vision model. Ollama: http://127.0.0.1:11434/v1, LM Studio: http://127.0.0.1:1234/v1, vLLM: http://127.0.0.1:8000/v1, llama.cpp server: http://127.0.0.1:8080/v1.",
    ),
    ProviderInfo(
        id="openai", name="OpenAI", protocol="openai", base_url="https://api.openai.com/v1", default_model="gpt-5-mini", models=["gpt-5-mini", "gpt-5", "gpt-4.1-mini", "gpt-4o-mini"],
        key_env=["OPENAI_API_KEY"], note="Pictures are sent to OpenAI. Model names change; use one your account lists.",
    ),
    ProviderInfo(
        id="anthropic", name="Anthropic Claude", protocol="anthropic", base_url="https://api.anthropic.com", default_model="claude-opus-5", models=["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"],
        key_env=["ANTHROPIC_API_KEY"], note="Pictures are sent to Anthropic. Uses the official anthropic Python package (pip install anthropic). Claude Haiku 4.5 costs least per event; Claude Opus 5 describes best.",
    ),
    ProviderInfo(
        id="gemini", name="Google Gemini", protocol="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", default_model="gemini-2.5-flash", models=["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"],
        key_env=["GEMINI_API_KEY", "GOOGLE_API_KEY"], note="Pictures are sent to Google.",
    ),
    ProviderInfo(
        id="openrouter", name="OpenRouter", protocol="openai", base_url="https://openrouter.ai/api/v1", default_model="google/gemini-2.5-flash",
        models=["google/gemini-2.5-flash", "openai/gpt-5-mini", "qwen/qwen2.5-vl-72b-instruct"], key_env=["OPENROUTER_API_KEY"],
        note="Routes to many providers; pick a model that accepts images. Pictures go to OpenRouter and the model's provider.",
    ),
    ProviderInfo(
        id="deepseek", name="DeepSeek", protocol="openai", base_url="https://api.deepseek.com/v1", default_model="deepseek-chat", models=["deepseek-chat"], key_env=["DEEPSEEK_API_KEY"], vision=False,
        note="DeepSeek's API models read text only: CV-Scope sends the written observations (zone, kind, objects, timing) without pictures, so the model cannot check the picture itself.",
    ),
    ProviderInfo(
        id="custom", name="Other compatible API", protocol="openai", base_url="", default_model="", needs_key=False,
        note="Any provider with an OpenAI-compatible chat completions endpoint (Azure OpenAI through a compatible gateway, Together, Groq, Mistral, a company proxy). Set the base URL up to /v1.",
    ),
]
PROVIDERS_BY_ID = {p.id: p for p in PROVIDERS}


# Local vision language models: what fits where. Sizes are for 4-bit
# quantized weights as Ollama ships them, plus working memory for a few
# pictures; they vary with the runtime, the quantization and the context size.
LOCAL_MODELS: list[dict[str, Any]] = [
    {"model": "qwen2.5vl:3b", "download_gb": 3.2, "tier": "light", "vram_gb": 4, "note": "Recommended starting point on 6-8 GB cards next to the detector. Good at short descriptions; follows the JSON answer format well."},
    {"model": "gemma3:4b", "download_gb": 3.3, "tier": "light", "vram_gb": 5, "note": "Light and fast; descriptions a little less precise about positions."},
    {"model": "moondream", "download_gb": 1.7, "tier": "light", "vram_gb": 2, "note": "Tiny (1.8 B). Useful on CPUs and small GPUs for a caption; weak at following the answer format, so the verdict is often 'uncertain'."},
    {"model": "qwen2.5vl:7b", "download_gb": 6.0, "tier": "capable", "vram_gb": 8, "note": "Recommended on 12 GB cards (for example an RTX 4070 SUPER): noticeably better at comparing the before and after pictures."},
    {"model": "llama3.2-vision:11b", "download_gb": 7.8, "tier": "capable", "vram_gb": 10, "note": "Good general descriptions; slower per picture."},
    {"model": "gemma3:12b", "download_gb": 8.1, "tier": "capable", "vram_gb": 11, "note": "Strong descriptions; fills a 12 GB card on its own."},
    {"model": "qwen2.5vl:32b", "download_gb": 21, "tier": "large", "vram_gb": 24, "note": "Needs a 24 GB card or spills into system memory and becomes very slow."},
    {"model": "qwen2.5vl:72b", "download_gb": 49, "tier": "large", "vram_gb": 48, "note": "Server-class (two 24 GB cards or more)."},
]

LOCAL_WARNING = (
    "A local vision model shares the GPU with the detector, the tracker and the recognition modules. "
    "Larger models need much more GPU memory (VRAM) and system memory, take longer per event (from about one second for a 3 B model "
    "to tens of seconds for 30 B+ models, much longer when the model does not fit in VRAM and runs partly on the CPU), and every camera "
    "that raises events at the same time queues behind the others. Start with a light model, watch the latency on the Anomaly Assistant "
    "page, and keep 'Calls at the same time' at 1 unless the GPU has room to spare. Only confirmed events are sent, never the video stream."
)


class LLMSettings(BaseModel):
    provider: ProviderId = "none"
    model: str = ""
    base_url: str = ""  # empty: the provider's default
    timeout_s: float = Field(default=60.0, ge=2.0, le=600.0)
    max_output_tokens: int = Field(default=2048, ge=64, le=16000)  # room for models that reason before answering
    # Pictures sent per event (reference, event with the change outlined, and close-ups)
    send_images: bool = True
    image_max_px: int = Field(default=768, ge=256, le=2048)
    include_crops: bool = True
    # Budget and load
    max_concurrent: int = Field(default=1, ge=1, le=8)
    max_calls_per_hour: int = Field(default=120, ge=1, le=100000)
    queue_limit: int = Field(default=50, ge=1, le=1000)
    # Merged into the request body as is (for example {"reasoning_effort": "low"} or {"keep_alive": "10m"})
    extra_body: dict[str, Any] = Field(default_factory=dict)
    # Ask the server for a JSON answer (OpenAI-compatible servers; turned off automatically when a server rejects it)
    json_mode: bool = True
    # Context window a local Ollama model is loaded with. Four pictures need about
    # 5000 tokens; Ollama's own default (4096) is too small. More costs GPU memory.
    context_tokens: int = Field(default=8192, ge=2048, le=131072)

    @property
    def info(self) -> ProviderInfo:
        return PROVIDERS_BY_ID[self.provider]

    @property
    def enabled(self) -> bool:
        return self.provider != "none"

    @property
    def resolved_model(self) -> str:
        return self.model.strip() or self.info.default_model

    @property
    def resolved_base_url(self) -> str:
        return (self.base_url.strip() or self.info.base_url).rstrip("/")


# ---------------------------------------------------------------------------- keys
class KeyStore:
    """API keys per provider in ``<data>/anomaly/llm_keys.json`` (environment variables win)."""

    def __init__(self, data_dir: Path) -> None:
        self.path = Path(data_dir) / "anomaly" / "llm_keys.json"

    def _load(self) -> dict[str, str]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set(self, provider: str, key: str | None) -> None:
        keys = self._load()
        if key:
            keys[provider] = key.strip()
        else:
            keys.pop(provider, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(keys), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(self.path)

    def get(self, provider: str) -> tuple[str | None, str]:
        """The key and where it came from: env:<NAME>, file, or none."""
        info = PROVIDERS_BY_ID.get(provider)  # type: ignore[arg-type]
        for name in ["PATHSCOPE_LLM_API_KEY", *(info.key_env if info else [])]:
            value = os.environ.get(name)
            if value:
                return value, f"env:{name}"
        value = self._load().get(provider)
        return (value, "file") if value else (None, "none")

    def describe(self, provider: str) -> dict:
        key, source = self.get(provider)
        return {"set": bool(key), "source": source, "hint": f"…{key[-4:]}" if key and len(key) > 8 else ("set" if key else "")}


def load_settings(session) -> LLMSettings:
    from pathscope.db.models import Setting

    row = session.get(Setting, SETTING_KEY)
    try:
        return LLMSettings.model_validate(row.value if row is not None and isinstance(row.value, dict) else {})
    except Exception:  # noqa: BLE001 - a damaged setting means "no model", never a crash
        return LLMSettings()


def save_settings(session, settings: LLMSettings) -> None:
    from pathscope.db.models import Setting

    row = session.get(Setting, SETTING_KEY)
    if row is None:
        session.add(Setting(key=SETTING_KEY, value=settings.model_dump()))
    else:
        row.value = settings.model_dump()
    session.commit()
