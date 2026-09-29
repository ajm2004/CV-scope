"""Face embedding interface: aligned 112x112 BGR crop in, unit vector out."""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


def l2_normalize(v: np.ndarray) -> np.ndarray | None:
    v = np.asarray(v, dtype=np.float32).reshape(-1)
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n < 1e-9:
        return None
    return (v / n).astype(np.float32)


class FaceEmbedder(ABC):
    id: str = "base"
    model_version: str = ""
    dim: int = 0
    input_size: int = 112
    # Calibrated cosine-similarity thresholds (administrators may override them)
    default_match_threshold: float = 0.5
    default_possible_threshold: float = 0.35
    resolved_device: str = "cpu"

    @abstractmethod
    def embed(self, aligned_bgr: np.ndarray) -> np.ndarray | None:
        """L2-normalised embedding of one aligned face, or ``None`` when unusable."""

    def embed_batch(self, aligned: list[np.ndarray]) -> list[np.ndarray | None]:
        return [self.embed(a) for a in aligned]

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass

    def describe(self) -> dict:
        return {
            "id": self.id,
            "model_version": self.model_version,
            "dim": self.dim,
            "device": self.resolved_device,
            "default_match_threshold": self.default_match_threshold,
            "default_possible_threshold": self.default_possible_threshold,
        }
