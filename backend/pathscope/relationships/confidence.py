"""Confidence of inferred relationships.

An inferred relationship is never a fact. Its confidence combines the
evidence that went into it, each component in 0..1 (``None`` = does not
apply):

* ``tracking``    - detection confidence of the tracks involved, lowered when a
                    track was lost and found again
* ``recognition`` - the recognition confidence, when the rule needed an identity
* ``spatial``     - how certain the measurement is: calibrated metres, a
                    single known distance, or uncalibrated frame units, and how
                    clearly the measured distance met the threshold
* ``temporal``    - how consistently the condition held over the interval
                    (valid samples / expected samples)
* ``sensor``      - agreement of other sensors (depth, radar, thermal) when any
                    reported on the same pair or place

The components are combined as a weighted geometric mean, capped at the
weakest component + 0.3 (strong tracking cannot make up for a weak
recognition), then scaled by the amount of support: a condition seen in
three samples is less certain than one seen in thirty.

States:

* ``confirmed``    - >= 0.85: the rule's conditions were met with strong evidence
* ``likely``       - >= 0.65
* ``possible``     - >= 0.40
* ``insufficient`` - below: kept for review, never acted on

Automated actions (events, webhooks) default to ``likely`` or better.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

STATES = ("insufficient", "possible", "likely", "confirmed")
STATE_RANK = {s: i for i, s in enumerate(STATES)}
THRESHOLDS = {"confirmed": 0.85, "likely": 0.65, "possible": 0.40}
STATE_LABELS = {"confirmed": "Confirmed by rule", "likely": "Likely", "possible": "Possible", "insufficient": "Insufficient evidence"}

WEIGHTS = {"tracking": 1.0, "recognition": 1.5, "spatial": 1.0, "temporal": 1.0, "sensor": 1.0}
WEAKEST_MARGIN = 0.3

# Measurement certainty by calibration mode
CALIBRATION_CERTAINTY = {"homography": 1.0, "scale": 0.85, "none": 0.65, "registry": 1.0}


@dataclass
class Components:
    tracking: float | None = None
    recognition: float | None = None
    spatial: float | None = None
    temporal: float | None = None
    sensor: float | None = None
    support: int = 1  # supporting samples or observations

    def to_dict(self) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _clamp(v: float) -> float:
    return min(1.0, max(0.0, float(v)))


def support_factor(n: int, half: float = 4.0) -> float:
    """0.6 for a single sample, approaching 1 with more support."""
    return 0.6 + 0.4 * (1.0 - math.exp(-max(0, n - 1) / half))


def combine(c: Components) -> float:
    num = 0.0
    den = 0.0
    weakest = 1.0
    for name, w in WEIGHTS.items():
        v = getattr(c, name)
        if v is None:
            continue
        num += w * math.log(max(1e-6, _clamp(v)))
        den += w
        weakest = min(weakest, _clamp(v))
    base = math.exp(num / den) if den > 0 else 0.5
    # one weak piece of evidence cannot be averaged away by strong ones
    base = min(base, weakest + WEAKEST_MARGIN)
    return round(_clamp(base * support_factor(c.support)), 4)


def state_for(confidence: float) -> str:
    for s in ("confirmed", "likely", "possible"):
        if confidence >= THRESHOLDS[s]:
            return s
    return "insufficient"


def at_least(state: str, minimum: str) -> bool:
    return STATE_RANK.get(state, 0) >= STATE_RANK.get(minimum, 0)


def margin(measured: float, threshold: float, below: bool = True) -> float:
    """How clearly a measurement met a threshold: 0.5 at the threshold, 1 far inside it."""
    if threshold <= 0:
        return 1.0
    rel = (threshold - measured) / threshold if below else (measured - threshold) / threshold
    return _clamp(0.5 + 0.5 * min(1.0, max(0.0, rel) * 2.0))


def spatial_certainty(calibration_mode: str, measured: float | None = None, threshold: float | None = None, below: bool = True) -> float:
    base = CALIBRATION_CERTAINTY.get(calibration_mode, 0.65)
    if measured is None or threshold is None:
        return base
    return _clamp(base * (0.7 + 0.3 * margin(measured, threshold, below)))
