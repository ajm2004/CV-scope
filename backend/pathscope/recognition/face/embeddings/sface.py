"""SFace embeddings (OpenCV Zoo, Apache-2.0) through ``cv2.FaceRecognizerSF``.

128-dimensional embeddings from a 112x112 aligned crop. OpenCV documents a
cosine-similarity verification threshold of 0.363; CV-Scope reports
Recognized only above a stricter default and Possible match in between.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.face.embeddings.base import FaceEmbedder, l2_normalize


class SFaceEmbedder(FaceEmbedder):
    id = "sface"
    dim = 128
    default_match_threshold = 0.46
    default_possible_threshold = 0.363

    def __init__(self, model_path: str | Path, model_version: str = "sface-2021dec") -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"SFace model not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version
        self._rec = cv2.FaceRecognizerSF.create(self.model_path, "")
        self.resolved_device = "cpu"

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        if aligned_bgr is None or aligned_bgr.shape[0] != self.input_size or aligned_bgr.shape[1] != self.input_size:
            aligned_bgr = cv2.resize(aligned_bgr, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR)
        feat = self._rec.feature(aligned_bgr)
        return l2_normalize(np.asarray(feat).reshape(-1))
