"""Wiring of cross-camera correlation (API process).

The relationship service hands over runs whose graph changed:

* live batches  -> ``enqueue(run, identities)``: the identities touched in the
                   batch are re-correlated (debounced, background thread);
* run finished, re-analysis current, analysis deleted
                -> ``enqueue(run)``: the whole run is re-correlated;
* topology edited
                -> ``correlate_window``: runs in a time range, on request.

New topology deviations are published as ordinary events of the run they
anchor to (``location_anomaly``), live when the run is active, stored
directly otherwise.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pathscope.db.models import Event, Run
from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger
from pathscope.relationships import entities as E

log = get_logger(__name__)

DEBOUNCE_S = 2.0


def publishable_event(c, track_id: int | None, object_class: str) -> dict:
    return {
        "track_id": int(track_id or 0), "object_class": object_class or "", "event_type": "location_anomaly", "label": c.label, "frame_index": 0,
        "media_time_s": round(float(c.end_media_s or c.start_media_s or 0.0), 3), "wall_time": (c.end_at or c.start_at).timestamp(), "rule_id": c.rule_key,
        "rule_name": c.rule_name, "route": None, "object_id": None, "object_name": None, "direction": None, "entered_at_s": c.start_media_s, "completed_at_s": c.end_media_s,
        "duration_s": None, "avg_speed": None, "speed_unit": None, "confidence": round(c.confidence, 3),
        "context": {"correlated_id": c.id, "kind": "topology", "type": (c.metrics or {}).get("type"), "state": c.state, "summary": c.description},
        "record": True, "count": True, "webhooks": [],
    }


class CrossCameraService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: dict[int, set[int] | None] = {}
        self._due = 0.0
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last: dict | None = None
        self.background = os.environ.get("PATHSCOPE_CROSSCAM_BACKGROUND", "1") != "0"

    # ------------------------------------------------------------ queue
    def enqueue(self, run_id: int | None, subjects: set[int] | None = None) -> None:
        if run_id is None:
            return
        with self._lock:
            if run_id in self._pending and self._pending[run_id] is None:
                pass
            elif subjects is None:
                self._pending[run_id] = None
            else:
                self._pending.setdefault(run_id, set())
                cur = self._pending[run_id]
                if cur is not None:
                    cur |= set(subjects)
            self._due = time.time() + DEBOUNCE_S
        if not self.background:
            return  # tests: the caller runs flush()
        self._ensure_thread()
        self._wake.set()

    def _ensure_thread(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="crosscam", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._wake.wait(5.0)
            self._wake.clear()
            if self._stop.is_set():
                return
            while True:
                with self._lock:
                    wait = self._due - time.time()
                if wait <= 0:
                    break
                if self._stop.wait(min(wait, 1.0)):
                    return
            with self._lock:
                work, self._pending = self._pending, {}
            for run_id, subjects in work.items():
                try:
                    self.run_now(run_id, subjects)
                except Exception as exc:  # noqa: BLE001 - correlation never blocks the rest
                    log.warning("cross-camera correlation failed", run_id=run_id, error=str(exc)[:300])

    def pending(self) -> dict[int, set[int] | None]:
        with self._lock:
            return dict(self._pending)

    def flush(self) -> None:
        """Process everything queued now (tests)."""
        with self._lock:
            work, self._pending = self._pending, {}
        for run_id, subjects in work.items():
            self.run_now(run_id, subjects)

    # ------------------------------------------------------------ work
    def run_now(self, run_id: int, subjects: set[int] | None = None) -> dict:
        return self.correlate({run_id}, subjects)

    def correlate(self, run_ids: set[int], subjects: set[int] | None = None) -> dict:
        from pathscope.crosscam.engine import Correlator, cleanup
        from pathscope.location.settings import load_crosscam_settings
        from pathscope.location.topology import LocationGraph

        Session = get_session_factory()
        with Session() as session:
            cfg = load_crosscam_settings(session)
            loc = LocationGraph.load(session)
            c = Correlator(session, loc, cfg)
            res = c.rebuild(set(run_ids), subjects)
            cleanup(session)
            session.commit()
            if res.new_deviations and cfg.publish_anomalies:
                self._publish(session, res.new_deviations)
            out = {**res.to_dict(), "runs": sorted(run_ids), "at": datetime.now(UTC).isoformat()}
        self.last = out
        return out

    def correlate_window(self, session: Session, time_from: datetime | None, time_to: datetime | None) -> dict:
        q = select(Run.id).where(Run.started_at.is_not(None))
        if time_to is not None:
            q = q.where(Run.started_at <= time_to)
        if time_from is not None:
            q = q.where(or_(Run.ended_at.is_(None), Run.ended_at >= time_from))
        runs = set(session.scalars(q))
        if not runs:
            return {"transitions": 0, "withdrawn": 0, "relationships": 0, "deviations": 0, "subjects": 0, "runs": []}
        return self.correlate(runs)

    def _publish(self, session: Session, correlated_ids: list[int]) -> None:
        from pathscope.relationships.models import RelationCorrelated, RelationEntity

        by_run: dict[int, list[dict]] = {}
        for cid in correlated_ids:
            c = session.get(RelationCorrelated, cid)
            if c is None or c.published or c.run_id is None:
                continue
            anchor = session.get(RelationEntity, (c.metrics or {}).get("anchor_track") or -1)
            tid = E.parse_track_ref(anchor.ref)[1] if anchor is not None and E.parse_track_ref(anchor.ref) else None
            cls = (anchor.meta or {}).get("object_class", "") if anchor is not None else ""
            by_run.setdefault(c.run_id, []).append(publishable_event(c, tid, cls))
            c.published = True
        session.commit()
        if not by_run:
            return
        from pathscope.workers.supervisor import get_supervisor

        sup = get_supervisor()
        for run_id, events in by_run.items():
            h = sup.get(run_id)
            if h is not None and not h.finished:
                sup.publish_events(h, events)
                continue
            run = session.get(Run, run_id)
            if run is None:
                continue
            for e in events:
                session.add(Event(
                    run_id=run_id, experiment_id=run.experiment_id, camera_id=run.camera_id, track_id=e["track_id"], object_class=e["object_class"], event_type=e["event_type"],
                    rule_id=e["rule_id"], rule_name=e["rule_name"], media_time_s=e["media_time_s"], wall_time=datetime.fromtimestamp(e["wall_time"], tz=UTC),
                    entered_at_s=e["entered_at_s"], completed_at_s=e["completed_at_s"], confidence=e["confidence"], context=e["context"],
                ))
            session.commit()


_service: CrossCameraService | None = None


def get_crosscam_service() -> CrossCameraService:
    global _service
    if _service is None:
        _service = CrossCameraService()
    return _service
