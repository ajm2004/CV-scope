"""Synthetic scenes for the anomaly tests: a textured room seen by a noisy camera."""

from __future__ import annotations

import cv2
import numpy as np

W, H = 640, 480


def room(seed: int = 3) -> np.ndarray:
    """A textured background: walls, a floor pattern and a few pieces of furniture."""
    rng = np.random.default_rng(seed)
    img = np.zeros((H, W, 3), np.float32)
    img[:] = (150, 160, 170)
    img[300:] = (95, 120, 140)  # floor
    tex = cv2.GaussianBlur(rng.normal(0, 22, (H, W)).astype(np.float32), (0, 0), 2.0)
    img += tex[..., None]
    for x in range(0, W, 40):  # floor boards
        cv2.line(img, (x, 300), (x - 60, H), (70, 90, 110), 2)
    cv2.rectangle(img, (60, 180), (200, 300), (60, 70, 120), -1)  # a cabinet
    cv2.rectangle(img, (420, 230), (600, 330), (170, 150, 200), -1)  # a bed
    cv2.rectangle(img, (430, 240), (590, 270), (220, 220, 225), -1)  # pillow
    return np.clip(img, 0, 255)


def box_object(size: tuple[int, int] = (70, 60), seed: int = 9) -> np.ndarray:
    """A textured object (a bag)."""
    rng = np.random.default_rng(seed)
    w, h = size
    obj = np.zeros((h, w, 3), np.float32)
    obj[:] = (40, 60, 180)
    obj += cv2.GaussianBlur(rng.normal(0, 25, (h, w)).astype(np.float32), (0, 0), 1.5)[..., None]
    cv2.rectangle(obj, (0, 0), (w - 1, h - 1), (20, 30, 90), 3)
    return np.clip(obj, 0, 255)


def place(img: np.ndarray, obj: np.ndarray, x: int, y: int) -> np.ndarray:
    out = img.copy()
    h, w = obj.shape[:2]
    out[y : y + h, x : x + w] = obj
    return out


class Camera:
    """Adds sensor noise and JPEG compression like a real webcam."""

    def __init__(self, seed: int = 1, noise: float = 3.0, quality: int = 70) -> None:
        self.rng = np.random.default_rng(seed)
        self.noise = noise
        self.quality = quality

    def shoot(self, scene: np.ndarray, gain: float = 1.0) -> np.ndarray:
        img = scene * gain + self.rng.normal(0, self.noise, scene.shape)
        img = np.clip(img, 0, 255).astype(np.uint8)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), self.quality])
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def run(assistant, frames, fps: float = 10.0, t0: float = 0.0, objects_at=None):
    """Feed (scene, gain) pairs; returns every update with its media time."""
    cam = Camera()
    out = []
    for i, (scene, gain) in enumerate(frames):
        t = t0 + i / fps
        objs = objects_at(t) if objects_at else None
        for u in assistant.observe(cam.shoot(scene, gain), t, wall_time=1_000_000.0 + t, objects=objs):
            out.append(u)
    return out
