"""Detector factory."""

from __future__ import annotations

from pathscope.vision.detectors.base import Detector, DetectorConfig, DetectorLoadError


def create_detector(config: DetectorConfig) -> Detector:
    provider = config.provider
    if provider == "ultralytics":
        from pathscope.vision.detectors.ultralytics_detector import UltralyticsDetector

        return UltralyticsDetector(config)
    if provider == "onnxruntime":
        from pathscope.vision.detectors.onnx_detector import OnnxRuntimeDetector

        return OnnxRuntimeDetector(config)
    if provider == "torchvision":
        from pathscope.vision.detectors.torchvision_detector import TorchvisionDetector

        return TorchvisionDetector(config)
    raise DetectorLoadError(f"unknown detector provider '{provider}'")


__all__ = ["Detector", "DetectorConfig", "DetectorLoadError", "create_detector"]
