"""Face quality estimation: size, sharpness, exposure, contrast, pose and
occlusion, combined into one 0..1 score with the reasons a face is unusable.

Recognition is never attempted below a safe quality; enrollment demands more.
The pose estimate comes from the five landmarks and is approximate: yaw grows
positive when the subject turns towards the image's right side.
"""

from __future__ import annotations

import numpy as np

from pathscope.recognition.common.quality import (
    blur_score,
    contrast_score,
    crop_with_margin,
    edge_cut_fraction,
    exposure_score,
    mean_brightness,
    size_score,
)
from pathscope.recognition.common.types import FaceDetection, QualityReport


def pose_from_landmarks(lm: np.ndarray | None) -> tuple[float | None, float | None]:
    if lm is None:
        return None, None
    lm = np.asarray(lm, dtype=np.float32).reshape(5, 2)
    le, re, nose, lmouth, rmouth = lm
    eye_dist = float(np.linalg.norm(re - le))
    if eye_dist < 1e-3:
        return None, None
    d_left = float(np.linalg.norm(nose - le))
    d_right = float(np.linalg.norm(nose - re))
    yaw = (d_left - d_right) / eye_dist
    eye_mid = (le + re) / 2.0
    mouth_mid = (lmouth + rmouth) / 2.0
    axis = mouth_mid - eye_mid
    face_h = float(np.linalg.norm(axis))
    if face_h < 1e-3:
        return float(yaw), None
    r = float(np.dot(nose - eye_mid, axis / face_h)) / face_h  # 0 at the eyes, 1 at the mouth
    pitch = (r - 0.55) * 2.0
    return float(yaw), float(pitch)


class FaceQualityAssessor:
    id = "heuristic-v1"

    def __init__(
        self,
        min_face_px: float = 40.0,
        good_face_px: float = 110.0,
        min_quality: float = 0.45,
        max_yaw: float = 0.75,
        max_pitch: float = 0.55,
        sharp_at: float = 120.0,
    ) -> None:
        self.min_face_px = float(min_face_px)
        self.good_face_px = float(good_face_px)
        self.min_quality = float(min_quality)
        self.max_yaw = float(max_yaw)
        self.max_pitch = float(max_pitch)
        self.sharp_at = float(sharp_at)

    def assess(self, image_bgr: np.ndarray, det: FaceDetection, frame_w: int | None = None, frame_h: int | None = None) -> QualityReport:
        """``det.box`` is in ``image_bgr`` coordinates; ``frame_w/h`` (when the
        image is the full frame) let cut-off faces be detected."""
        h, w = image_bgr.shape[:2]
        fw, fh = (frame_w or w), (frame_h or h)
        crop, _ = crop_with_margin(image_bgr, det.box, margin=0.05)
        reasons: list[str] = []
        size_px = float(det.height)
        if crop is None:
            return QualityReport(0.0, False, size_px, 0.0, 0.0, 0.0, None, None, 1.0, ["too_small"])
        blur = blur_score(crop, 112, self.sharp_at)
        exposure, exp_reason = exposure_score(crop)
        contrast = contrast_score(crop)
        brightness = mean_brightness(crop)
        yaw, pitch = pose_from_landmarks(det.landmarks)
        occlusion = edge_cut_fraction(det.box, fw, fh)
        if det.score < 0.75:
            occlusion = max(occlusion, min(1.0, (0.75 - det.score) / 0.75))
        if size_px < self.min_face_px:
            reasons.append("too_small")
        if blur < 0.2:
            reasons.append("blurred")
        if exp_reason:
            reasons.append(exp_reason)
        if contrast < 0.15:
            reasons.append("low_contrast")
        if yaw is not None and abs(yaw) > self.max_yaw:
            reasons.append("turned_away")
        if pitch is not None and abs(pitch) > self.max_pitch:
            reasons.append("tilted")
        if occlusion > 0.25:
            reasons.append("obstructed")
        s_size = size_score(size_px, self.min_face_px, self.good_face_px)
        pose = 1.0
        if yaw is not None:
            pose *= max(0.0, 1.0 - 0.6 * (abs(yaw) / self.max_yaw) ** 2)
        if pitch is not None:
            pose *= max(0.0, 1.0 - 0.5 * (abs(pitch) / self.max_pitch) ** 2)
        score = np.sqrt(max(0.0, s_size)) * (0.45 * blur + 0.25 * exposure + 0.15 * contrast + 0.15 * pose) * (1.0 - occlusion)
        score = float(max(0.0, min(1.0, score)))
        usable = not reasons and score >= self.min_quality
        if not usable and not reasons:
            reasons.append("low_quality")
        return QualityReport(score, usable, size_px, blur, exposure, contrast, yaw, pitch, occlusion, reasons, brightness)

    def describe(self) -> dict:
        return {"id": self.id, "min_face_px": self.min_face_px, "min_quality": self.min_quality, "max_yaw": self.max_yaw}
