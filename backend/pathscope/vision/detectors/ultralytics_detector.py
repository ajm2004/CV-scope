"""Ultralytics provider: YOLO11, YOLOv8 and RT-DETR checkpoints.

Optional dependency (AGPL-3.0). Imported lazily so the rest of the platform
works without it.
"""

from __future__ import annotations

import numpy as np

from pathscope.vision.classes import canonical_class, class_ids_for
from pathscope.vision.detectors.base import Detector, DetectorConfig, DetectorLoadError
from pathscope.vision.inference.runtime import resolve_device
from pathscope.vision.types import Detection


def _precision_kwargs(half: bool) -> dict:
    """Ultralytics 8.4 replaced ``half`` with ``quantize``; support both."""
    if not half:
        return {}
    try:
        from ultralytics.cfg import get_cfg

        if "quantize" in vars(get_cfg()):
            return {"quantize": 16}
    except Exception:  # noqa: BLE001
        pass
    return {"half": True}


class UltralyticsDetector(Detector):
    provider = "ultralytics"

    def __init__(self, config: DetectorConfig) -> None:
        super().__init__(config)
        self._model = None
        self._names: list[str] = []
        self._class_ids: list[int] | None = None

    def load(self) -> None:
        try:
            from ultralytics import RTDETR, YOLO
        except ImportError as exc:  # pragma: no cover - environment specific
            raise DetectorLoadError(
                "The 'ultralytics' package is not installed. Install it with: pip install ultralytics"
            ) from exc
        device, reason = resolve_device(self.config.device)
        self.resolved_device = device
        family = self.config.extra.get("family", "")
        path = self.config.weights_path
        try:
            if family == "rtdetr" or "rtdetr" in path.lower():
                self._model = RTDETR(path)
            else:
                self._model = YOLO(path)
        except Exception as exc:  # noqa: BLE001
            raise DetectorLoadError(f"Could not load weights '{path}': {exc}") from exc
        names = self._model.names
        if isinstance(names, dict):
            self._names = [names[k] for k in sorted(names)]
        else:
            self._names = list(names)
        if self.config.classes:
            ids = class_ids_for(self.config.classes, self._names)
            self._class_ids = ids or None
        # Half precision only makes sense on CUDA
        if not device.startswith("cuda"):
            self.config.half = False
        self._precision_kwargs = _precision_kwargs(self.config.half)
        self.loaded = True
        self.load_reason = reason

    @property
    def class_names(self) -> list[str]:
        return [canonical_class(n) for n in self._names]

    def _detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        assert self._model is not None
        try:
            results = self._model.predict(
                frame_bgr,
                imgsz=self.config.image_size,
                conf=self.config.confidence,
                iou=self.config.iou,
                device=self.resolved_device,
                classes=self._class_ids,
                verbose=False,
                **self._precision_kwargs,
            )
        except RuntimeError as exc:
            # Typical CUDA out-of-memory or device failure: fall back to CPU once.
            if self.resolved_device != "cpu" and ("CUDA" in str(exc) or "out of memory" in str(exc).lower()):
                self.resolved_device = "cpu"
                self.config.half = False
                self._precision_kwargs = {}
                results = self._model.predict(
                    frame_bgr, imgsz=self.config.image_size, conf=self.config.confidence,
                    iou=self.config.iou, device="cpu", classes=self._class_ids, verbose=False,
                )
            else:
                raise
        out: list[Detection] = []
        if not results:
            return out
        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return out
        xyxy = boxes.xyxy.cpu().numpy()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        for (x1, y1, x2, y2), c, k in zip(xyxy, conf, cls, strict=True):
            name = canonical_class(self._names[k]) if 0 <= k < len(self._names) else str(k)
            out.append(Detection(name, float(c), (float(x1), float(y1), float(x2), float(y2)), int(k)))
        return out

    def close(self) -> None:
        self._model = None
        self.loaded = False
