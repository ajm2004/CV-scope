"""Plate stack factory: detector + OCR from the configured models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from pathscope.recognition.common.types import PlateDetection, PlateRead
from pathscope.recognition.face.stack import stub_allowed
from pathscope.recognition.plate.detector.base import PlateDetector
from pathscope.recognition.plate.ocr.base import PlateOcr, PlateOcrConfig


@dataclass
class PlateStack:
    detector: PlateDetector
    ocr: PlateOcr

    def describe(self) -> dict:
        return {"detector": self.detector.describe(), "ocr": self.ocr.describe()}

    @property
    def model_version(self) -> str:
        return f"{self.detector.model_version}+{self.ocr.model_version}"

    def close(self) -> None:
        self.detector.close()
        self.ocr.close()


class StubPlateDetector(PlateDetector):
    """Test stand-in: the lower-central band of any image is 'the plate'."""

    id = "stub"
    model_version = "stub"

    def detect(self, image_bgr: np.ndarray) -> list[PlateDetection]:
        h, w = image_bgr.shape[:2]
        if h < 20 or w < 20:
            return []
        return [PlateDetection((w * 0.3, h * 0.65, w * 0.7, h * 0.85), 0.9)]


class ScriptedPlateOcr(PlateOcr):
    """Test stand-in: returns scripted reads in order, then repeats the last."""

    id = "stub"
    model_version = "stub"

    def __init__(self, reads: list[PlateRead | None] | None = None) -> None:
        self.reads = list(reads or [])
        self.calls = 0
        self.config = PlateOcrConfig(max_plate_slots=10, alphabet="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_", image_color_mode="rgb")

    def read(self, crop_bgr: np.ndarray) -> PlateRead | None:
        self.calls += 1
        if not self.reads:
            return None
        r = self.reads[min(self.calls - 1, len(self.reads) - 1)]
        return PlateRead(list(r.chars), list(r.confidences), r.region, r.region_confidence) if r else None


def load_ocr_config(models: dict) -> PlateOcrConfig:
    cfg = models.get("ocr_config")
    if isinstance(cfg, dict):
        return PlateOcrConfig.from_dict(cfg)
    if cfg and Path(str(cfg)).exists():
        return PlateOcrConfig.from_yaml_text(Path(str(cfg)).read_text(encoding="utf-8"))
    meta = models.get("ocr_meta") or {}
    if meta.get("alphabet") and meta.get("max_plate_slots"):
        return PlateOcrConfig.from_dict(meta)
    raise FileNotFoundError("the plate OCR model has no configuration file (plate_config.yaml)")


def create_plate_stack(models: dict, device: str = "auto", cfg: dict | None = None, stack_id: str = "onnx") -> PlateStack:
    """``models``: {"detector": path, "ocr": path, "ocr_config": path|dict, ...}."""
    cfg = cfg or {}
    if stack_id == "stub":
        if not stub_allowed():
            raise RuntimeError("the stub plate stack is only available in tests (PATHSCOPE_RECOGNITION_ALLOW_STUB=1)")
        return PlateStack(StubPlateDetector(), ScriptedPlateOcr(models.get("scripted_reads")))
    from pathscope.recognition.plate.detector.onnx_yolo import OnnxPlateDetector
    from pathscope.recognition.plate.ocr.onnx_slots import OnnxSlotOcr

    detector = OnnxPlateDetector(models["detector"], device=device, score_threshold=float(cfg.get("min_detection_score", 0.3)), model_version=str(models.get("detector_version", "")))
    ocr = OnnxSlotOcr(models["ocr"], load_ocr_config(models), device=device, model_version=str(models.get("ocr_version", "")))
    return PlateStack(detector, ocr)
