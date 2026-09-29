"""Image quality measures shared by the face and plate pipelines.

Every measure is normalised to 0..1 (1 = good). They are deliberately simple
and explainable: researchers need to understand why a frame was rejected.
"""

from __future__ import annotations

import cv2
import numpy as np


def to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 2:
        return img
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


def blur_score(img: np.ndarray, reference_size: int = 112, sharp_at: float = 120.0) -> float:
    """Sharpness from the variance of the Laplacian on a size-normalised gray
    crop. ``sharp_at`` is the variance that counts as fully sharp; the score
    saturates there. Very small crops are resized up, which lowers their
    variance and therefore their score, as it should."""
    g = to_gray(img)
    if g.size == 0:
        return 0.0
    h, w = g.shape[:2]
    scale = reference_size / max(h, w)
    if abs(scale - 1.0) > 0.05:
        g = cv2.resize(g, (max(8, int(round(w * scale))), max(8, int(round(h * scale)))), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
    var = float(cv2.Laplacian(g, cv2.CV_64F).var())
    return float(min(1.0, var / sharp_at))


def exposure_score(img: np.ndarray) -> tuple[float, str | None]:
    """1 when the crop is neither dark nor blown out. Returns (score, reason)."""
    g = to_gray(img)
    if g.size == 0:
        return 0.0, "empty"
    mean = float(g.mean()) / 255.0
    clipped_dark = float((g < 8).mean())
    clipped_bright = float((g > 247).mean())
    if mean < 0.12 or clipped_dark > 0.5:
        return max(0.0, mean / 0.25), "too_dark"
    if mean > 0.9 or clipped_bright > 0.35:
        return max(0.0, (1.0 - mean) / 0.2), "too_bright"
    # Smooth peak around a mid-gray mean; penalise heavy clipping a little
    score = 1.0 - min(1.0, abs(mean - 0.48) / 0.4)
    score *= 1.0 - min(0.5, clipped_dark + clipped_bright)
    return float(max(0.0, min(1.0, score))), None


def mean_brightness(img: np.ndarray) -> float:
    """Mean gray level of the crop, 0..1."""
    g = to_gray(img)
    return float(g.mean()) / 255.0 if g.size else 0.0


def contrast_score(img: np.ndarray, full_at: float = 55.0) -> float:
    """Standard deviation of gray levels, saturating at ``full_at``."""
    g = to_gray(img)
    if g.size == 0:
        return 0.0
    return float(min(1.0, float(g.std()) / full_at))


def size_score(size_px: float, min_px: float, good_px: float) -> float:
    """0 below ``min_px``, 1 at ``good_px`` and above, linear in between."""
    if size_px < min_px:
        return 0.0
    if size_px >= good_px:
        return 1.0
    return float((size_px - min_px) / max(1e-6, good_px - min_px))


def edge_cut_fraction(box: tuple[float, float, float, float], width: int, height: int, tolerance: float = 1.0) -> float:
    """Rough fraction of the box that lies outside the frame (cut off)."""
    x1, y1, x2, y2 = box
    bw, bh = max(1e-6, x2 - x1), max(1e-6, y2 - y1)
    cut_w = max(0.0, -x1) + max(0.0, x2 - width)
    cut_h = max(0.0, -y1) + max(0.0, y2 - height)
    cut_w = 0.0 if cut_w <= tolerance else cut_w
    cut_h = 0.0 if cut_h <= tolerance else cut_h
    return float(min(1.0, cut_w / bw + cut_h / bh))


def crop_with_margin(frame: np.ndarray, box: tuple[float, float, float, float], margin: float = 0.1, min_size: int = 4) -> tuple[np.ndarray | None, tuple[int, int]]:
    """Crop a box enlarged by ``margin`` on each side. Returns (crop, (x0, y0))."""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    x1 -= bw * margin
    x2 += bw * margin
    y1 -= bh * margin
    y2 += bh * margin
    xa = int(max(0, np.floor(x1)))
    ya = int(max(0, np.floor(y1)))
    xb = int(min(w, np.ceil(x2)))
    yb = int(min(h, np.ceil(y2)))
    if xb - xa < min_size or yb - ya < min_size:
        return None, (xa, ya)
    return frame[ya:yb, xa:xb], (xa, ya)
