"""Persisted user settings (key/value in the database) layered over defaults."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.config import get_settings
from pathscope.db.models import Setting

# key -> (default, section, label, help, kind, advanced)
SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    "setup_completed": {"default": False, "section": "system", "label": "Setup wizard completed", "kind": "bool", "advanced": True},
    "default_preset": {"default": "auto", "section": "performance", "label": "Default inference preset", "kind": "enum", "options": ["auto", "fast", "balanced", "accurate", "custom"], "help": "Used by new experiments."},
    "default_model_id": {"default": "", "section": "models", "label": "Default detector", "kind": "string", "help": "Empty = follow the hardware recommendation."},
    "default_device": {"default": "auto", "section": "hardware", "label": "Inference device", "kind": "enum", "options": ["auto", "cuda", "mps", "cpu"], "help": "AUTO picks the fastest available device."},
    "preview_fps": {"default": 12.0, "section": "performance", "label": "Live preview frame rate", "kind": "float", "help": "Preview only; does not affect processing."},
    "preview_max_width": {"default": 1280, "section": "performance", "label": "Live preview width (px)", "kind": "int", "advanced": True},
    "store_trajectories": {"default": None, "section": "storage", "label": "Store sampled trajectories", "kind": "bool", "help": "Required for trajectory review and heatmaps. Trajectories are anonymous ground-plane samples."},
    "keep_source_video": {"default": None, "section": "video", "label": "Keep uploaded source videos", "kind": "bool", "help": "Recorded in the privacy list. Not enforced yet: uploaded videos stay until you delete them."},
    "retention_days": {"default": None, "section": "storage", "label": "Event retention (days)", "kind": "int", "help": "Recorded in the privacy list. Not enforced yet: events stay until you delete their runs."},
    "video_retention_days": {"default": 0, "section": "video", "label": "Video retention (days)", "kind": "int", "help": "Video recorded from live cameras is deleted this many days after it was recorded (checked every hour). 0 keeps it until you delete it. Uploaded videos are not affected."},
    "anomaly_retention_days": {"default": 0, "section": "storage", "label": "Anomaly evidence retention (days)", "kind": "int", "help": "Anomaly events and their before/after pictures are deleted this many days after they happened (checked every hour). 0 keeps them until you delete them or their run."},
    "export_format": {"default": "csv", "section": "export", "label": "Default export format", "kind": "enum", "options": ["csv", "json", "parquet"]},
    "export_include_context": {"default": True, "section": "export", "label": "Include context column in exports", "kind": "bool", "advanced": True},
    "log_level": {"default": None, "section": "logging", "label": "Log level", "kind": "enum", "options": ["debug", "info", "warning", "error"], "help": "Applies to newly started workers."},
    "webhooks_enabled": {"default": True, "section": "export", "label": "Allow webhook actions", "kind": "bool", "advanced": True, "help": "Off stops every rule from sending webhooks. Applies to runs started after the change."},
    "usb_probe_count": {"default": 6, "section": "cameras", "label": "USB camera indices to probe", "kind": "int", "advanced": True},
    "rtsp_transport": {"default": "tcp", "section": "cameras", "label": "RTSP transport", "kind": "enum", "options": ["tcp", "udp"], "advanced": True},
}


def env_defaults() -> dict[str, Any]:
    s = get_settings()
    return {
        "store_trajectories": s.store_trajectories,
        "keep_source_video": s.keep_source_video,
        "retention_days": s.retention_days,
        "log_level": s.log_level,
        "preview_fps": s.preview_fps,
        "preview_max_width": s.preview_max_width,
    }


def all_settings(session: Session) -> dict[str, Any]:
    values: dict[str, Any] = {}
    env = env_defaults()
    for key, d in SETTING_DEFINITIONS.items():
        default = d["default"]
        if default is None:
            default = env.get(key)
        values[key] = default
    for row in session.scalars(select(Setting)):
        if row.key in SETTING_DEFINITIONS:
            values[row.key] = row.value
    return values


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is not None:
        return row.value
    d = SETTING_DEFINITIONS.get(key)
    if d is None:
        return default
    if d["default"] is None:
        return env_defaults().get(key, default)
    return d["default"]


def set_settings(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    for key, value in values.items():
        if key not in SETTING_DEFINITIONS:
            continue
        d = SETTING_DEFINITIONS[key]
        kind = d["kind"]
        if kind == "bool":
            value = bool(value)
        elif kind == "int":
            value = int(value)
        elif kind == "float":
            value = float(value)
        elif kind == "enum" and value not in d.get("options", []):
            raise ValueError(f"'{value}' is not a valid option for {key}")
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
        else:
            row.value = value
    session.commit()
    return all_settings(session)


def definitions() -> list[dict[str, Any]]:
    out = []
    for key, d in SETTING_DEFINITIONS.items():
        out.append({"key": key, **{k: v for k, v in d.items() if k != "default"}, "advanced": d.get("advanced", False)})
    return out
