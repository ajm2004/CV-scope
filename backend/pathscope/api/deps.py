"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import HTTPException
from sqlalchemy.orm import Session

from pathscope.config import Settings, get_settings
from pathscope.db.session import get_session_factory


def db_session() -> Generator[Session, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def settings_dep() -> Settings:
    return get_settings()


def get_or_404(session: Session, model, ident: int, label: str | None = None):
    obj = session.get(model, ident)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{label or model.__name__} {ident} not found")
    return obj
