"""Local model setup (Ollama): status, downloads with progress, guards. No network, no real Ollama."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

import httpx
import pytest

from pathscope.anomaly.llm import local
from pathscope.anomaly.llm.local import LocalModels, ollama_root


def test_ollama_root_follows_the_openai_base_url():
    assert ollama_root("") == "http://127.0.0.1:11434"
    assert ollama_root("http://gpu-box:11434/v1/") == "http://gpu-box:11434"


def test_status_without_a_running_server(monkeypatch):
    monkeypatch.setattr(local, "find_ollama", lambda: None)
    st = LocalModels().status("http://127.0.0.1:9")  # nothing listens there
    assert st["installed"] is False and st["running"] is False and st["models"] == []


class _Stream:
    def __init__(self, lines, status_code=200):
        self.lines, self.status_code = lines, status_code

    def iter_lines(self):
        yield from self.lines

    def read(self):
        return b"boom"


def test_pull_reports_progress_over_all_layers(monkeypatch):
    lines = [json.dumps(x) for x in (
        {"status": "pulling manifest"},
        {"status": "pulling abc", "digest": "sha256:a", "total": 3_000, "completed": 1_000},
        {"status": "pulling def", "digest": "sha256:b", "total": 1_000, "completed": 1_000},
        {"status": "pulling abc", "digest": "sha256:a", "total": 3_000, "completed": 3_000},
        {"status": "verifying sha256 digest"},
        {"status": "success"},
    )]
    seen = {}

    @contextmanager
    def fake_stream(method, url, json=None, timeout=None):
        seen["url"], seen["body"] = url, json
        yield _Stream(lines)

    monkeypatch.setattr(local.httpx, "stream", fake_stream)
    lm = LocalModels()
    job = lm.pull("http://127.0.0.1:11434", "qwen2.5vl:3b")
    deadline = time.time() + 5
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "done" and job.completed == 4_000 and job.total == 4_000 and job.progress == 1.0
    assert seen["url"].endswith("/api/pull") and seen["body"] == {"model": "qwen2.5vl:3b", "stream": True}
    assert lm.jobs()[0]["target"] == "qwen2.5vl:3b"


def test_pull_errors_and_bad_names(monkeypatch):
    @contextmanager
    def failing(method, url, json=None, timeout=None):
        yield _Stream([json_line({"error": "pull model manifest: file does not exist"})])

    def json_line(x):
        return json.dumps(x)

    monkeypatch.setattr(local.httpx, "stream", failing)
    job = LocalModels().pull("http://127.0.0.1:11434", "no-such-model:1b")
    deadline = time.time() + 5
    while job.status == "running" and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "failed" and "does not exist" in job.error
    with pytest.raises(ValueError):
        LocalModels().pull("http://127.0.0.1:11434", "rm -rf /; x")


def test_local_api(client, monkeypatch):
    monkeypatch.setattr(local, "find_ollama", lambda: None)
    client.put("/api/anomaly/assistant", json={"provider": "local", "base_url": "http://127.0.0.1:9/v1"})
    st = client.get("/api/anomaly/local").json()
    assert st["ollama"]["url"] == "http://127.0.0.1:9" and st["ollama"]["running"] is False
    assert st["catalog"][0]["download_gb"] > 0
    assert client.post("/api/anomaly/local/pull", json={"model": "bad name!"}).status_code == 422
    used = client.post("/api/anomaly/local/use", json={"model": "qwen2.5vl:3b"}).json()
    assert used["settings"]["provider"] == "local" and used["settings"]["model"] == "qwen2.5vl:3b" and used["settings"]["base_url"] == "http://127.0.0.1:9/v1"
    client.put("/api/anomaly/assistant", json={"provider": "none"})


def test_setup_actions_only_from_this_computer(client, monkeypatch):
    from starlette.testclient import TestClient

    from pathscope.main import app

    remote = TestClient(app, client=("192.168.1.50", 5000))
    r = remote.post("/api/anomaly/local/pull", json={"model": "qwen2.5vl:3b"})
    assert r.status_code == 403 and "CV-Scope computer" in r.json()["detail"]
    assert remote.post("/api/anomaly/local/install").status_code == 403
    _ = httpx  # imported for the monkeypatched module
