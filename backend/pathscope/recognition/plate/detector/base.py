"""Plate detector interface: a vehicle crop (or frame) in, plate boxes out."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from pathscope.recognition.common.types import PlateDetection


class PlateDetector(ABC):
    id: str = "base"
    model_version: str = ""
    resolved_device: str = "cpu"

    @abstractmethod
    def detect(self, image_bgr: np.ndarray) -> list[PlateDetection]:
        """Plates in the image, boxes in image pixels, best score first."""

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass

    def describe(self) -> dict:
        return {"id": self.id, "model_version": self.model_version, "device": self.resolved_device}
