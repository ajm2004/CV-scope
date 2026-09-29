"""OCR interface and the plate model configuration (fast-plate-ocr layout)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from pathscope.recognition.common.types import PlateRead


def _parse_scalar(raw: str) -> Any:
    v = raw.strip()
    if not v:
        return ""
    if (v[0] == v[-1]) and v[0] in ("'", '"'):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none", "~"):
        return None
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if re.fullmatch(r"-?\d+\.\d*", v):
        return float(v)
    return v


def _parse_list(body: str) -> list:
    items: list = []
    for part in re.findall(r"'[^']*'|\"[^\"]*\"|[^,\s][^,]*", body):
        part = part.strip()
        if part:
            items.append(_parse_scalar(part))
    return items


def parse_simple_yaml(text: str) -> dict[str, Any]:
    """Enough YAML for plate config files: ``key: scalar`` lines, comments,
    inline lists (possibly spanning several lines) and simple tuples."""
    out: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # drop trailing comments outside quotes
        quote = None
        cut = len(line)
        for j, ch in enumerate(line):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == "#":
                cut = j
                break
        line = line[:cut].rstrip()
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") or value.startswith("("):
            closer = "]" if value.startswith("[") else ")"
            while closer not in value and i < len(lines):
                value += " " + lines[i].split("#", 1)[0].strip()
                i += 1
            body = value[1 : value.rfind(closer)] if closer in value else value[1:]
            out[key] = _parse_list(body)
        else:
            out[key] = _parse_scalar(value)
    return out


@dataclass
class PlateOcrConfig:
    max_plate_slots: int
    alphabet: str
    pad_char: str = "_"
    img_height: int = 64
    img_width: int = 128
    keep_aspect_ratio: bool = False
    interpolation: str = "linear"
    image_color_mode: str = "grayscale"
    padding_color: tuple[int, int, int] = (114, 114, 114)
    plate_regions: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> PlateOcrConfig:
        pad = d.get("padding_color", (114, 114, 114))
        if isinstance(pad, int):
            pad = (pad, pad, pad)
        elif isinstance(pad, list | tuple):
            pad = tuple(int(v) for v in pad) if len(pad) == 3 else (int(pad[0]),) * 3
        regions = d.get("plate_regions") or []
        return cls(
            max_plate_slots=int(d["max_plate_slots"]),
            alphabet=str(d["alphabet"]),
            pad_char=str(d.get("pad_char", "_")),
            img_height=int(d.get("img_height", 64)),
            img_width=int(d.get("img_width", 128)),
            keep_aspect_ratio=bool(d.get("keep_aspect_ratio", False)),
            interpolation=str(d.get("interpolation", "linear")),
            image_color_mode=str(d.get("image_color_mode", "grayscale")),
            padding_color=tuple(pad),
            plate_regions=[str(r) for r in regions],
        )

    @classmethod
    def from_yaml_text(cls, text: str) -> PlateOcrConfig:
        return cls.from_dict(parse_simple_yaml(text))

    def to_dict(self) -> dict:
        return {
            "max_plate_slots": self.max_plate_slots,
            "alphabet": self.alphabet,
            "pad_char": self.pad_char,
            "img_height": self.img_height,
            "img_width": self.img_width,
            "keep_aspect_ratio": self.keep_aspect_ratio,
            "interpolation": self.interpolation,
            "image_color_mode": self.image_color_mode,
            "padding_color": list(self.padding_color),
            "plate_regions": list(self.plate_regions),
        }


class PlateOcr(ABC):
    id: str = "base"
    model_version: str = ""
    resolved_device: str = "cpu"
    config: PlateOcrConfig | None = None

    @abstractmethod
    def read(self, crop_bgr: np.ndarray) -> PlateRead | None:
        """Characters with per-character confidence for one plate crop."""

    def read_batch(self, crops: list[np.ndarray]) -> list[PlateRead | None]:
        return [self.read(c) for c in crops]

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass

    def describe(self) -> dict:
        return {"id": self.id, "model_version": self.model_version, "device": self.resolved_device, "config": self.config.to_dict() if self.config else None}
