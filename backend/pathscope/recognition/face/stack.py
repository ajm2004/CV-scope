"""Face stack factory: detector + aligner + quality + embedder for a stack id.

* ``opencv``      YuNet (MIT) + SFace (Apache-2.0); CPU through OpenCV DNN
* ``insightface`` SCRFD + ArcFace ResNet-50 through ONNX Runtime (weights for
                  non-commercial research use only)
* ``stub``        deterministic test stand-in, only when
                  ``PATHSCOPE_RECOGNITION_ALLOW_STUB=1`` is set

The stack is selected centrally (Recognition settings) and can be replaced
later without touching the pipeline.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

from pathscope.recognition.common.types import FaceDetection
from pathscope.recognition.face.alignment import FivePointAligner
from pathscope.recognition.face.detector.base import FaceDetector
from pathscope.recognition.face.embeddings.base import FaceEmbedder, l2_normalize
from pathscope.recognition.face.quality import FaceQualityAssessor

FACE_STACKS: dict[str, dict] = {
    "opencv": {"label": "OpenCV Zoo: YuNet + SFace", "detector": "face-det-yunet", "embedder": "face-emb-sface", "requires": "opencv"},
    "insightface": {"label": "InsightFace: SCRFD-10G + ArcFace R50 (research use)", "detector": "face-det-scrfd-10g", "embedder": "face-emb-arcface-r50", "requires": "onnxruntime"},
}


def stub_allowed() -> bool:
    return os.environ.get("PATHSCOPE_RECOGNITION_ALLOW_STUB", "") == "1"


@dataclass
class FaceStack:
    stack_id: str
    detector: FaceDetector
    aligner: FivePointAligner
    quality: FaceQualityAssessor
    embedder: FaceEmbedder
    # One stack is shared by the enrollment endpoints and the guided live
    # session, which run in different threads. OpenCV and ONNX Runtime
    # sessions are not safe to drive from two threads at once.
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def describe(self) -> dict:
        return {
            "stack": self.stack_id,
            "detector": self.detector.describe(),
            "alignment": self.aligner.describe(),
            "quality": self.quality.describe(),
            "embedder": self.embedder.describe(),
        }

    def close(self) -> None:
        self.detector.close()
        self.embedder.close()


class StubFaceDetector(FaceDetector):
    """Test stand-in: the central region of any image is 'the face'. Blank or
    blurred images are still rejected by the real quality assessor.

    The nose landmark follows the brightness of the picture: a brighter right
    half moves it right, a brighter lower half moves it down. A test can
    therefore act out a head that turns or a chin that drops by shading a
    synthetic frame, which is what drives the guided-capture tests."""

    id = "stub"
    model_version = "stub"

    def detect(self, image_bgr: np.ndarray) -> list[FaceDetection]:
        h, w = image_bgr.shape[:2]
        if h < 24 or w < 24:
            return []
        x1, y1, x2, y2 = w * 0.15, h * 0.1, w * 0.85, h * 0.9
        bw, bh = x2 - x1, y2 - y1
        gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        half_w, half_h = w // 2, h // 2
        dx = float(gray[:, half_w:].mean() - gray[:, :half_w].mean()) / 255.0
        dy = float(gray[half_h:, :].mean() - gray[:half_h, :].mean()) / 255.0
        nose_x = x1 + (0.5 + 0.6 * max(-0.5, min(0.5, dx))) * bw
        nose_y = y1 + (0.6 + 0.5 * max(-0.5, min(0.5, dy))) * bh
        lm = np.array(
            [[x1 + 0.3 * bw, y1 + 0.38 * bh], [x1 + 0.7 * bw, y1 + 0.38 * bh], [nose_x, nose_y], [x1 + 0.33 * bw, y1 + 0.8 * bh], [x1 + 0.67 * bw, y1 + 0.8 * bh]],
            dtype=np.float32,
        )
        return [FaceDetection((x1, y1, x2, y2), 0.95, lm)]


class StubFaceEmbedder(FaceEmbedder):
    """Test stand-in: coarse gray-level layout of the aligned crop (32-d)."""

    id = "stub"
    model_version = "stub"
    dim = 32
    default_match_threshold = 0.9
    default_possible_threshold = 0.75

    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        g = cv2.cvtColor(aligned_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        small = cv2.resize(g, (4, 4), interpolation=cv2.INTER_AREA).reshape(-1) / 255.0
        hist = cv2.calcHist([g.astype(np.uint8)], [0], None, [16], [0, 256]).reshape(-1)
        hist = hist / max(1.0, float(hist.sum()))
        vec = np.concatenate([small - small.mean(), np.sqrt(hist) - np.sqrt(hist).mean()])
        return l2_normalize(vec)


def create_face_stack(stack_id: str, models: dict, device: str = "auto", cfg: dict | None = None) -> FaceStack:
    """``models`` maps roles to weight paths: {"detector": ..., "embedder": ...}."""
    cfg = cfg or {}
    quality = FaceQualityAssessor(
        min_face_px=float(cfg.get("min_face_px", 40)),
        good_face_px=max(float(cfg.get("min_face_px", 40)) * 2.5, 80.0),
        min_quality=float(cfg.get("min_quality", 0.45)),
    )
    aligner = FivePointAligner(112)
    if stack_id == "stub":
        if not stub_allowed():
            raise RuntimeError("the stub face stack is only available in tests (PATHSCOPE_RECOGNITION_ALLOW_STUB=1)")
        return FaceStack("stub", StubFaceDetector(), aligner, quality, StubFaceEmbedder())
    if stack_id == "opencv":
        from pathscope.recognition.face.detector.yunet import YuNetDetector
        from pathscope.recognition.face.embeddings.sface import SFaceEmbedder

        return FaceStack("opencv", YuNetDetector(models["detector"]), aligner, quality, SFaceEmbedder(models["embedder"]))
    if stack_id == "insightface":
        from pathscope.recognition.face.detector.scrfd import ScrfdDetector
        from pathscope.recognition.face.embeddings.arcface_onnx import ArcFaceOnnxEmbedder

        return FaceStack("insightface", ScrfdDetector(models["detector"], device=device), aligner, quality, ArcFaceOnnxEmbedder(models["embedder"], device=device))
    raise ValueError(f"unknown face stack '{stack_id}'")
