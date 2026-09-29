"""Data types shared by the face and plate pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in frame pixels

# Recognition outcome of an observation set (see docs/recognition.md)
RECOGNIZED = "recognized"
POSSIBLE_MATCH = "possible_match"
UNKNOWN = "unknown"
INSUFFICIENT_QUALITY = "insufficient_quality"

# Enrollment views an operator is guided through
ENROLLMENT_VIEWS: tuple[str, ...] = ("front", "left", "right", "above", "below", "lighting", "rear")
# Views that carry a face (biometric input). "rear" is an appearance reference only.
BIOMETRIC_VIEWS: tuple[str, ...] = ("front", "left", "right", "above", "below", "lighting")


@dataclass(slots=True)
class QualityReport:
    """Quality of one face or plate crop. ``score`` is 0..1; ``usable`` says
    whether it may be used for recognition; ``reasons`` explains why not."""

    score: float
    usable: bool
    size_px: float
    blur: float  # 0..1, 1 = sharp
    exposure: float  # 0..1, 1 = well exposed
    contrast: float = 1.0  # 0..1
    yaw: float | None = None  # faces: - = turned to image-left, + = to image-right (approx.)
    pitch: float | None = None
    occlusion: float = 0.0  # 0..1 fraction judged obstructed / cut off
    reasons: list[str] = field(default_factory=list)
    # Mean brightness of the crop (0..1). Used to tell one lighting condition
    # from another during enrollment; not part of the quality score.
    brightness: float | None = None

    def to_dict(self) -> dict:
        return {
            "score": round(self.score, 3),
            "usable": self.usable,
            "size_px": round(self.size_px, 1),
            "blur": round(self.blur, 3),
            "exposure": round(self.exposure, 3),
            "contrast": round(self.contrast, 3),
            "yaw": round(self.yaw, 3) if self.yaw is not None else None,
            "pitch": round(self.pitch, 3) if self.pitch is not None else None,
            "occlusion": round(self.occlusion, 3),
            "reasons": list(self.reasons),
            "brightness": round(self.brightness, 3) if self.brightness is not None else None,
        }


@dataclass(slots=True)
class FaceDetection:
    box: Box
    score: float
    landmarks: np.ndarray | None = None  # (5, 2): image-left eye, image-right eye, nose, left mouth, right mouth

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass(slots=True)
class FaceObservation:
    track_id: int
    frame_index: int
    t: float
    detection: FaceDetection
    quality: QualityReport
    embedding: np.ndarray | None = None  # L2-normalised
    aligned: np.ndarray | None = None  # 112x112 BGR, kept only for enrollment / optional crops


@dataclass(slots=True)
class MatchCandidate:
    identity_id: str
    display_name: str
    similarity: float


@dataclass(slots=True)
class MatchResult:
    status: str  # RECOGNIZED | POSSIBLE_MATCH | UNKNOWN
    best: MatchCandidate | None
    second_similarity: float
    candidates: list[MatchCandidate]
    threshold: float
    possible_threshold: float
    margin: float

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "candidate": self.best.display_name if self.best else None,
            "candidate_id": self.best.identity_id if self.best else None,
            "similarity": round(self.best.similarity, 3) if self.best else None,
            "second_similarity": round(self.second_similarity, 3),
            "threshold": self.threshold,
            "possible_threshold": self.possible_threshold,
        }


@dataclass(slots=True)
class PlateDetection:
    box: Box
    score: float

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]


@dataclass(slots=True)
class PlateRead:
    """One OCR result: characters with per-character confidence."""

    chars: list[str]
    confidences: list[float]
    region: str | None = None
    region_confidence: float | None = None

    @property
    def text(self) -> str:
        return "".join(self.chars)

    @property
    def mean_confidence(self) -> float:
        return float(np.mean(self.confidences)) if self.confidences else 0.0

    @property
    def min_confidence(self) -> float:
        return float(min(self.confidences)) if self.confidences else 0.0

    def masked(self, min_char_confidence: float) -> str:
        """Characters below the confidence floor are shown as '?', never invented."""
        return "".join(c if p >= min_char_confidence else "?" for c, p in zip(self.chars, self.confidences, strict=False))


@dataclass(slots=True)
class PlateObservation:
    track_id: int
    frame_index: int
    t: float
    detection: PlateDetection
    quality: QualityReport
    read: PlateRead | None = None
    crop: np.ndarray | None = None


@dataclass(slots=True)
class ConsensusResult:
    text: str  # '?' marks an undecided position
    confidence: float
    n_observations: int
    complete: bool
    per_char: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "n_observations": self.n_observations,
            "complete": self.complete,
        }
