"""Per-track recognition buffer: keeps the best observations of a track.

    Track #204   Face observations: 12   Usable: 5   Best: frame 1381

Observations are ranked by quality; only the best ``capacity`` are kept, and
their embeddings can be aggregated (quality-weighted) into one query vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class _Item:
    quality: float
    seq: int
    obs: Any


@dataclass
class ObservationBuffer:
    capacity: int = 12
    items: list[_Item] = field(default_factory=list)
    total_seen: int = 0
    usable_seen: int = 0
    unusable_reasons: dict[str, int] = field(default_factory=dict)
    # Best usable observation ever seen (survives resets, for diagnostics and events)
    best_ever_quality: float = 0.0
    best_ever_frame: int | None = None
    _seq: int = 0

    def add(self, obs: Any, quality: float, usable: bool, reasons: list[str] | None = None) -> bool:
        """Record an observation. Only usable ones are kept; returns whether it was kept."""
        self.total_seen += 1
        self._seq += 1
        if not usable:
            for r in reasons or ["unusable"]:
                self.unusable_reasons[r] = self.unusable_reasons.get(r, 0) + 1
            return False
        self.usable_seen += 1
        if quality > self.best_ever_quality or self.best_ever_frame is None:
            self.best_ever_quality = quality
            self.best_ever_frame = getattr(obs, "frame_index", None)
        self.items.append(_Item(quality, self._seq, obs))
        self.items.sort(key=lambda it: (it.quality, it.seq), reverse=True)
        if len(self.items) > self.capacity:
            del self.items[self.capacity :]
        return True

    @property
    def n_kept(self) -> int:
        return len(self.items)

    @property
    def best(self) -> Any | None:
        return self.items[0].obs if self.items else None

    @property
    def best_quality(self) -> float:
        return self.items[0].quality if self.items else 0.0

    def observations(self) -> list[Any]:
        return [it.obs for it in self.items]

    def aggregate_embeddings(self, attr: str = "embedding") -> np.ndarray | None:
        """Quality-weighted mean of the kept embeddings, re-normalised."""
        vecs = [(it.quality, getattr(it.obs, attr)) for it in self.items if getattr(it.obs, attr, None) is not None]
        if not vecs:
            return None
        weights = np.array([max(1e-3, q) for q, _ in vecs], dtype=np.float32)
        mat = np.stack([v for _, v in vecs]).astype(np.float32)
        agg = (mat * weights[:, None]).sum(axis=0) / weights.sum()
        n = float(np.linalg.norm(agg))
        if n < 1e-9:
            return None
        return (agg / n).astype(np.float32)

    def reset(self, keep_best: int = 0) -> None:
        self.items = self.items[: max(0, keep_best)]

    def summary(self) -> dict:
        return {
            "observations": self.total_seen,
            "usable": self.usable_seen,
            "kept": len(self.items),
            "best_frame": self.best_ever_frame,
            "best_quality": round(self.best_ever_quality, 3) if self.best_ever_frame is not None else None,
            "rejected": dict(self.unusable_reasons),
        }
