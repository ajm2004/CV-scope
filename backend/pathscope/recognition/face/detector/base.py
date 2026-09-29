"""Face detector interface: BGR image in, face boxes with 5 landmarks out."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from pathscope.recognition.common.types import FaceDetection


def order_landmarks(lm: np.ndarray) -> np.ndarray:
    """Canonical order: image-left eye, image-right eye, nose, image-left mouth
    corner, image-right mouth corner (the order the alignment template uses)."""
    lm = np.asarray(lm, dtype=np.float32).reshape(5, 2).copy()
    if lm[0, 0] > lm[1, 0]:
        lm[[0, 1]] = lm[[1, 0]]
    if lm[3, 0] > lm[4, 0]:
        lm[[3, 4]] = lm[[4, 3]]
    return lm


class FaceDetector(ABC):
    id: str = "base"
    model_version: str = ""
    resolved_device: str = "cpu"

    @abstractmethod
    def detect(self, image_bgr: np.ndarray) -> list[FaceDetection]:
        """Faces in the image, boxes in image pixels, landmarks in canonical order."""

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass

    def describe(self) -> dict:
        return {"id": self.id, "model_version": self.model_version, "device": self.resolved_device}
