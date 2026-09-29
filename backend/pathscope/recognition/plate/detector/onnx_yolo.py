"""YOLO-style plate detector through ONNX Runtime.

Understands two export layouts:

* end-to-end exports (NMS inside the graph, as published by the
  open-image-models project): rows of ``[batch, x1, y1, x2, y2, class, score]``;
* raw Ultralytics-style exports ``(1, 4+nc, N)`` / ``(1, N, 4+nc)`` with
  centre-format boxes, for which NMS is applied here.

Any custom ONNX plate detector with one of these layouts can be dropped in.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.common.onnx import create_session
from pathscope.recognition.common.types import PlateDetection
from pathscope.recognition.plate.detector.base import PlateDetector


def letterbox(img: np.ndarray, size: int, color: int = 114) -> tuple[np.ndarray, float, tuple[int, int]]:
    h, w = img.shape[:2]
    r = min(size / h, size / w)
    nh, nw = max(1, int(round(h * r))), max(1, int(round(w * r)))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    dw, dh = int(round((size - nw) / 2 - 0.1)), int(round((size - nh) / 2 - 0.1))
    canvas[dh : dh + nh, dw : dw + nw] = resized
    return canvas, r, (dw, dh)


class OnnxPlateDetector(PlateDetector):
    id = "yolo-onnx"

    def __init__(self, model_path: str | Path, device: str = "auto", score_threshold: float = 0.3, nms_threshold: float = 0.45, input_size: int | None = None, model_version: str = "") -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"plate detector not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version or Path(model_path).stem
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self._session, self.resolved_device = create_session(model_path, device)
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = inp.shape
        self.input_size = int(input_size or 384)
        if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
            self.input_size = int(shape[2])
        self._output_names = [o.name for o in self._session.get_outputs()]

    def detect(self, image_bgr: np.ndarray) -> list[PlateDetection]:
        h, w = image_bgr.shape[:2]
        if h < 8 or w < 8:
            return []
        canvas, r, (dw, dh) = letterbox(image_bgr, self.input_size)
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        out = self._session.run(self._output_names, {self._input_name: blob})[0]
        pred = np.asarray(out)
        boxes: list[tuple[float, float, float, float]] = []
        scores: list[float] = []
        if pred.ndim == 3 and pred.shape[-1] == 7:
            pred = pred[0]
        if pred.ndim == 2 and pred.shape[1] == 7:
            for row in pred:
                score = float(row[6])
                if score < self.score_threshold:
                    continue
                boxes.append((float(row[1]), float(row[2]), float(row[3]), float(row[4])))
                scores.append(score)
        else:
            p = np.squeeze(pred, axis=0) if pred.ndim == 3 else pred
            if p.ndim != 2:
                return []
            if p.shape[0] < p.shape[1] and p.shape[0] <= 16:
                p = p.T  # (N, 4+nc)
            xywh, cls_scores = p[:, :4], p[:, 4:]
            if cls_scores.shape[1] == 0:
                return []
            conf = cls_scores.max(axis=1)
            keep = conf >= self.score_threshold
            if not keep.any():
                return []
            xywh, conf = xywh[keep], conf[keep]
            rects = [[float(x - bw / 2), float(y - bh / 2), float(bw), float(bh)] for x, y, bw, bh in xywh]
            idx = cv2.dnn.NMSBoxes(rects, conf.astype(float).tolist(), self.score_threshold, self.nms_threshold)
            for i in (np.array(idx).reshape(-1) if idx is not None and len(idx) else []):
                x, y, bw, bh = rects[i]
                boxes.append((x, y, x + bw, y + bh))
                scores.append(float(conf[i]))
        out_dets: list[PlateDetection] = []
        for (x1, y1, x2, y2), score in zip(boxes, scores, strict=False):
            bx1 = max(0.0, (x1 - dw) / r)
            by1 = max(0.0, (y1 - dh) / r)
            bx2 = min(float(w), (x2 - dw) / r)
            by2 = min(float(h), (y2 - dh) / r)
            if bx2 - bx1 < 4 or by2 - by1 < 3:
                continue
            out_dets.append(PlateDetection((bx1, by1, bx2, by2), score))
        out_dets.sort(key=lambda d: d.score, reverse=True)
        return out_dets

    def close(self) -> None:
        self._session = None
