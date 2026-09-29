"""Plate format registry: built-in formats plus custom ones from
``<data>/recognition/plate_formats.json`` (a list of objects with ``id``,
``name``, ``country``, ``pattern``, optional ``region`` and ``description``).
Custom formats with the id of a built-in one override it."""

from __future__ import annotations

import json
from pathlib import Path

from pathscope.recognition.plate.parser.base import PlateFormat
from pathscope.recognition.plate.parser.formats import BUILTIN_FORMATS

CUSTOM_FILE = "plate_formats.json"


def custom_formats_path(data_dir: Path | str) -> Path:
    return Path(data_dir) / "recognition" / CUSTOM_FILE


def load_custom_formats(data_dir: Path | str) -> tuple[list[PlateFormat], str | None]:
    """(formats, error). A broken file never disables the built-in formats."""
    p = custom_formats_path(data_dir)
    if not p.exists():
        return [], None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise ValueError("expected a JSON list")
        return [PlateFormat.from_dict(d) for d in raw], None
    except Exception as exc:  # noqa: BLE001
        return [], f"{p.name}: {exc}"


def available_formats(data_dir: Path | str | None) -> list[PlateFormat]:
    by_id = {f.id: f for f in BUILTIN_FORMATS}
    if data_dir is not None:
        custom, _ = load_custom_formats(data_dir)
        for f in custom:
            by_id[f.id] = f
    return list(by_id.values())


def load_formats(data_dir: Path | str | None, enabled: list[str] | str | None) -> list[PlateFormat]:
    """The enabled formats, in the configured order; ``generic`` when nothing is enabled."""
    ids = enabled if isinstance(enabled, list) else [s.strip() for s in (enabled or "").split(",")]
    ids = [i for i in ids if i]
    by_id = {f.id: f for f in available_formats(data_dir)}
    out = [by_id[i] for i in ids if i in by_id]
    if not out:
        out = [by_id["generic"]]
    return out
