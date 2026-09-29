"""ONNX Runtime provider for YOLO-style exported detectors.

Handles the common Ultralytics export layout: input (1,3,H,W) RGB 0..1 with
letterbox padding, output (1, 4+nc, N) or (1, N, 4+nc) with xywh boxes in
input pixels. NMS is done with OpenCV.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from pathscope.vision.classes import COCO_CLASSES, canonical_class
from pathscope.vision.detectors.base import Detector, DetectorConfig, DetectorLoadError
from pathscope.vision.types import Detection


def _letterbox(img: np.ndarray, size: int) -> tuple[np.ndarray, float, tuple[int, int]]:
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top : top + nh, left : left + nw] = resized
    return canvas, r, (left, top)


class OnnxRuntimeDetector(Detector):
    provider = "onnxruntime"

    def __init__(self, config: DetectorConfig) -> None:
        super().__init__(config)
        self._session = None
        self._input_name = ""
        self._names: list[str] = list(COCO_CLASSES)
        self._input_size = config.image_size
        self.execution_providers: list[str] = []

    def load(self) -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover
            raise DetectorLoadError(
                "The 'onnxruntime' package is not installed. Install onnxruntime or onnxruntime-gpu."
            ) from exc
        available = ort.get_available_providers()
        wanted: list = []
        dev = (self.config.device or "cpu").lower()
        if dev.startswith("cuda") or dev == "auto":
            if "TensorrtExecutionProvider" in available:
                wanted.append(("TensorrtExecutionProvider", {"trt_fp16_enable": True}))
            if "CUDAExecutionProvider" in available:
                wanted.append("CUDAExecutionProvider")
        if "CoreMLExecutionProvider" in available and dev in ("auto", "mps"):
            wanted.append("CoreMLExecutionProvider")
        wanted.append("CPUExecutionProvider")
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        try:
            self._session = ort.InferenceSession(self.config.weights_path, so, providers=wanted)
        except Exception as exc:  # noqa: BLE001
            raise DetectorLoadError(f"Could not load ONNX model '{self.config.weights_path}': {exc}") from exc
        self.execution_providers = list(self._session.get_providers())
        self.resolved_device = "cuda" if any("CUDA" in p or "Tensorrt" in p for p in self.execution_providers) else "cpu"
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = inp.shape
        if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
            self._input_size = int(shape[2])
        # Class names embedded by Ultralytics export
        meta = self._session.get_modelmeta().custom_metadata_map or {}
        names = meta.get("names")
        if names:
            try:
                import ast

                parsed = ast.literal_eval(names)
                if isinstance(parsed, dict):
                    self._names = [parsed[k] for k in sorted(parsed)]
                elif isinstance(parsed, list):
                    self._names = list(parsed)
            except Exception:  # noqa: BLE001
                pass
        self.loaded = True

    @property
    def class_names(self) -> list[str]:
        return [canonical_class(n) for n in self._names]

    def _detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        assert self._session is not None
        t0 = time.perf_counter()
        size = self._input_size
        img, ratio, (px, py) = _letterbox(frame_bgr, size)
        blob = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        blob = np.ascontiguousarray(blob[None])
        self.last_preprocess_ms = (time.perf_counter() - t0) * 1000.0
        out = self._session.run(None, {self._input_name: blob})[0]
        pred = np.squeeze(out, axis=0)
        if pred.ndim != 2:
            return []
        nc = len(self._names)
        if pred.shape[0] == 4 + nc and pred.shape[1] != 4 + nc:
            pred = pred.T  # (N, 4+nc)
        boxes_xywh = pred[:, :4]
        scores_all = pred[:, 4:]
        if scores_all.shape[1] == 0:
            return []
        cls_ids = scores_all.argmax(axis=1)
        scores = scores_all[np.arange(len(cls_ids)), cls_ids]
        keep = scores >= self.config.confidence
        if not keep.any():
            return []
        boxes_xywh, scores, cls_ids = boxes_xywh[keep], scores[keep], cls_ids[keep]
        # xywh (center) -> xyxy in letterbox pixels -> source pixels
        x1 = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2 - px) / ratio
        y1 = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2 - py) / ratio
        w = boxes_xywh[:, 2] / ratio
        h = boxes_xywh[:, 3] / ratio
        rects = np.stack([x1, y1, w, h], axis=1).astype(np.float32)
        idx = cv2.dnn.NMSBoxes(rects.tolist(), scores.astype(float).tolist(), float(self.config.confidence), float(self.config.iou))
        if idx is None or len(idx) == 0:
            return []
        idx = np.array(idx).reshape(-1)
        H, W = frame_bgr.shape[:2]
        dets: list[Detection] = []
        for i in idx:
            bx1 = float(max(0.0, rects[i, 0]))
            by1 = float(max(0.0, rects[i, 1]))
            bx2 = float(min(W, rects[i, 0] + rects[i, 2]))
            by2 = float(min(H, rects[i, 1] + rects[i, 3]))
            k = int(cls_ids[i])
            name = canonical_class(self._names[k]) if k < len(self._names) else str(k)
            dets.append(Detection(name, float(scores[i]), (bx1, by1, bx2, by2), k))
        return dets

    def close(self) -> None:
        self._session = None
        self.loaded = False
