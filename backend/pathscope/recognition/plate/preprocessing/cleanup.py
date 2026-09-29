"""Plate crop cleanup and quality.

Only measurement-preserving operations: cropping with a margin and optional
contrast normalisation (CLAHE on the lightness channel). No super-resolution
or generative enhancement is applied before OCR, so no character can be
invented by preprocessing.
"""

from __future__ import annotations

import cv2
import numpy as np

from pathscope.recognition.common.quality import (
    blur_score,
    contrast_score,
    crop_with_margin,
    exposure_score,
    size_score,
)
from pathscope.recognition.common.types import PlateDetection, QualityReport


def plate_crop(image_bgr: np.ndarray, box: tuple[float, float, float, float], margin: float = 0.12) -> np.ndarray | None:
    crop, _ = crop_with_margin(image_bgr, box, margin=margin, min_size=6)
    return crop


def normalize_contrast(crop_bgr: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def prepare_for_ocr(crop_bgr: np.ndarray, contrast_normalize: bool = False) -> np.ndarray:
    return normalize_contrast(crop_bgr) if contrast_normalize else crop_bgr


def assess_plate_quality(crop_bgr: np.ndarray | None, det: PlateDetection, min_plate_px: float, good_plate_px: float | None = None) -> QualityReport:
    good = good_plate_px or max(min_plate_px * 3.0, 32.0)
    height = float(det.height)
    if crop_bgr is None or crop_bgr.size == 0:
        return QualityReport(0.0, False, height, 0.0, 0.0, 0.0, None, None, 0.0, ["too_small"])
    reasons: list[str] = []
    blur = blur_score(crop_bgr, reference_size=64, sharp_at=90.0)
    exposure, exp_reason = exposure_score(crop_bgr)
    contrast = contrast_score(crop_bgr, full_at=45.0)
    if height < min_plate_px:
        reasons.append("too_small")
    if blur < 0.15:
        reasons.append("blurred")
    if exp_reason:
        reasons.append(exp_reason)
    if contrast < 0.2:
        reasons.append("low_contrast")
    if det.score < 0.3:
        reasons.append("weak_detection")
    s_size = size_score(height, min_plate_px, good)
    score = float(max(0.0, min(1.0, np.sqrt(max(0.0, s_size)) * (0.4 * blur + 0.25 * exposure + 0.25 * contrast + 0.1 * min(1.0, det.score)))))
    usable = not reasons and score >= 0.3
    if not usable and not reasons:
        reasons.append("low_quality")
    return QualityReport(score, usable, height, blur, exposure, contrast, None, None, 0.0, reasons)
