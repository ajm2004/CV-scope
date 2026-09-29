"""SCRFD face detector (InsightFace) through ONNX Runtime.

Decodes the ``det_10g`` layout: for each stride (8, 16, 32) three outputs
(scores, box distances, keypoint distances) with two anchors per location.
The model weights come from the InsightFace ``buffalo_l`` pack, which is
available for non-commercial research use only (see the model catalog).
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.common.onnx import create_session
from pathscope.recognition.common.types import FaceDetection
from pathscope.recognition.face.detector.base import FaceDetector, order_landmarks


def _distance2bbox(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(points: np.ndarray, distance: np.ndarray) -> np.ndarray:
    preds = []
    for i in range(0, distance.shape[1], 2):
        preds.append(points[:, 0] + distance[:, i])
        preds.append(points[:, 1] + distance[:, i + 1])
    return np.stack(preds, axis=-1)


class ScrfdDetector(FaceDetector):
    id = "scrfd"

    def __init__(self, model_path: str | Path, device: str = "auto", score_threshold: float = 0.5, nms_threshold: float = 0.4, input_size: int = 640, model_version: str = "scrfd-10g-kps") -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"SCRFD model not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.input_size = int(input_size)
        self._session, self.resolved_device = create_session(model_path, device)
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = inp.shape
        if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
            self.input_size = int(shape[2])
        n_out = len(self._session.get_outputs())
        if n_out in (6, 9):
            self._fmc, self._strides, self._num_anchors = 3, [8, 16, 32], 2
        elif n_out in (10, 15):
            self._fmc, self._strides, self._num_anchors = 5, [8, 16, 32, 64, 128], 1
        else:
            raise RuntimeError(f"unexpected SCRFD output count {n_out}")
        self._use_kps = n_out in (9, 15)
        self._output_names = [o.name for o in self._session.get_outputs()]
        self._anchor_cache: dict[tuple[int, int, int], np.ndarray] = {}

    def _anchors(self, height: int, width: int, stride: int) -> np.ndarray:
        key = (height, width, stride)
        cached = self._anchor_cache.get(key)
        if cached is None:
            centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
            centers = (centers * stride).reshape(-1, 2)
            if self._num_anchors > 1:
                centers = np.stack([centers] * self._num_anchors, axis=1).reshape(-1, 2)
            cached = self._anchor_cache[key] = centers
        return cached

    def detect(self, image_bgr: np.ndarray) -> list[FaceDetection]:
        h, w = image_bgr.shape[:2]
        if h < 16 or w < 16:
            return []
        size = self.input_size
        scale = min(size / h, size / w)
        nh, nw = max(1, int(round(h * scale))), max(1, int(round(w * scale)))
        resized = cv2.resize(image_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((size, size, 3), dtype=np.uint8)
        canvas[:nh, :nw] = resized
        blob = cv2.dnn.blobFromImage(canvas, 1.0 / 128.0, (size, size), (127.5, 127.5, 127.5), swapRB=True)
        outs = self._session.run(self._output_names, {self._input_name: blob})
        scores_all, boxes_all, kps_all = [], [], []
        for idx, stride in enumerate(self._strides):
            scores = outs[idx].reshape(-1)
            bbox = outs[idx + self._fmc].reshape(-1, 4) * stride
            fh, fw = size // stride, size // stride
            anchors = self._anchors(fh, fw, stride)
            n = min(len(scores), len(anchors))
            scores, bbox, anchors = scores[:n], bbox[:n], anchors[:n]
            pos = np.where(scores >= self.score_threshold)[0]
            if len(pos) == 0:
                continue
            scores_all.append(scores[pos])
            boxes_all.append(_distance2bbox(anchors, bbox)[pos])
            if self._use_kps:
                kps = outs[idx + self._fmc * 2].reshape(-1, 10)[:n] * stride
                kps_all.append(_distance2kps(anchors, kps)[pos].reshape(-1, 5, 2))
        if not scores_all:
            return []
        scores = np.concatenate(scores_all)
        boxes = np.concatenate(boxes_all) / scale
        kps = np.concatenate(kps_all) / scale if kps_all else None
        rects = [[float(b[0]), float(b[1]), float(b[2] - b[0]), float(b[3] - b[1])] for b in boxes]
        keep = cv2.dnn.NMSBoxes(rects, scores.astype(float).tolist(), float(self.score_threshold), float(self.nms_threshold))
        if keep is None or len(keep) == 0:
            return []
        out: list[FaceDetection] = []
        for i in np.array(keep).reshape(-1):
            b = boxes[i]
            box = (max(0.0, float(b[0])), max(0.0, float(b[1])), min(float(w), float(b[2])), min(float(h), float(b[3])))
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                continue
            lm = order_landmarks(kps[i]) if kps is not None else None
            out.append(FaceDetection(box=box, score=float(scores[i]), landmarks=lm))
        out.sort(key=lambda d: d.width * d.height, reverse=True)
        return out

    def close(self) -> None:
        self._session = None
