"""Five-point face alignment to the 112x112 ArcFace template.

The similarity transform (rotation, uniform scale, translation) that maps the
detected landmarks onto the template is estimated with Umeyama's least-squares
method; the face is then warped. Both SFace and ArcFace models expect this
crop. Alignment only rotates and scales real pixels: nothing is generated.
"""

from __future__ import annotations

import cv2
import numpy as np

ARCFACE_TEMPLATE = np.array(
    [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]],
    dtype=np.float32,
)


def similarity_transform(src: np.ndarray, dst: np.ndarray) -> np.ndarray:
    """2x3 similarity matrix mapping ``src`` points onto ``dst`` (Umeyama)."""
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n = src.shape[0]
    mu_s = src.mean(axis=0)
    mu_d = dst.mean(axis=0)
    s = src - mu_s
    d = dst - mu_d
    cov = d.T @ s / n
    u, sv, vt = np.linalg.svd(cov)
    sign = np.ones(2)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[-1] = -1.0
    rot = u @ np.diag(sign) @ vt
    var_s = (s**2).sum() / n
    scale = (sv * sign).sum() / var_s if var_s > 1e-12 else 1.0
    t = mu_d - scale * rot @ mu_s
    return np.hstack([scale * rot, t[:, None]]).astype(np.float32)


class FivePointAligner:
    id = "five-point-similarity"

    def __init__(self, size: int = 112) -> None:
        self.size = int(size)
        self.template = ARCFACE_TEMPLATE * (self.size / 112.0)

    def align(self, image_bgr: np.ndarray, landmarks: np.ndarray) -> np.ndarray:
        lm = np.asarray(landmarks, dtype=np.float32).reshape(5, 2)
        m = similarity_transform(lm, self.template)
        return cv2.warpAffine(image_bgr, m, (self.size, self.size), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))

    def describe(self) -> dict:
        return {"id": self.id, "size": self.size}
