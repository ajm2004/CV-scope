"""Matching engine: a query embedding against every enrolled identity.

Each identity has one or more templates (its enrollment embeddings). The
similarity to an identity is the best cosine similarity over its templates.
The outcome is:

* ``recognized``      best >= match threshold and best - runner-up >= margin
* ``possible_match``  best >= possible threshold (or the margin is too small)
* ``unknown``         everything else

Identities outside their validity period or disabled are never matched.
Thresholds are configured centrally and default to the embedding model's
calibrated values. The matcher never forces a match.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np

from pathscope.recognition.common.types import (
    POSSIBLE_MATCH,
    RECOGNIZED,
    UNKNOWN,
    MatchCandidate,
    MatchResult,
)


@dataclass
class IdentityTemplates:
    identity_id: str
    display_name: str
    embeddings: np.ndarray  # (k, d), L2-normalised rows
    active: bool = True
    valid_from: date | None = None
    valid_until: date | None = None
    model_version: str = ""
    meta: dict = field(default_factory=dict)

    def valid_on(self, day: date) -> bool:
        if not self.active:
            return False
        if self.valid_from and day < self.valid_from:
            return False
        if self.valid_until and day > self.valid_until:
            return False
        return True


class FaceMatcher:
    def __init__(self, identities: list[IdentityTemplates], match_threshold: float, possible_threshold: float, margin: float = 0.05) -> None:
        self.match_threshold = float(match_threshold)
        self.possible_threshold = float(min(possible_threshold, match_threshold))
        self.margin = float(margin)
        self.identities: list[IdentityTemplates] = []
        self._matrix = np.zeros((0, 0), dtype=np.float32)
        self._owner = np.zeros((0,), dtype=np.int64)
        self._today: date | None = None
        self._valid_mask = np.zeros((0,), dtype=bool)
        self.rebuild(identities)

    # ------------------------------------------------------------- setup
    def rebuild(self, identities: list[IdentityTemplates]) -> None:
        self.identities = [i for i in identities if i.embeddings is not None and len(i.embeddings)]
        rows: list[np.ndarray] = []
        owner: list[int] = []
        for idx, ident in enumerate(self.identities):
            emb = np.asarray(ident.embeddings, dtype=np.float32)
            if emb.ndim == 1:
                emb = emb[None, :]
            norms = np.linalg.norm(emb, axis=1, keepdims=True)
            norms[norms < 1e-9] = 1.0
            emb = emb / norms
            ident.embeddings = emb
            rows.append(emb)
            owner.extend([idx] * len(emb))
        self._matrix = np.concatenate(rows, axis=0) if rows else np.zeros((0, 0), dtype=np.float32)
        self._owner = np.asarray(owner, dtype=np.int64)
        self._today = None

    @property
    def n_identities(self) -> int:
        return len(self.identities)

    @property
    def n_templates(self) -> int:
        return int(self._matrix.shape[0])

    def _validity(self, day: date) -> np.ndarray:
        if self._today != day:
            self._today = day
            self._valid_mask = np.array([i.valid_on(day) for i in self.identities], dtype=bool)
        return self._valid_mask

    # ------------------------------------------------------------- matching
    def similarities(self, embedding: np.ndarray, day: date | None = None) -> list[MatchCandidate]:
        """Best similarity per valid identity, sorted descending."""
        if self.n_templates == 0:
            return []
        q = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if q.shape[0] != self._matrix.shape[1]:
            raise ValueError(f"embedding dimension {q.shape[0]} does not match the templates ({self._matrix.shape[1]})")
        sims = self._matrix @ q
        valid = self._validity(day or date.today())
        best = np.full(len(self.identities), -2.0, dtype=np.float32)
        np.maximum.at(best, self._owner, sims)
        order = np.argsort(-best)
        out: list[MatchCandidate] = []
        for idx in order:
            if not valid[idx] or best[idx] <= -2.0:
                continue
            ident = self.identities[idx]
            out.append(MatchCandidate(ident.identity_id, ident.display_name, float(best[idx])))
        return out

    def match(self, embedding: np.ndarray, day: date | None = None, top_k: int = 5) -> MatchResult:
        candidates = self.similarities(embedding, day)
        if not candidates:
            return MatchResult(UNKNOWN, None, -1.0, [], self.match_threshold, self.possible_threshold, self.margin)
        best = candidates[0]
        second = candidates[1].similarity if len(candidates) > 1 else -1.0
        if best.similarity >= self.match_threshold and (best.similarity - second) >= self.margin:
            status = RECOGNIZED
        elif best.similarity >= self.possible_threshold:
            status = POSSIBLE_MATCH
        else:
            status = UNKNOWN
        keep = best if status != UNKNOWN else None
        return MatchResult(status, keep, second, candidates[:top_k], self.match_threshold, self.possible_threshold, self.margin)

    def describe(self) -> dict:
        return {
            "identities": self.n_identities,
            "templates": self.n_templates,
            "match_threshold": self.match_threshold,
            "possible_threshold": self.possible_threshold,
            "margin": self.margin,
        }
