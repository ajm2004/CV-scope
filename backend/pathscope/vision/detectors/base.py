"""Detector interface.

A detector receives a BGR frame and returns detections with canonical class
names. It has no knowledge of scene geometry or research semantics.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np

from pathscope.vision.types import Detection


@dataclass
class DetectorConfig:
    model_id: str
    weights_path: str
    provider: str  # ultralytics | onnxruntime | torchvision
    device: str = "cpu"  # cpu | cuda | cuda:0 | mps
    image_size: int = 640
    confidence: float = 0.25
    iou: float = 0.5
    half: bool = False
    classes: list[str] = field(default_factory=list)  # canonical names to keep; empty = all
    extra: dict = field(default_factory=dict)


class Detector(ABC):
    provider: str = "base"

    def __init__(self, config: DetectorConfig) -> None:
        self.config = config
        self.loaded = False
        self.last_inference_ms: float = 0.0
        self.last_preprocess_ms: float = 0.0
        self.resolved_device: str = config.device

    @abstractmethod
    def load(self) -> None: ...

    @abstractmethod
    def _detect(self, frame_bgr: np.ndarray) -> list[Detection]: ...

    @property
    @abstractmethod
    def class_names(self) -> list[str]: ...

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        if not self.loaded:
            self.load()
        t0 = time.perf_counter()
        dets = self._detect(frame_bgr)
        self.last_inference_ms = (time.perf_counter() - t0) * 1000.0
        if self.config.classes:
            keep = set(self.config.classes)
            dets = [d for d in dets if d.class_name in keep]
        return dets

    def warmup(self, width: int = 640, height: int = 480, iterations: int = 2) -> None:
        if not self.loaded:
            self.load()
        blank = np.zeros((height, width, 3), dtype=np.uint8)
        for _ in range(iterations):
            self._detect(blank)

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass

    def describe(self) -> dict:
        return {
            "provider": self.provider,
            "model_id": self.config.model_id,
            "device": self.resolved_device,
            "image_size": self.config.image_size,
            "confidence": self.config.confidence,
            "iou": self.config.iou,
            "half": self.config.half,
        }


class DetectorLoadError(RuntimeError):
    pass
