"""Evidence pictures of an anomaly: before, event, after, crops and an outlined overlay.

Only these few pictures are kept per event (never a stream of frames). The
overlay shows the zone, the changed area and the boxes of detected objects
with their class, never a recognized name.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.anomaly.detector import AnomalyUpdate

MAX_WIDTH = 1280
JPEG_QUALITY = 85

ZONE_COLOR = (0, 215, 255)  # amber (BGR)
CHANGE_COLOR = (40, 40, 235)  # red
OBJECT_COLOR = (255, 190, 40)  # blue


def _fit(img: np.ndarray) -> np.ndarray:
    if img.shape[1] <= MAX_WIDTH:
        return img
    scale = MAX_WIDTH / img.shape[1]
    return cv2.resize(img, (MAX_WIDTH, round(img.shape[0] * scale)), interpolation=cv2.INTER_AREA)


def _crop(img: np.ndarray, bbox: list[float], pad: float = 0.25, min_px: int = 96) -> np.ndarray:
    h, w = img.shape[:2]
    x1, y1, x2, y2 = bbox[0] * w, bbox[1] * h, bbox[2] * w, bbox[3] * h
    bw, bh = max(x2 - x1, min_px), max(y2 - y1, min_px)
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    bw, bh = bw * (1 + 2 * pad), bh * (1 + 2 * pad)
    a, b = int(max(0, cx - bw / 2)), int(max(0, cy - bh / 2))
    c, d = int(min(w, cx + bw / 2)), int(min(h, cy + bh / 2))
    return img[b:d, a:c]


def overlay(frame: np.ndarray, upd: AnomalyUpdate, boxes: list[tuple[str, tuple[float, float, float, float]]] | None = None) -> np.ndarray:
    img = frame.copy()
    h, w = img.shape[:2]
    thick = max(2, round(w / 480))
    if upd.zone_polygon:
        pts = np.array([[round(x * w), round(y * h)] for x, y in upd.zone_polygon], np.int32)
        cv2.polylines(img, [pts], True, ZONE_COLOR, thick, cv2.LINE_AA)
    if upd.mask is not None and upd.mask.any():
        big = cv2.resize(upd.mask.astype(np.uint8) * 255, (w, h), interpolation=cv2.INTER_NEAREST)
        tint = img.copy()
        tint[big > 0] = (0.55 * tint[big > 0] + 0.45 * np.array(CHANGE_COLOR)).astype(np.uint8)
        img = tint
        contours, _ = cv2.findContours(big, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(img, contours, -1, CHANGE_COLOR, thick, cv2.LINE_AA)
    for label, (x1, y1, x2, y2) in boxes or []:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), OBJECT_COLOR, thick)
        cv2.putText(img, label, (int(x1) + 3, max(14, int(y1) - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * thick / 2 + 0.2, OBJECT_COLOR, thick, cv2.LINE_AA)
    return img


class EvidenceWriter:
    """Writes the pictures of one run's anomalies below ``root``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def write(self, upd: AnomalyUpdate, boxes: list[tuple[str, tuple[float, float, float, float]]] | None = None) -> dict[str, str]:
        """Pictures for this update; returns name -> path relative to ``root``."""
        folder = self.root / upd.uid
        folder.mkdir(parents=True, exist_ok=True)
        out: dict[str, str] = {}

        def save(name: str, img: np.ndarray | None) -> None:
            if img is None or img.size == 0:
                return
            ok, buf = cv2.imencode(".jpg", _fit(img), [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
            if ok:
                (folder / f"{name}.jpg").write_bytes(buf.tobytes())
                out[name] = f"{upd.uid}/{name}.jpg"

        frames = upd.frames
        if upd.phase == "confirmed":
            save("before", frames.get("before"))
            save("event", frames.get("event"))
            if frames.get("event") is not None:
                save("overlay", overlay(frames["event"], upd, boxes))
                save("crop_event", _crop(frames["event"], upd.bbox))
            if frames.get("before") is not None:
                save("crop_before", _crop(frames["before"], upd.bbox))
        else:
            after = frames.get("after")
            save("after", after)
            if after is not None and not upd.instant:
                save("crop_after", _crop(after, upd.bbox))
                save("overlay_after", overlay(after, upd, boxes))
        return out
