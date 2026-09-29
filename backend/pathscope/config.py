"""Application settings.

All values can be provided through environment variables prefixed with
``PATHSCOPE_`` or through a ``.env`` file in the repository root. Relative
paths are resolved against the repository root so the backend behaves the same
whether it is started from the root or from ``backend/``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/pathscope/config.py -> backend -> repository root
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PATHSCOPE_",
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("./data"))
    database_url: str | None = None
    host: str = "127.0.0.1"
    port: int = 8420
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    device: str = "auto"
    models_dir: Path | None = None

    store_trajectories: bool = True
    keep_source_video: bool = True
    retention_days: int = 0

    log_level: str = "info"
    log_format: str = "console"

    # Worker tuning
    preview_fps: float = 12.0
    preview_max_width: int = 1280
    preview_jpeg_quality: int = 75
    worker_restart_limit: int = 3

    # Licensed recognition modules (see docs/recognition.md). Both are empty in
    # the open-source build: no trusted issuer means the modules stay locked.
    recognition_issuer_keys: str = ""  # comma-separated hex Ed25519 public keys of trusted licence issuers
    recognition_key_dir: Path | None = None  # where the template / media encryption keys live (default <data>/recognition/keys)

    # ------------------------------------------------------------------ paths
    def _resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def resolved_data_dir(self) -> Path:
        return self._resolve(self.data_dir)

    @property
    def resolved_models_dir(self) -> Path:
        return self._resolve(self.models_dir) if self.models_dir else self.resolved_data_dir / "models"

    @property
    def videos_dir(self) -> Path:
        return self.resolved_data_dir / "videos"

    @property
    def exports_dir(self) -> Path:
        return self.resolved_data_dir / "exports"

    @property
    def recordings_dir(self) -> Path:
        return self.resolved_data_dir / "recordings"

    @property
    def logs_dir(self) -> Path:
        return self.resolved_data_dir / "logs"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        db_path = self.resolved_data_dir / "pathscope.db"
        return f"sqlite:///{db_path.as_posix()}"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_directories(self) -> None:
        for d in (
            self.resolved_data_dir,
            self.resolved_models_dir,
            self.videos_dir,
            self.exports_dir,
            self.recordings_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    return settings
