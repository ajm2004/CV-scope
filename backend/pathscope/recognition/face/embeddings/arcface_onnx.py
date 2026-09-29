"""ArcFace-style embeddings from an ONNX model (InsightFace ``w600k_r50`` and
compatible exports): RGB 112x112 input normalised as (x - 127.5) / 127.5.

The InsightFace weights are for non-commercial research use only; see the
model catalog. Any ONNX model with the same input contract can be dropped in.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.common.onnx import create_session
from pathscope.recognition.face.embeddings.base import FaceEmbedder, l2_normalize


class ArcFaceOnnxEmbedder(FaceEmbedder):
    id = "arcface-onnx"
    default_match_threshold = 0.45
    default_possible_threshold = 0.32

    def __init__(self, model_path: str | Path, device: str = "auto", model_version: str = "arcface-r50-w600k", input_mean: float = 127.5, input_std: float = 127.5) -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"ArcFace model not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version
        self.input_mean = float(input_mean)
        self.input_std = float(input_std)
        self._session, self.resolved_device = create_session(model_path, device)
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = inp.shape
        if len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
            self.input_size = int(shape[2])
        out = self._session.get_outputs()[0]
        self._output_name = out.name
        self.dim = int(out.shape[-1]) if isinstance(out.shape[-1], int) else 512

    def _blob(self, imgs: list[np.ndarray]) -> np.ndarray:
        resized = [cv2.resize(i, (self.input_size, self.input_size), interpolation=cv2.INTER_LINEAR) if i.shape[0] != self.input_size or i.shape[1] != self.input_size else i for i in imgs]
        return cv2.dnn.blobFromImages(resized, 1.0 / self.input_std, (self.input_size, self.input_size), (self.input_mean, self.input_mean, self.input_mean), swapRB=True)

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        return self.embed_batch([aligned_bgr])[0]

    def embed_batch(self, aligned: list[np.ndarray]) -> list[np.ndarray | None]:
        if not aligned:
            return []
        out = self._session.run([self._output_name], {self._input_name: self._blob(aligned)})[0]
        out = np.asarray(out).reshape(len(aligned), -1)
        if self.dim != out.shape[1]:
            self.dim = int(out.shape[1])
        return [l2_normalize(row) for row in out]

    def close(self) -> None:
        self._session = None
