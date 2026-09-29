"""YuNet face detector (OpenCV Zoo, MIT) through ``cv2.FaceDetectorYN``.

Detects faces from about 10x10 px up and returns five landmarks. Runs on the
CPU through OpenCV's DNN module with no extra dependency.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.common.types import FaceDetection
from pathscope.recognition.face.detector.base import FaceDetector, order_landmarks


class YuNetDetector(FaceDetector):
    id = "yunet"

    def __init__(self, model_path: str | Path, score_threshold: float = 0.6, nms_threshold: float = 0.3, top_k: int = 200, model_version: str = "yunet-2023mar") -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"YuNet model not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version
        self.score_threshold = score_threshold
        self._size = (320, 320)
        self._det = cv2.FaceDetectorYN.create(self.model_path, "", self._size, float(score_threshold), float(nms_threshold), int(top_k))
        self.resolved_device = "cpu"

    def detect(self, image_bgr: np.ndarray) -> list[FaceDetection]:
        h, w = image_bgr.shape[:2]
        if h < 16 or w < 16:
            return []
        # The network works on sizes that are multiples of 32; pad rather than resize
        pw, ph = ((w + 31) // 32) * 32, ((h + 31) // 32) * 32
        if (pw, ph) != (w, h):
            padded = np.zeros((ph, pw, 3), dtype=np.uint8)
            padded[:h, :w] = image_bgr
        else:
            padded = image_bgr
        if (pw, ph) != self._size:
            self._det.setInputSize((pw, ph))
            self._size = (pw, ph)
        _, faces = self._det.detect(padded)
        out: list[FaceDetection] = []
        if faces is None:
            return out
        for f in faces:
            x, y, bw, bh = (float(v) for v in f[:4])
            score = float(f[14])
            if score < self.score_threshold:
                continue
            box = (max(0.0, x), max(0.0, y), min(float(w), x + bw), min(float(h), y + bh))
            if box[2] - box[0] < 4 or box[3] - box[1] < 4:
                continue
            out.append(FaceDetection(box=box, score=score, landmarks=order_landmarks(np.array(f[4:14], dtype=np.float32).reshape(5, 2))))
        out.sort(key=lambda d: d.width * d.height, reverse=True)
        return out
