"""Temporal consensus over consecutive plate reads.

    Frame 1: DUB4?67    Frame 2: DUB4567    Frame 3: DUB4567    ->  DUB4567

Reads of the dominant length vote per character position, weighted by the
read's quality. A character below the confidence floor abstains. A position
is decided only when the winning character holds at least the configured
share of the weight; otherwise it stays '?'. Nothing is ever invented.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from pathscope.recognition.common.types import ConsensusResult, PlateRead


@dataclass
class _Read:
    chars: list[str]
    confs: list[float]
    weight: float
    t: float
    region: str | None


class PlateConsensus:
    def __init__(self, max_reads: int = 15, min_char_confidence: float = 0.5, agreement: float = 0.6) -> None:
        self.max_reads = max_reads
        self.min_char_confidence = float(min_char_confidence)
        self.agreement = float(agreement)
        self.reads: deque[_Read] = deque(maxlen=max_reads)

    def add(self, read: PlateRead, weight: float = 1.0, t: float = 0.0) -> None:
        if not read.chars:
            return
        self.reads.append(_Read(list(read.chars), [float(c) for c in read.confidences], max(1e-3, float(weight)), t, read.region))

    def clear(self) -> None:
        self.reads.clear()

    @property
    def n(self) -> int:
        return len(self.reads)

    def region(self) -> tuple[str | None, float]:
        votes: dict[str, float] = {}
        total = 0.0
        for r in self.reads:
            total += r.weight
            if r.region:
                votes[r.region] = votes.get(r.region, 0.0) + r.weight
        if not votes or total <= 0:
            return None, 0.0
        best = max(votes.items(), key=lambda kv: kv[1])
        return best[0], best[1] / total

    def result(self) -> ConsensusResult:
        if not self.reads:
            return ConsensusResult("", 0.0, 0, False)
        by_len: dict[int, float] = {}
        for r in self.reads:
            mean_conf = sum(r.confs) / len(r.confs) if r.confs else 0.0
            by_len[len(r.chars)] = by_len.get(len(r.chars), 0.0) + r.weight * max(mean_conf, 1e-3)
        length = max(by_len.items(), key=lambda kv: kv[1])[0]
        group = [r for r in self.reads if len(r.chars) == length]
        total_w = sum(r.weight for r in group)
        text: list[str] = []
        per_char: list[dict] = []
        conf_sum = 0.0
        for pos in range(length):
            votes: dict[str, float] = {}
            confs: dict[str, list[float]] = {}
            for r in group:
                c, p = r.chars[pos], r.confs[pos] if pos < len(r.confs) else 0.0
                if p < self.min_char_confidence:
                    continue
                votes[c] = votes.get(c, 0.0) + r.weight
                confs.setdefault(c, []).append(p)
            if votes:
                winner, w = max(votes.items(), key=lambda kv: kv[1])
                share = w / total_w if total_w > 0 else 0.0
                mean_conf = sum(confs[winner]) / len(confs[winner])
            else:
                winner, share, mean_conf = "?", 0.0, 0.0
            accepted = winner != "?" and share >= self.agreement and mean_conf >= self.min_char_confidence
            text.append(winner if accepted else "?")
            if accepted:
                conf_sum += share * mean_conf
            per_char.append({"pos": pos, "char": winner if accepted else "?", "share": round(share, 3), "confidence": round(mean_conf, 3), "votes": {k: round(v, 3) for k, v in votes.items()}})
        joined = "".join(text)
        return ConsensusResult(joined, conf_sum / length if length else 0.0, len(group), "?" not in joined, per_char)
