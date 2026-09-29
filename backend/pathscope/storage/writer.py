"""Persist worker output: events, track summaries, trajectories and run stats.

The writer batches inserts and survives transient database failures by
keeping the batch and retrying on the next flush.
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from sqlalchemy.exc import SQLAlchemyError

from pathscope.db.models import Event, Run, TrackSummary, Trajectory
from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger

log = get_logger(__name__)


def _dt(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


class EventWriter:
    def __init__(self, run_id: int, experiment_id: int, camera_id: int | None, store_trajectories: bool = True, flush_interval_s: float = 1.0) -> None:
        self.run_id = run_id
        self.experiment_id = experiment_id
        self.camera_id = camera_id
        self.store_trajectories = store_trajectories
        self.flush_interval_s = flush_interval_s
        self._events: list[dict] = []
        self._tracks: list[dict] = []
        self._lock = threading.Lock()
        self._last_flush = time.time()
        self.written_events = 0
        self.written_tracks = 0
        self.failed_flushes = 0
        self.last_error: str | None = None

    # ------------------------------------------------------------------ queueing
    def add_events(self, events: list[dict]) -> None:
        with self._lock:
            self._events.extend(e for e in events if e.get("record", True))

    def add_track(self, summary: dict) -> None:
        with self._lock:
            self._tracks.append(summary)

    def maybe_flush(self) -> None:
        if time.time() - self._last_flush >= self.flush_interval_s:
            self.flush()

    # ------------------------------------------------------------------ flushing
    def flush(self) -> None:
        with self._lock:
            events, self._events = self._events, []
            tracks, self._tracks = self._tracks, []
        if not events and not tracks:
            self._last_flush = time.time()
            return
        Session = get_session_factory()
        session = Session()
        try:
            for e in events:
                session.add(
                    Event(
                        run_id=self.run_id,
                        experiment_id=self.experiment_id,
                        camera_id=self.camera_id,
                        track_id=int(e.get("track_id", 0)),
                        object_class=e.get("object_class") or "",
                        event_type=e.get("event_type") or "custom",
                        rule_id=e.get("rule_id"),
                        rule_name=e.get("rule_name"),
                        route=e.get("route"),
                        object_id=e.get("object_id"),
                        object_name=e.get("object_name"),
                        direction=e.get("direction"),
                        frame_index=int(e.get("frame_index", 0)),
                        media_time_s=float(e.get("media_time_s", 0.0)),
                        wall_time=_dt(e.get("wall_time")) or datetime.now(UTC),
                        entered_at_s=e.get("entered_at_s"),
                        completed_at_s=e.get("completed_at_s"),
                        duration_s=e.get("duration_s"),
                        avg_speed=e.get("avg_speed"),
                        speed_unit=e.get("speed_unit"),
                        confidence=e.get("confidence"),
                        context={**(e.get("context") or {}), "label": e.get("label")},
                    )
                )
            for tr in tracks:
                session.add(
                    TrackSummary(
                        run_id=self.run_id,
                        track_id=int(tr["track_id"]),
                        object_class=tr.get("object_class") or "",
                        first_seen_s=float(tr.get("first_seen_s", 0.0)),
                        last_seen_s=float(tr.get("last_seen_s", 0.0)),
                        first_seen_at=_dt(tr.get("first_seen_wall")),
                        last_seen_at=_dt(tr.get("last_seen_wall")),
                        n_frames=int(tr.get("n_frames", 0)),
                        path_length=tr.get("path_length"),
                        path_unit=tr.get("path_unit") or "frame",
                        avg_speed=tr.get("avg_speed"),
                        speed_unit=tr.get("speed_unit"),
                        mean_confidence=tr.get("mean_confidence"),
                        final_state=tr.get("final_state") or "removed",
                        route_result=tr.get("route_result"),
                        lost_count=int(tr.get("lost_count", 0)),
                    )
                )
                if self.store_trajectories and tr.get("points"):
                    session.add(
                        Trajectory(
                            run_id=self.run_id,
                            track_id=int(tr["track_id"]),
                            object_class=tr.get("object_class") or "",
                            points=tr["points"],
                            n_points=len(tr["points"]),
                        )
                    )
            session.commit()
            self.written_events += len(events)
            self.written_tracks += len(tracks)
            self.last_error = None
        except SQLAlchemyError as exc:
            session.rollback()
            self.failed_flushes += 1
            self.last_error = str(exc)
            log.warning("event flush failed; will retry", run_id=self.run_id, error=str(exc)[:200])
            with self._lock:
                self._events = events + self._events
                self._tracks = tracks + self._tracks
        finally:
            session.close()
            self._last_flush = time.time()

    def update_run(self, status: str | None = None, stats: dict | None = None, error: str | None = None, ended: bool = False, snapshot: dict | None = None) -> None:
        Session = get_session_factory()
        session = Session()
        try:
            run = session.get(Run, self.run_id)
            if run is None:
                return
            if status:
                run.status = status
                if status == "running" and run.started_at is None:
                    run.started_at = datetime.now(UTC)
            if stats is not None:
                merged = dict(run.stats or {})
                merged.update(stats)
                merged["written_events"] = self.written_events
                merged["written_tracks"] = self.written_tracks
                run.stats = merged
            if snapshot is not None:
                run.snapshot = {**(run.snapshot or {}), **snapshot}
            if error is not None:
                run.error = error
            if ended:
                run.ended_at = datetime.now(UTC)
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            log.warning("run update failed", run_id=self.run_id, error=str(exc)[:200])
        finally:
            session.close()
