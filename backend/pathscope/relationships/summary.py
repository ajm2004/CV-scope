"""Deterministic summaries of what the graph knows.

A summary is composed from timeline items only (observations, relationships
and correlated events that are stored), one sentence per actor and time
span:

    14:22:03-14:24:10  Employee-017 (Person track #3) entered Parking Zone 2,
    approached Vehicle track #9, was near Vehicle track #9 for 41 s and was
    last seen.

An optional language model may reword that text for readability. It
receives the deterministic text of an anonymous viewer (no names, no plates)
and nothing else; its answer is labelled as model-written and the
deterministic summary stays next to it as the source of truth.
"""

from __future__ import annotations

from datetime import datetime, timedelta

SKIP_TYPES = {"appeared"}
MAX_SENTENCES = 60
GAP_S = 120.0  # a pause this long starts a new sentence for the same actor

SYSTEM = (
    "You rewrite a factual activity summary from a video analysis system into clear, concise prose. "
    "Use ONLY the facts given. Do not add causes, intentions, relationships between people, ownership, emotions or any judgement. "
    "Keep every time, place and label exactly as given. Answer as JSON: {\"summary\": \"...\"}."
)
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"], "additionalProperties": False}


def _clock(at: datetime, tz_offset_min: int) -> str:
    return (at + timedelta(minutes=tz_offset_min)).strftime("%H:%M:%S")


def _join(clauses: list[str]) -> str:
    if len(clauses) <= 1:
        return "".join(clauses)
    return ", ".join(clauses[:-1]) + " and " + clauses[-1]


def _media(s: float) -> str:
    s = max(0.0, float(s))
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{int(s % 60):02d}" if s >= 3600 else f"{int(s // 60)}:{int(s % 60):02d}"


def compose(items: list[dict], tz_offset_min: int = 0, media_time: bool = False) -> dict:
    """Sentences from timeline items (as returned by Presenter.timeline).

    ``media_time``: times are the run's own clock (a video file is analysed
    faster than real time, so its wall-clock times would compress)."""
    sentences: list[dict] = []
    cur: dict | None = None
    if media_time:
        items = [it for it in items if it.get("media_time_s") is not None]
    for it in items:
        if it.get("type") in SKIP_TYPES:
            continue
        parts = it.get("parts") or {}
        subject = parts.get("subject") or ""
        if it["kind"] == "correlated" and it.get("type") == "deviation":
            clause = (it.get("description") or it["text"]).rstrip(".")
            subject = "Pattern deviation"
        elif it["kind"] == "correlated":
            clause = f"{it['text']}" + (f" ({', '.join(f'{k}: {v}' for k, v in (it.get('roles') or {}).items())})" if it.get("roles") else "")
            subject = "Correlated event"
        else:
            words = [parts.get("verb") or "", parts.get("object") or "", parts.get("extra") or ""]
            clause = " ".join(w for w in words if w)
            if it["kind"] == "relationship" and it.get("state") in ("possible", "insufficient"):
                clause += f" ({it['state']})"
        if media_time:
            at = float(it["media_time_s"])
            end = float(it.get("end_media_s") if it.get("end_media_s") is not None else at)
        else:
            at = it["at"]
            end = it.get("end_at") or at
        gap = (at - cur["end"]) if (cur is not None and media_time) else ((at - cur["end"]).total_seconds() if cur is not None else 0.0)
        if cur is not None and cur["subject"] == subject and gap <= GAP_S:
            if clause not in cur["clauses"]:
                cur["clauses"].append(clause)
            cur["end"] = max(cur["end"], end)
            cur["ids"].append((it["kind"], it["id"]))
            continue
        cur = {"subject": subject, "start": at, "end": end, "clauses": [clause], "ids": [(it["kind"], it["id"])], "run_id": it.get("run_id"), "media_time_s": it.get("media_time_s")}
        sentences.append(cur)
    out = []
    for s in sentences[:MAX_SENTENCES]:
        if media_time:
            span = _media(s["start"]) + ("" if s["end"] - s["start"] < 1 else "-" + _media(s["end"]))
        else:
            span = _clock(s["start"], tz_offset_min) + ("" if (s["end"] - s["start"]).total_seconds() < 1 else "-" + _clock(s["end"], tz_offset_min))
        text = (f"{s['subject']}: " if s["subject"] in ("Correlated event", "Pattern deviation") else f"{s['subject']} ") + (_join(s["clauses"]) if s["subject"] != "Pattern deviation" else "; ".join(s["clauses"])) + "."
        out.append({"span": span, "text": text, "start": s["start"], "end": s["end"], "items": [{"kind": k, "id": i} for k, i in s["ids"]],
                    "run_id": s["run_id"], "media_time_s": s["media_time_s"]})
    text = "\n".join(f"{s['span']}  {s['text']}" for s in out)
    if len(sentences) > MAX_SENTENCES:
        text += f"\n({len(sentences) - MAX_SENTENCES} more not shown: narrow the time range)"
    return {"text": text, "sentences": out, "facts": len(items), "clock": "media" if media_time else "wall"}


def reword(text: str, llm_settings, key: str | None) -> dict:
    """Optional model rewording of an anonymous deterministic summary."""
    from pathscope.anomaly.llm.client import complete_json

    answer, usage = complete_json(llm_settings, key, SYSTEM, "Facts (one line per time span):\n" + text, SCHEMA)
    summary = str(answer.get("summary") or "").strip()
    return {"text": summary, "provider": llm_settings.provider, "model": llm_settings.resolved_model, "usage": usage}
