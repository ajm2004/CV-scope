"""CV-Scope's wiring of the Anomaly Assistant (API process).

Run workers detect anomalies and write their evidence pictures; this service
receives the confirmed and ended anomalies, stores them, decides when an
anomaly becomes an alert, and asks the vision language model when a zone
wants one:

* ``deterministic`` - raised at once, no model
* ``assisted``      - raised at once; the model's description follows
                      (when the event is confirmed, or when it ends)
* ``confirmed``     - raised only after the model agrees (``confirmed`` or
                      ``uncertain``); ``rejected`` events are kept as
                      *dismissed* for review. When the model cannot be asked
                      (no model, error, budget, queue full) the run's
                      ``on_llm_failure`` policy raises the event anyway
                      (default) or holds it for an operator.

A raised anomaly becomes an ordinary event (type ``anomaly``) of the run: it
is stored with the other events, shown live, counted, starts video clips in
the worker and sends the zone's webhooks. Model calls run on a small thread
pool with a queue limit and an hourly budget, so a busy scene cannot flood a
provider or a local GPU.
"""

from __future__ import annotations

import shutil
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.anomaly.config import KIND_LABELS
from pathscope.anomaly.llm.client import LLMError, interpret
from pathscope.anomaly.llm.prompt import choose_pictures
from pathscope.anomaly.llm.settings import KeyStore, LLMSettings, load_settings
from pathscope.anomaly.models import AnomalyEvent
from pathscope.anomaly.subjects import generic_names
from pathscope.config import get_settings
from pathscope.db.models import Camera, Run
from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------- files
def evidence_root() -> Path:
    return get_settings().resolved_data_dir / "anomalies"


def run_dir(run_id: int) -> Path:
    return evidence_root() / f"run-{run_id}"


def evidence_path(row: AnomalyEvent, name: str) -> Path | None:
    rel = (row.evidence or {}).get(name)
    if not rel:
        return None
    base = run_dir(row.run_id).resolve()
    path = (base / rel).resolve()
    return path if path.is_relative_to(base) else None


def delete_evidence(row: AnomalyEvent) -> None:
    folder = (run_dir(row.run_id) / row.uid).resolve()
    if folder.is_relative_to(evidence_root().resolve()):
        shutil.rmtree(folder, ignore_errors=True)


def delete_run_evidence(run_id: int) -> None:
    shutil.rmtree(run_dir(run_id), ignore_errors=True)


def key_store() -> KeyStore:
    return KeyStore(get_settings().resolved_data_dir)


# ---------------------------------------------------------------------------- views
def anomaly_out(row: AnomalyEvent, camera_name: str | None = None) -> dict:
    return {
        "id": row.id, "uid": row.uid, "run_id": row.run_id, "experiment_id": row.experiment_id, "camera_id": row.camera_id, "camera_name": camera_name,
        "zone_id": row.zone_id, "zone_name": row.zone_name, "expected_state": row.expected_state, "kind": row.kind, "kind_label": KIND_LABELS.get(row.kind, row.kind),
        "status": row.status, "published": row.published, "confidence": row.confidence, "area_pct": row.area_pct, "bbox": row.bbox,
        "started_media_s": row.started_media_s, "confirmed_media_s": row.confirmed_media_s, "ended_media_s": row.ended_media_s, "duration_s": row.duration_s,
        "started_at": row.started_at, "confirmed_at": row.confirmed_at, "ended_at": row.ended_at, "end_reason": row.end_reason,
        "summary": row.summary, "objects": row.objects or [], "subjects": row.subjects or [], "metrics": row.metrics or {},
        "evidence": {name: f"/api/anomalies/{row.id}/evidence/{name}" for name in (row.evidence or {})},
        "validation": (row.zone_settings or {}).get("validation", "deterministic"), "interpret_at": (row.zone_settings or {}).get("interpret_at", "confirm"),
        "llm": {
            "status": row.llm_status, "verdict": row.llm_verdict, "category": row.llm_category, "description": row.llm_description, "confidence": row.llm_confidence,
            "evidence": row.llm_evidence, "provider": row.llm_provider, "model": row.llm_model, "latency_ms": row.llm_latency_ms, "error": row.llm_error, "at": row.llm_at,
        },
        "feedback": row.feedback, "note": row.note, "created_at": row.created_at,
    }


def _dt(ts: float | None) -> datetime | None:
    return None if ts is None else datetime.fromtimestamp(float(ts), tz=UTC)


def event_for(row: AnomalyEvent) -> dict:
    """The ordinary run event an anomaly becomes when it is raised (no names, no aliases)."""
    subjects = row.subjects or []
    first = subjects[0] if subjects else None
    context: dict = {
        "anomaly_id": row.id, "anomaly_uid": row.uid, "kind": row.kind, "summary": generic_names(row.summary, subjects),
        "validation": (row.zone_settings or {}).get("validation", "deterministic"), "area_pct": round(row.area_pct, 2),
    }
    if row.llm_description:
        context["description"] = generic_names(row.llm_description, subjects)
        context["verdict"] = row.llm_verdict
    if first and first.get("kind"):
        context["entity"] = {k: first[k] for k in ("kind", "identity_id", "vehicle_id", "status", "confidence", "recognition_event_id") if k in first}
    return {
        "track_id": int(first["track_id"]) if first else 0,
        "object_class": first["object_class"] if first else "scene",
        "event_type": "anomaly",
        "label": f"Anomaly · {row.zone_name}: {KIND_LABELS.get(row.kind, row.kind)}",
        "frame_index": 0,
        "media_time_s": round(row.confirmed_media_s, 3),
        "wall_time": row.confirmed_at.timestamp() if row.confirmed_at else time.time(),
        "rule_id": None, "rule_name": None, "route": None,
        "object_id": row.zone_id, "object_name": row.zone_name, "direction": None,
        "entered_at_s": round(row.started_media_s, 3), "completed_at_s": None, "duration_s": None,
        "avg_speed": None, "speed_unit": None, "confidence": round(row.confidence, 3),
        "context": context, "record": True, "count": True,
        "webhooks": list((row.zone_settings or {}).get("webhooks") or []),
    }


def webhook_payload(kind: str, row: AnomalyEvent) -> dict:
    subjects = row.subjects or []
    return {
        "type": kind, "anomaly_id": row.id, "zone": row.zone_name, "kind": row.kind, "status": row.status,
        "summary": generic_names(row.summary, subjects), "description": generic_names(row.llm_description or "", subjects) or None,
        "verdict": row.llm_verdict, "confidence": row.confidence, "duration_s": row.duration_s,
        "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None, "ended_at": row.ended_at.isoformat() if row.ended_at else None,
    }


# ---------------------------------------------------------------------------- service
class AnomalyService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._executor: ThreadPoolExecutor | None = None
        self._workers = 0
        self._pending = 0
        self._calls: deque[float] = deque()
        self.stats = {"calls": 0, "failures": 0, "skipped_budget": 0, "skipped_queue": 0, "last_latency_ms": None, "last_error": None}

    # ------------------------------------------------------------ worker updates
    def handle_updates(self, handle, updates: list[dict], supervisor) -> None:
        for u in updates:
            try:
                if u.get("phase") == "confirmed":
                    self._confirmed(handle, u, supervisor)
                    if u.get("instant"):
                        self._ended(handle, {**u, "phase": "ended", "ended_t": u.get("confirmed_t"), "wall_ended": u.get("wall_confirmed"), "end_reason": "instant"}, supervisor)
                elif u.get("phase") == "ended":
                    self._ended(handle, u, supervisor)
            except Exception as exc:  # noqa: BLE001 - one bad update never blocks the rest
                log.warning("anomaly update not handled", run_id=handle.run_id, error=str(exc)[:300])

    def _confirmed(self, handle, u: dict, supervisor) -> None:
        run_settings = ((handle.spec.anomaly or {}).get("settings") or {})
        zone = dict(u.get("zone") or {})
        zone["on_llm_failure"] = run_settings.get("on_llm_failure", "raise")
        Session = get_session_factory()
        with Session() as session:
            llm = load_settings(session)
            row = AnomalyEvent(
                uid=u["uid"], run_id=handle.run_id, experiment_id=handle.spec.experiment_id, camera_id=handle.spec.camera_id,
                zone_id=u["zone_id"], zone_name=u.get("zone_name") or u["zone_id"], expected_state=zone.get("expected_state") or "",
                kind=u["kind"], confidence=float(u.get("confidence") or 0.0), area_pct=float(u.get("area_pct") or 0.0), bbox=u.get("bbox") or [],
                started_media_s=float(u.get("started_t") or 0.0), confirmed_media_s=float(u.get("confirmed_t") or 0.0),
                started_at=_dt(u.get("wall_started")) or datetime.now(UTC), confirmed_at=_dt(u.get("wall_confirmed")) or datetime.now(UTC),
                summary=u.get("summary") or "", objects=u.get("objects") or [], subjects=u.get("subjects") or [], metrics=u.get("metrics") or {},
                evidence=u.get("evidence") or {}, zone_settings=zone, status="raised", llm_status="off", note="",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            validation = zone.get("validation", "deterministic")
            ask_now = validation != "deterministic" and zone.get("interpret_at", "confirm") == "confirm"
            if validation == "deterministic":
                self._publish(session, row, handle, supervisor)
                return
            if validation == "assisted":
                self._publish(session, row, handle, supervisor)
                if not ask_now:
                    row.llm_status = "pending_end"
                    session.commit()
                    return
            else:  # confirmed: raised after the verdict
                row.status = "awaiting_model"
                session.commit()
            self._ask(session, row, llm, handle, supervisor, at_end=False)

    def _ended(self, handle, u: dict, supervisor) -> None:
        Session = get_session_factory()
        with Session() as session:
            row = session.scalar(select(AnomalyEvent).where(AnomalyEvent.uid == u["uid"]))
            if row is None:
                return
            row.ended_media_s = u.get("ended_t")
            row.ended_at = _dt(u.get("wall_ended"))
            row.duration_s = None if u.get("instant") else u.get("duration_s")
            row.end_reason = u.get("end_reason")
            if not u.get("instant"):
                row.kind = u.get("kind") or row.kind
                row.summary = u.get("summary") or row.summary
                row.confidence = max(row.confidence, float(u.get("confidence") or 0.0))
                if u.get("subjects"):
                    row.subjects = u["subjects"]  # recognition often decides after the confirmation
                    row.objects = u.get("objects") or row.objects
                row.metrics = {**(row.metrics or {}), **(u.get("metrics") or {})}
                row.evidence = {**(row.evidence or {}), **(u.get("evidence") or {})}
            session.commit()
            zone = row.zone_settings or {}
            if row.published and not u.get("instant"):
                supervisor.notify(handle, list(zone.get("webhooks") or []), webhook_payload("anomaly.ended", row))
            if row.llm_status == "pending_end":
                self._ask(session, row, load_settings(session), handle, supervisor, at_end=True)

    # ------------------------------------------------------------ publication
    def _publish(self, session: Session, row: AnomalyEvent, handle, supervisor) -> None:
        row.status = "raised"
        row.published = True
        session.commit()
        event = event_for(row)
        if handle is not None and supervisor is not None:
            supervisor.publish_events(handle, [event])
            return
        # The run is over (an operator raised a held event later): store the event directly
        from pathscope.storage.writer import EventWriter

        writer = EventWriter(row.run_id, row.experiment_id or 0, row.camera_id)
        writer.add_events([event])
        writer.flush()

    def raise_now(self, session: Session, row: AnomalyEvent) -> None:
        """An operator raises a held or dismissed anomaly."""
        from pathscope.workers.supervisor import get_supervisor

        sup = get_supervisor()
        handle = sup.get(row.run_id)
        self._publish(session, row, handle if handle is not None and not handle.finished else None, sup if handle is not None and not handle.finished else None)

    # ------------------------------------------------------------ model
    def _ask(self, session: Session, row: AnomalyEvent, llm: LLMSettings, handle, supervisor, at_end: bool) -> None:
        reason = None
        if not llm.enabled:
            reason = "No vision language model is selected (Anomaly Assistant settings)."
        else:
            with self._lock:
                now = time.time()
                while self._calls and now - self._calls[0] > 3600.0:
                    self._calls.popleft()
                if len(self._calls) >= llm.max_calls_per_hour:
                    reason = f"The hourly budget of {llm.max_calls_per_hour} model calls is used up."
                    self.stats["skipped_budget"] += 1
                elif self._pending >= llm.queue_limit:
                    reason = f"{self._pending} events are already waiting for the model."
                    self.stats["skipped_queue"] += 1
                else:
                    self._calls.append(now)
                    self._pending += 1
                    if self._executor is None or self._workers != llm.max_concurrent:
                        if self._executor is not None:
                            self._executor.shutdown(wait=False)
                        self._executor = ThreadPoolExecutor(max_workers=llm.max_concurrent, thread_name_prefix="anomaly-llm")
                        self._workers = llm.max_concurrent
                    executor = self._executor
        if reason is not None:
            row.llm_status = "skipped"
            row.llm_error = reason
            session.commit()
            self._no_verdict(session, row, handle, supervisor)
            return
        row.llm_status = "queued"
        session.commit()
        executor.submit(self._job, row.id, llm, handle, supervisor, at_end)

    def _job(self, row_id: int, llm: LLMSettings, handle, supervisor, at_end: bool) -> None:
        try:
            Session = get_session_factory()
            with Session() as session:
                row = session.get(AnomalyEvent, row_id)
                if row is None:
                    return
                row.llm_status = "running"
                session.commit()
                try:
                    result = self.run_model(session, row, llm, at_end)
                except LLMError as exc:
                    row.llm_status = "failed"
                    row.llm_error = str(exc)[:1000]
                    row.llm_at = datetime.now(UTC)
                    session.commit()
                    with self._lock:
                        self.stats["failures"] += 1
                        self.stats["last_error"] = str(exc)[:300]
                    self._no_verdict(session, row, handle, supervisor)
                    return
                self._apply(session, row, result)
                zone = row.zone_settings or {}
                if row.status == "awaiting_model":
                    if result.verdict == "rejected":
                        row.status = "dismissed"
                        session.commit()
                    else:
                        self._publish(session, row, handle, supervisor)
                elif row.published:
                    supervisor.notify(handle, list(zone.get("webhooks") or []), webhook_payload("anomaly.described", row))
        except Exception as exc:  # noqa: BLE001 - a crashed job must not leave the pool
            log.warning("anomaly model job failed", anomaly_id=row_id, error=str(exc)[:300])
        finally:
            with self._lock:
                self._pending = max(0, self._pending - 1)

    def _no_verdict(self, session: Session, row: AnomalyEvent, handle, supervisor) -> None:
        """No model answer: a model-confirmed zone follows the run's policy."""
        if row.status != "awaiting_model":
            return
        if (row.zone_settings or {}).get("on_llm_failure", "raise") == "hold":
            row.status = "held"
            session.commit()
        else:
            self._publish(session, row, handle, supervisor)

    def run_model(self, session: Session, row: AnomalyEvent, llm: LLMSettings, at_end: bool | None = None):
        """Ask the model about one stored anomaly (also used for "Describe again")."""
        if at_end is None:
            at_end = row.ended_at is not None
        camera = session.get(Camera, row.camera_id) if row.camera_id else None
        record = {
            "camera_name": camera.name if camera else None, "zone_id": row.zone_id, "zone_name": row.zone_name, "expected_state": row.expected_state,
            "kind": row.kind, "confidence": row.confidence, "area_pct": row.area_pct, "bbox": row.bbox, "started_at": row.started_at,
            "confirmed_after_s": max(0.0, row.confirmed_media_s - row.started_media_s), "duration_s": row.duration_s if at_end else None,
            "end_reason": row.end_reason if at_end else None, "subjects": row.subjects or [], "metrics": row.metrics or {}, "summary": row.summary,
        }
        pictures: list[tuple[str, bytes]] = []
        for name in choose_pictures(row.evidence or {}, at_end, llm.include_crops):
            path = evidence_path(row, name)
            if path is not None and path.is_file():
                pictures.append((name, path.read_bytes()))
        key, _ = key_store().get(llm.provider)
        result = interpret(llm, key, record, pictures)
        with self._lock:
            self.stats["calls"] += 1
            self.stats["last_latency_ms"] = result.latency_ms
        return result

    @staticmethod
    def _apply(session: Session, row: AnomalyEvent, result) -> None:
        row.llm_status = "done"
        row.llm_verdict = result.verdict
        row.llm_category = result.category
        row.llm_description = result.description
        row.llm_confidence = result.confidence
        row.llm_evidence = result.evidence
        row.llm_provider = result.provider
        row.llm_model = result.model
        row.llm_latency_ms = result.latency_ms
        row.llm_error = None
        row.llm_at = datetime.now(UTC)
        session.commit()

    def describe_again(self, session: Session, row: AnomalyEvent) -> AnomalyEvent:
        llm = load_settings(session)
        try:
            result = self.run_model(session, row, llm)
        except LLMError as exc:
            row.llm_status = "failed"
            row.llm_error = str(exc)[:1000]
            row.llm_at = datetime.now(UTC)
            session.commit()
            raise
        self._apply(session, row, result)
        return row

    def queue_state(self) -> dict:
        with self._lock:
            now = time.time()
            recent = sum(1 for t in self._calls if now - t <= 3600.0)
            return {"pending": self._pending, "calls_last_hour": recent, **self.stats}

    def shutdown(self) -> None:
        with self._lock:
            if self._executor is not None:
                self._executor.shutdown(wait=False, cancel_futures=True)
                self._executor = None


_service: AnomalyService | None = None


def get_anomaly_service() -> AnomalyService:
    global _service
    if _service is None:
        _service = AnomalyService()
    return _service


# ---------------------------------------------------------------------------- maintenance
def sweep(now: datetime | None = None) -> dict:
    """Delete evidence of runs that no longer exist and anomalies past their retention;
    mark model calls that a restart interrupted."""
    from pathscope.settings_store import get_setting

    now = now or datetime.now(UTC)
    removed_dirs = removed_rows = 0
    Session = get_session_factory()
    with Session() as session:
        root = evidence_root()
        if root.is_dir():
            known = set(session.scalars(select(Run.id)))
            for d in root.iterdir():
                if d.is_dir() and d.name.startswith("run-"):
                    try:
                        rid = int(d.name[4:])
                    except ValueError:
                        continue
                    if rid not in known:
                        shutil.rmtree(d, ignore_errors=True)
                        removed_dirs += 1
        days = int(get_setting(session, "anomaly_retention_days", 0) or 0)
        if days > 0:
            cutoff = now - timedelta(days=days)
            for row in session.scalars(select(AnomalyEvent).where(AnomalyEvent.confirmed_at < cutoff)):
                delete_evidence(row)
                session.delete(row)
                removed_rows += 1
            session.commit()
    return {"removed_dirs": removed_dirs, "removed_rows": removed_rows}


def recover_interrupted() -> int:
    """Model calls do not survive a restart: report them as failed and apply the policy."""
    Session = get_session_factory()
    n = 0
    with Session() as session:
        for row in session.scalars(select(AnomalyEvent).where(AnomalyEvent.llm_status.in_(("queued", "running")))):
            row.llm_status = "failed"
            row.llm_error = "CV-Scope restarted before the model answered."
            if row.status == "awaiting_model":
                row.status = "held"  # the run is gone; an operator can raise it from the Anomalies page
            n += 1
        session.commit()
    return n


def usage() -> dict:
    root = evidence_root()
    files = size = 0
    if root.is_dir():
        for p in root.rglob("*.jpg"):
            files += 1
            size += p.stat().st_size
    return {"files": files, "bytes": size}


_stop = threading.Event()
_thread: threading.Thread | None = None


def start_maintenance(interval_s: float = 3600.0, first_delay_s: float = 90.0) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    try:
        recover_interrupted()
    except Exception as exc:  # noqa: BLE001
        log.warning("anomaly recovery failed", error=str(exc)[:200])

    def _loop() -> None:
        if _stop.wait(first_delay_s):
            return
        while True:
            try:
                sweep()
            except Exception as exc:  # noqa: BLE001
                log.warning("anomaly sweep failed", error=str(exc)[:200])
            if _stop.wait(interval_s):
                return

    _thread = threading.Thread(target=_loop, name="anomaly-maintenance", daemon=True)
    _thread.start()


def stop_maintenance() -> None:
    _stop.set()
    get_anomaly_service().shutdown()
