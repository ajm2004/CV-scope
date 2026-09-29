"""Deterministic one-line descriptions: every event has one, with or without a model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pathscope.anomaly.config import FRAME_ZONE_ID
from pathscope.anomaly.subjects import subject_phrase

if TYPE_CHECKING:
    from pathscope.anomaly.detector import AnomalyUpdate

END_REASONS = {
    "cleared": "back to normal",
    "accepted": "accepted as the new normal",
    "run_ended": "the run ended",
    "view_changed": "the whole picture changed",
    "rebaselined": "the normal picture was learned again",
}


def duration_text(seconds: float) -> str:
    s = max(0, round(seconds))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s} s" if s else f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min"


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


PLURALS = {"person": "people", "bus": "buses"}


def _who(subjects: list[dict]) -> str:
    """'2 people', '[Person A] (recognized person) and a dog': identical anonymous phrases are counted."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for s in subjects:
        p = subject_phrase(s)
        if p not in counts:
            order.append(p)
        counts[p] = counts.get(p, 0) + 1
    parts = []
    for p in order[:4]:
        n = counts[p]
        if n > 1 and (p.startswith("a ") or p.startswith("an ")):
            words = p.split(" ", 1)[1].split(" ")
            words[-1] = PLURALS.get(words[-1], words[-1] + "s")
            parts.append(f"{n} {' '.join(words)}")
        else:
            parts.append(p)
    if len(order) > 4:
        parts.append(f"{sum(counts[p] for p in order[4:])} more")
    return _join(parts)


def summarize(u: AnomalyUpdate) -> str:
    where = "the picture" if u.zone_id == FRAME_ZONE_ID else u.zone_name
    if u.kind == "lighting":
        text = "The lighting of the whole picture changed"
    elif u.kind == "tamper":
        text = "The camera view was blocked, blinded or moved"
    elif u.kind == "presence":
        who = _who(u.subjects) or "someone or something"
        text = f"{_capital(who)} {'appeared in' if u.zone_id == FRAME_ZONE_ID else 'entered'} {where}"
    elif u.kind == "motion":
        who = _who(u.subjects)
        text = f"Movement in {where} with {who}" if who else f"Movement in {where} (no tracked object explains it)"
    elif u.kind == "appeared":
        text = f"Something appeared in {where}"
    elif u.kind == "disappeared":
        text = f"Something was removed from {where}"
    elif u.kind == "moved":
        text = f"Something was moved in {where}"
    else:
        text = f"{_capital(where)} changed compared with its normal state"
    if u.kind in ("motion", "appeared", "disappeared", "moved", "changed") and u.area_pct:
        text += f" ({u.area_pct:.1f}% of the {'picture' if u.zone_id == FRAME_ZONE_ID else 'zone'})"
    if u.phase == "ended" and u.ended_t is not None and not u.instant:
        text += f"; lasted {duration_text(u.ended_t - u.started_t)}"
        if u.end_reason in END_REASONS:
            text += f", {END_REASONS[u.end_reason]}"
    return text + "."
