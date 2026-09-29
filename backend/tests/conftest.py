"""Test configuration: isolated data directory and SQLite database per session."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="pathscope-test-"))
os.environ["PATHSCOPE_DATA_DIR"] = str(_TMP)
os.environ["PATHSCOPE_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["PATHSCOPE_LOG_LEVEL"] = "warning"
os.environ["PATHSCOPE_CROSSCAM_BACKGROUND"] = "0"  # cross-camera correlation runs when a test flushes it


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _TMP


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from pathscope.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def sample_video() -> Path | None:
    root = Path(__file__).resolve().parents[2]
    p = root / "samples" / "videos" / "people-detection.mp4"
    return p if p.exists() else None
