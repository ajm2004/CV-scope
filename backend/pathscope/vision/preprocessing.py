"""Frame preprocessing applied before detection: rotation and crop.

The crop is expressed in normalized coordinates of the *rotated* frame so the
same camera configuration works at any capture resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class PreprocessConfig:
    rotation: int = 0  # 0 | 90 | 180 | 270 (clockwise)
    crop: dict | None = None  # {"x": 0..1, "y": 0..1, "w": 0..1, "h": 0..1}

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        if self.rotation in (90, 270):
            width, height = height, width
        if self.crop:
            cw = max(1, int(round(width * float(self.crop.get("w", 1.0)))))
            ch = max(1, int(round(height * float(self.crop.get("h", 1.0)))))
            return cw, ch
        return width, height


def apply_preprocess(frame: np.ndarray, cfg: PreprocessConfig) -> np.ndarray:
    if cfg.rotation == 90:
        frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    elif cfg.rotation == 180:
        frame = cv2.rotate(frame, cv2.ROTATE_180)
    elif cfg.rotation == 270:
        frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if cfg.crop:
        h, w = frame.shape[:2]
        x = int(round(w * float(cfg.crop.get("x", 0.0))))
        y = int(round(h * float(cfg.crop.get("y", 0.0))))
        cw = int(round(w * float(cfg.crop.get("w", 1.0))))
        ch = int(round(h * float(cfg.crop.get("h", 1.0))))
        x, y = max(0, min(x, w - 1)), max(0, min(y, h - 1))
        cw, ch = max(1, min(cw, w - x)), max(1, min(ch, h - y))
        frame = frame[y : y + ch, x : x + cw]
    return frame


def resize_for_preview(frame: np.ndarray, max_width: int) -> np.ndarray:
    h, w = frame.shape[:2]
    if w <= max_width:
        return frame
    scale = max_width / w
    return cv2.resize(frame, (max_width, int(round(h * scale))), interpolation=cv2.INTER_AREA)


def encode_jpeg(frame: np.ndarray, quality: int = 75) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buf.tobytes()
