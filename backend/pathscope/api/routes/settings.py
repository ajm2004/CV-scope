"""User settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, settings_dep
from pathscope.api.schemas import SettingsIn
from pathscope.config import Settings
from pathscope.settings_store import all_settings, definitions, set_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def get_all(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    return {
        "values": all_settings(session),
        "definitions": definitions(),
        "environment": {
            "data_dir": str(settings.resolved_data_dir),
            "models_dir": str(settings.resolved_models_dir),
            "database_url": settings.resolved_database_url.split("@")[-1] if "@" in settings.resolved_database_url else settings.resolved_database_url,
            "host": settings.host,
            "port": settings.port,
            "device": settings.device,
            "log_format": settings.log_format,
        },
    }


@router.put("")
def update(body: SettingsIn, session: Session = Depends(db_session)) -> dict:
    try:
        values = set_settings(session, body.values)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"values": values}
