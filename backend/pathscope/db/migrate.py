"""Run Alembic migrations programmatically at startup."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command
from pathscope.config import get_settings
from pathscope.logging_setup import get_logger

log = get_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url or get_settings().resolved_database_url)
    return cfg


def upgrade_database(url: str | None = None) -> None:
    cfg = alembic_config(url)
    command.upgrade(cfg, "head")
    log.info("database migrated to head")
