"""CV-Scope's wiring of the relationship engine (API process).

* ``prepare_run``      - at run start: resolve the experiment's rule versions,
                         open a live analysis and build the worker payload
* ``handle``           - batches from the worker: store them, publish the
                         relationships / correlated events whose rules ask for it
                         as ordinary run events (and webhooks), check patterns
* ``finish_run``       - the run ended: close the analysis, last pattern pass
* ``start_analysis``   - re-analyse a stored run (background thread); the new
                         analysis becomes current when it finishes, the old one
                         stays (history is never silently re-interpreted)
* ``ingest_sensor``    - an external sensor's observation, linked to the
                         relationships it corroborates or contradicts
* ``import_registry``  - externally supplied relations (authorized registry)
* maintenance          - retention sweeps; analyses interrupted by a restart
"""

from __future__ import annotations

import threading
import traceback
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from pathscope.db.models import Experiment, Run
from pathscope.db.session import get_session_factory
from pathscope.domain.scene import SceneDocument
from pathscope.logging_setup import get_logger
from pathscope.relationships import entities as E
from pathscope.relationships.access import RelationshipSettings, load_settings, plate_salt
from pathscope.relationships.confidence import Components, combine, state_for
from pathscope.relationships.models import (
    RelationAnalysis,
    RelationAudit,
    RelationCorrelated,
    RelationEntity,
    RelationObservation,
    RelationRelationship,
    RelationRule,
    RelationSupport,
)
from pathscope.relationships.observations import new_uid
from pathscope.relationships.rules import (
    CompiledRule,
    RelationExperimentSettings,
    RelationRuleDefinition,
    RuleRef,
    relation_settings,
)
from pathscope.relationships.spatial import Metric
from pathscope.relationships.store import dt, ensure_entities, store_payload

log = get_logger(__name__)


# ---------------------------------------------------------------------------- rules
def latest_rules(session: Session, include_archived: bool = False) -> list[RelationRule]:
    sub = select(RelationRule.key, func.max(RelationRule.version).label("v")).group_by(RelationRule.key).subquery()
    q = select(RelationRule).join(sub, (RelationRule.key == sub.c.key) & (RelationRule.version == sub.c.v))
    rows = list(session.scalars(q.order_by(RelationRule.name)))
    return rows if include_archived else [r for r in rows if not r.archived]


def resolve_rules(session: Session, refs: list[RuleRef]) -> tuple[list[CompiledRule], list[str]]:
    """The rule versions a run uses (a ref without a version takes the latest)."""
    out: list[CompiledRule] = []
    warnings: list[str] = []
    for ref in refs:
        q = select(RelationRule).where(RelationRule.key == ref.key)
        q = q.where(RelationRule.version == ref.version) if ref.version else q.order_by(RelationRule.version.desc())
        row = session.scalars(q.limit(1)).first()
        if row is None:
            warnings.append(f"relationship rule {ref.key}{f' v{ref.version}' if ref.version else ''} does not exist")
            continue
        if row.archived and not ref.version:
            warnings.append(f"relationship rule '{row.name}' is archived and was skipped")
            continue
        try:
            out.append(CompiledRule(key=row.key, version=row.version, definition=RelationRuleDefinition.model_validate(row.definition)))
        except ValueError as exc:
            warnings.append(f"relationship rule '{row.name}' v{row.version} is not valid any more: {exc}")
    return out, warnings


def effective_settings(exp: RelationExperimentSettings, rs: RelationshipSettings) -> tuple[RelationExperimentSettings, set[str]]:
    modules = {m for m, on in (("face", rs.modules.face), ("plate", rs.modules.plate)) if on}
    return exp, modules


# ---------------------------------------------------------------------------- events for the run
def _track_of(session: Session, entity_id: int | None) -> tuple[int, str]:
    if entity_id is None:
        return 0, ""
    e = session.get(RelationEntity, entity_id)
    if e is None or e.entity_type not in E.TRACK_TYPES:
        return 0, ""
    parsed = E.parse_track_ref(e.ref)
    return (parsed[1] if parsed else 0), (e.meta or {}).get("object_class", "")


def event_for_relationship(session: Session, row: RelationRelationship, spec: dict) -> dict:
    tid, cls = _track_of(session, row.subject_id)
    other, _ = _track_of(session, row.object_id)
    t = row.end_media_s if row.end_media_s is not None else (row.start_media_s or 0.0)
    wall = (row.end_at or row.start_at).timestamp()
    return {
        "track_id": tid, "object_class": cls or "", "event_type": "relationship", "label": spec.get("label") or row.relation_type,
        "frame_index": 0, "media_time_s": round(float(t), 3), "wall_time": wall, "rule_id": row.rule_key, "rule_name": row.rule_name,
        "route": None, "object_id": row.zone_id, "object_name": None, "direction": None,
        "entered_at_s": row.start_media_s, "completed_at_s": row.end_media_s,
        "duration_s": (row.end_media_s - row.start_media_s) if (row.end_media_s is not None and row.start_media_s is not None) else None,
        "avg_speed": None, "speed_unit": None, "confidence": round(row.confidence, 3),
        "context": {"relationship_id": row.id, "relation": row.relation_type, "state": row.state, "other_track_id": other or None, "rule_version": row.rule_version},
        "record": bool(spec.get("record", True)), "count": True, "webhooks": list(spec.get("webhooks") or []),
    }


def event_for_correlated(session: Session, row: RelationCorrelated, spec: dict | None, deviation: bool = False) -> dict:
    roles = row.roles or {}
    tid, cls = _track_of(session, roles.get("A") or roles.get("subject"))
    return {
        "track_id": tid, "object_class": cls or "", "event_type": "relation_deviation" if deviation else "correlated",
        "label": (spec or {}).get("label") or row.label, "frame_index": 0, "media_time_s": round(float(row.end_media_s or row.start_media_s or 0.0), 3),
        "wall_time": (row.end_at or row.start_at).timestamp(), "rule_id": row.rule_key, "rule_name": row.rule_name, "route": None, "object_id": None, "object_name": None,
        "direction": None, "entered_at_s": row.start_media_s, "completed_at_s": row.end_media_s, "duration_s": None, "avg_speed": None, "speed_unit": None,
        "confidence": round(row.confidence, 3),
        "context": {"correlated_id": row.id, "kind": row.kind, "state": row.state, "summary": row.description, "rule_version": row.rule_version},
        "record": bool((spec or {}).get("record", True)), "count": True, "webhooks": list((spec or {}).get("webhooks") or []),
    }


# ---------------------------------------------------------------------------- cross-camera hand-over
def _crosscam(run_id: int | None) -> None:
    """The run's graph changed as a whole: correlate it across cameras again."""
    try:
        from pathscope.crosscam.service import get_crosscam_service

        get_crosscam_service().enqueue(run_id)
    except Exception as exc:  # noqa: BLE001 - never blocks the relationship engine
        log.warning("cross-camera correlation not queued", run_id=run_id, error=str(exc)[:200])


def _crosscam_live(session: Session, run_id: int | None, rows: list[RelationRelationship]) -> None:
    """A live batch: correlate the identities it touched."""
    try:
        from pathscope.crosscam.engine import identity_map
        from pathscope.crosscam.service import get_crosscam_service

        tracks = {r.subject_id for r in rows if r.relation_type in ("IDENTIFIED_AS", "IDENTIFIED_BY_PLATE", "ENTERED", "EXITED", "CROSSED")}
        subjects = {x.subject_id for x in identity_map(session, tracks, "possible").values()}
        if subjects:
            get_crosscam_service().enqueue(run_id, subjects)
    except Exception as exc:  # noqa: BLE001
        log.warning("cross-camera correlation not queued", run_id=run_id, error=str(exc)[:200])


# ---------------------------------------------------------------------------- service
class RelationshipService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs: dict[int, dict] = {}

    # ------------------------------------------------------------ run start
    def prepare_run(self, session: Session, experiment: Experiment, run: Run, doc: SceneDocument, scene_version: int | None) -> tuple[dict | None, list[str]]:
        settings = relation_settings(experiment.relations)
        if not settings.enabled:
            return None, []
        rs = load_settings(session)
        rules, warnings = resolve_rules(session, settings.rules)
        settings, modules = effective_settings(settings, rs)
        metric = Metric(doc, doc.frame_width, doc.frame_height)
        for r in rules:
            d = r.definition
            if d.uses_distance and d.distance is not None and not metric.physical and d.distance.unit == "m" and d.distance.fallback_fw is None:
                warnings.append(f"'{d.name or r.key}' needs a calibrated camera (or a distance in frame widths) and will stay inactive")
        analysis = RelationAnalysis(
            run_id=run.id, experiment_id=experiment.id, camera_id=run.camera_id, source="live", status="running", current=True,
            rules=[{"key": r.key, "version": r.version, "name": r.definition.name, "kind": r.definition.kind} for r in rules],
            settings=settings.model_dump(), calibration={**metric.describe(), "scene_config_id": run.scene_config_id, "scene_version": scene_version}, stats={},
            created_by="run",
        )
        session.add(analysis)
        session.flush()
        payload = {
            "analysis_id": analysis.id, "settings": settings.model_dump(), "rules": [r.model_dump() for r in rules],
            "plate_salt": plate_salt().hex(), "modules": sorted(modules), "scene_version": scene_version, "warnings": warnings,
        }
        return payload, warnings

    # ------------------------------------------------------------ live batches
    def handle(self, handle, payload: dict, supervisor) -> None:
        cfg = handle.spec.relations or {}
        analysis_id = cfg.get("analysis_id")
        kind = payload.get("kind", "batch")
        Session = get_session_factory()
        with Session() as session:
            analysis = session.get(RelationAnalysis, analysis_id) if analysis_id else None
            if analysis is None:
                return
            if kind == "describe":
                analysis.stats = {**(analysis.stats or {}), "engine": payload.get("describe") or {}}
                session.commit()
                return
            if kind == "status":
                analysis.stats = {**(analysis.stats or {}), "live": payload.get("status") or {}}
                session.commit()
                return
            res = store_payload(session, analysis.id, analysis.run_id, analysis.experiment_id, analysis.camera_id, payload)
            session.commit()
            events = self._events_for(session, res.publish)
            settings = relation_settings(cfg.get("settings"))
            try:
                from pathscope.relationships import patterns

                devs = patterns.evaluate(session, analysis, settings, relationship_ids=res.relationship_ids)
                if devs:
                    dres = store_payload(session, analysis.id, analysis.run_id, analysis.experiment_id, analysis.camera_id, {"correlated": devs})
                    session.commit()
                    if settings.publish_deviations:
                        for row in dres.correlated:
                            row.published = True
                            events.append(event_for_correlated(session, row, None, deviation=True))
            except Exception as exc:  # noqa: BLE001 - patterns never block storage
                log.warning("relationship patterns failed", run_id=analysis.run_id, error=str(exc)[:300])
            session.commit()
            _crosscam_live(session, analysis.run_id, res.relationships)
        if events and supervisor is not None:
            supervisor.publish_events(handle, events)

    def _events_for(self, session: Session, publish: list) -> list[dict]:
        events = []
        for kind, spec, row in publish:
            if kind == "relationship":
                events.append(event_for_relationship(session, row, spec))
            else:
                row.published = True
                events.append(event_for_correlated(session, row, spec))
        return events

    def finish_run(self, run_id: int, handle=None, supervisor=None) -> None:
        Session = get_session_factory()
        with Session() as session:
            for analysis in session.scalars(select(RelationAnalysis).where(RelationAnalysis.run_id == run_id, RelationAnalysis.source == "live", RelationAnalysis.status == "running")):
                analysis.status = "done"
                analysis.finished_at = datetime.now(UTC)
                analysis.stats = {**(analysis.stats or {}), **self._counts(session, analysis.id)}
                session.commit()
                try:
                    from pathscope.relationships import patterns

                    settings = relation_settings(analysis.settings)
                    devs = patterns.evaluate(session, analysis, settings)
                    if devs:
                        dres = store_payload(session, analysis.id, analysis.run_id, analysis.experiment_id, analysis.camera_id, {"correlated": devs})
                        session.commit()
                        if settings.publish_deviations and dres.correlated:
                            events = []
                            for row in dres.correlated:
                                row.published = True
                                events.append(event_for_correlated(session, row, None, deviation=True))
                            session.commit()
                            if handle is not None and supervisor is not None:
                                supervisor.publish_events(handle, events)
                except Exception as exc:  # noqa: BLE001
                    log.warning("final relationship patterns failed", run_id=run_id, error=str(exc)[:300])
        _crosscam(run_id)

    @staticmethod
    def _counts(session: Session, analysis_id: int) -> dict:
        return {
            "relationships": session.scalar(select(func.count(RelationRelationship.id)).where(RelationRelationship.analysis_id == analysis_id)) or 0,
            "observations": session.scalar(select(func.count(RelationObservation.id)).where(RelationObservation.analysis_id == analysis_id)) or 0,
            "correlated": session.scalar(select(func.count(RelationCorrelated.id)).where(RelationCorrelated.analysis_id == analysis_id, RelationCorrelated.kind == "correlated")) or 0,
            "deviations": session.scalar(select(func.count(RelationCorrelated.id)).where(RelationCorrelated.analysis_id == analysis_id, RelationCorrelated.kind == "deviation")) or 0,
        }

    # ------------------------------------------------------------ re-analysis
    def start_analysis(self, session: Session, run: Run, refs: list[RuleRef] | None, created_by: str, settings_override: dict | None = None, wait: bool = False) -> RelationAnalysis:
        exp = session.get(Experiment, run.experiment_id)
        settings = relation_settings(settings_override if settings_override is not None else (exp.relations if exp else None))
        if refs is not None:
            settings = settings.model_copy(update={"rules": refs})
        rules, warnings = resolve_rules(session, settings.rules)
        rs = load_settings(session)
        settings, modules = effective_settings(settings, rs)
        analysis = RelationAnalysis(
            run_id=run.id, experiment_id=run.experiment_id, camera_id=run.camera_id, source="replay", status="running", current=False,
            rules=[{"key": r.key, "version": r.version, "name": r.definition.name, "kind": r.definition.kind} for r in rules],
            settings=settings.model_dump(), calibration={}, stats={"warnings": warnings}, created_by=created_by,
        )
        session.add(analysis)
        session.commit()
        aid = analysis.id
        with self._lock:
            self.jobs[aid] = {"progress": 0.0, "state": "running"}
        if wait:
            self._replay(aid, run.id, rules, settings, modules)
        else:
            threading.Thread(target=self._replay, args=(aid, run.id, rules, settings, modules), daemon=True, name=f"relations-replay-{aid}").start()
        session.refresh(analysis)
        return analysis

    def _replay(self, analysis_id: int, run_id: int, rules: list[CompiledRule], settings: RelationExperimentSettings, modules: set[str]) -> None:
        from pathscope.relationships import patterns
        from pathscope.relationships.replay import ReplayError, load_scene, replay

        Session = get_session_factory()
        with Session() as session:
            analysis = session.get(RelationAnalysis, analysis_id)
            run = session.get(Run, run_id)
            try:
                doc, sc = load_scene(session, run)
                if doc is not None:
                    m = Metric(doc, doc.frame_width, doc.frame_height)
                    analysis.calibration = {**m.describe(), "scene_config_id": run.scene_config_id, "scene_version": sc.version if sc else None}
                    session.commit()

                def on_payload(p: dict) -> None:
                    store_payload(session, analysis_id, run.id, run.experiment_id, run.camera_id, p)
                    session.commit()

                def progress(x: float) -> None:
                    with self._lock:
                        self.jobs[analysis_id]["progress"] = round(x, 3)

                info = replay(session, run, rules, settings, plate_salt(), modules, on_payload, progress)
                devs = patterns.evaluate(session, analysis, settings)
                if devs:
                    store_payload(session, analysis_id, run.id, run.experiment_id, run.camera_id, {"correlated": devs})
                analysis.status = "done"
                analysis.finished_at = datetime.now(UTC)
                analysis.stats = {**(analysis.stats or {}), **info, **self._counts(session, analysis_id)}
                # the new interpretation becomes current; the earlier ones stay available
                session.execute(update(RelationAnalysis).where(RelationAnalysis.run_id == run.id, RelationAnalysis.id != analysis_id).values(current=False))
                analysis.current = True
                session.commit()
                state = "done"
                _crosscam(run.id)
            except ReplayError as exc:
                session.rollback()
                analysis = session.get(RelationAnalysis, analysis_id)
                analysis.status, analysis.error, analysis.finished_at = "failed", str(exc), datetime.now(UTC)
                session.commit()
                state = "failed"
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                log.error("relationship analysis failed", analysis_id=analysis_id, error=str(exc), tb=traceback.format_exc())
                analysis = session.get(RelationAnalysis, analysis_id)
                analysis.status, analysis.error, analysis.finished_at = "failed", f"{type(exc).__name__}: {exc}", datetime.now(UTC)
                session.commit()
                state = "failed"
        with self._lock:
            self.jobs[analysis_id] = {"progress": 1.0, "state": state}

    def job(self, analysis_id: int) -> dict | None:
        with self._lock:
            return dict(self.jobs[analysis_id]) if analysis_id in self.jobs else None

    # ------------------------------------------------------------ sensors
    def ingest_sensor(self, session: Session, body: dict) -> dict:
        """Store a sensor observation and let it corroborate (or contradict) relationships."""
        run_id = body.get("run_id")
        run = session.get(Run, run_id) if run_id else None
        if run_id and run is None:
            raise ValueError(f"run {run_id} does not exist")
        sensor_id = str(body["sensor_id"])
        sensor_type = str(body.get("sensor_type") or "sensor")
        at = body.get("at")
        if at is None and body.get("media_time_s") is not None and run is not None:
            from pathscope.relationships.replay import wall_offset

            at = datetime.fromtimestamp(float(body["media_time_s"]) + wall_offset(session, run), tz=UTC)
        at = at or datetime.now(UTC)
        media_t = body.get("media_time_s")

        def entity_key(ref: dict | None) -> str | None:
            if not ref:
                return None
            if ref.get("key"):
                return str(ref["key"])
            if ref.get("track_id") is not None and run is not None:
                cls = ref.get("object_class")
                if not cls:
                    for t in ("person_track", "vehicle_track", "object_track"):
                        k = E.make_key(t, f"r{run.id}.t{int(ref['track_id'])}")
                        if session.scalar(select(RelationEntity.id).where(RelationEntity.key == k)) is not None:
                            return k
                    cls = "object"
                return E.track_key(run.id, int(ref["track_id"]), cls)
            if ref.get("object_id"):
                return E.place_key(run.camera_id if run else ref.get("camera_id"), str(ref["object_id"]), ref.get("object_type"))
            return None

        skey = E.sensor_key(sensor_id)
        subject = entity_key(body.get("subject")) or skey
        obj = entity_key(body.get("object"))
        ids = ensure_entities(session, [{"key": skey, "type": "sensor", "source": sensor_type, "label": f"{sensor_type.capitalize()} sensor {sensor_id}", "last_wall": at.timestamp(), "first_wall": at.timestamp()}],
                              {subject, *( [obj] if obj else [])}, {"camera_id": run.camera_id if run else None, "experiment_id": run.experiment_id if run else None})
        m = body.get("measurement") or {}
        o = RelationObservation(uid=new_uid(), analysis_id=None, run_id=run.id if run else None, camera_id=run.camera_id if run else None, entity_id=ids[subject],
                                object_entity_id=ids.get(obj) if obj else None, observation_type="sensor", media_time_s=media_t, at=at, source=sensor_type,
                                confidence=body.get("confidence"), value={"sensor_id": sensor_id, "kind": m.get("kind"), "value": m.get("value"), "unit": m.get("unit")})
        session.add(o)
        session.flush()
        touched = []
        if run is not None and subject != skey:
            touched = self._corroborate(session, o, ids[subject], ids.get(obj) if obj else None, m, sensor_type)
        session.commit()
        return {"observation_id": o.id, "uid": o.uid, "corroborated": touched}

    def _corroborate(self, session: Session, o: RelationObservation, subject_id: int, object_id: int | None, m: dict, sensor_type: str) -> list[dict]:
        R = RelationRelationship
        cur = select(RelationAnalysis.id).where(RelationAnalysis.current.is_(True))
        q = select(R).where(R.run_id == o.run_id, or_(R.analysis_id.is_(None), R.analysis_id.in_(cur)), or_(R.subject_id == subject_id, R.object_id == subject_id))
        at = o.at
        out = []
        for r in session.scalars(q):
            if object_id is not None and {r.subject_id, r.object_id} != {subject_id, object_id}:
                continue
            start = r.start_at - timedelta(seconds=1)
            end = (r.end_at or datetime.now(UTC)) + timedelta(seconds=1)
            if not (start <= at <= end):
                continue
            kind, value = m.get("kind"), m.get("value")
            agree: float | None = None
            note = ""
            if kind == "distance" and object_id is not None and value is not None:
                thr = (r.metrics or {}).get("threshold")
                if thr is not None and (r.metrics or {}).get("unit") == "m" and (m.get("unit") or "m") == "m":
                    agree = 1.0 if float(value) <= float(thr) * 1.1 else 0.3
                    note = f"{sensor_type} measured {float(value):.2f} m (threshold {float(thr):.2f} m)"
                else:
                    note = f"{sensor_type} distance not comparable (uncalibrated relationship)"
            elif kind == "presence":
                agree = 0.95 if value else 0.3
                note = f"{sensor_type} {'confirmed' if value else 'did not confirm'} presence"
            elif kind == "movement" and value is not None:
                moving = float(value) >= 0.2
                wants_moving = r.relation_type in ("TRAVELLED_WITH", "FOLLOWED", "APPROACHED", "MOVED_AWAY_FROM")
                wants_still = r.relation_type in ("STOPPED_NEAR", "PARKED_IN", "REMAINED_IN")
                if wants_moving or wants_still:
                    agree = 1.0 if moving == wants_moving else 0.4
                    note = f"{sensor_type} measured {float(value):.2f} m/s"
            session.add(RelationSupport(relationship_id=r.id, observation_id=o.id, role="sensor"))
            comp = dict(r.components or {})
            if agree is not None:
                prev = comp.get("sensor")
                comp["sensor"] = round(agree if prev is None else (prev + agree) / 2.0, 3)
                c = Components(**{k: comp.get(k) for k in ("tracking", "recognition", "spatial", "temporal", "sensor")}, support=int(comp.get("support") or 1))
                r.components = comp
                r.confidence = combine(c)
                r.state = state_for(r.confidence)
            r.sources = sorted(set(r.sources or []) | {sensor_type})
            r.metrics = {**(r.metrics or {}), "sensor_notes": [*((r.metrics or {}).get("sensor_notes") or []), note][-10:]}
            out.append({"relationship_id": r.id, "type": r.relation_type, "state": r.state, "confidence": r.confidence, "agrees": agree is None or agree >= 0.9, "note": note})
        return out

    # ------------------------------------------------------------ external registry
    def import_registry(self, session: Session, items: list[dict], source: str, actor: str) -> list[int]:
        from pathscope.relationships.relations import relation_type

        out = []
        for it in items:
            rt = relation_type(str(it["relation"]).upper())
            if rt is None:
                raise ValueError(f"unknown relationship type {it['relation']} (define it under Relationship settings first)")
            subj, obj = str(it["subject"]), str(it["object"])
            ids = ensure_entities(session, [], {subj, obj}, {})
            start = it.get("valid_from") or datetime.now(UTC)
            row = RelationRelationship(
                uid=new_uid(), analysis_id=None, subject_id=ids[subj], relation_type=rt.id, object_id=ids[obj], start_at=start, end_at=it.get("valid_to"),
                status="closed" if it.get("valid_to") else "open", confidence=1.0, state="confirmed", components={"support": 1}, rule_key=f"registry:{source}"[:60],
                rule_version=1, rule_name=f"Imported from {source}", reason=f"Supplied by the authorized registry '{source}' (imported by {actor}); not inferred from observation.",
                sources=["registry"], calibration={"mode": "registry"}, metrics={"registry": source},
            )
            session.add(row)
            session.flush()
            out.append(row.id)
        session.commit()
        return out

    # ------------------------------------------------------------ deletion and retention
    @staticmethod
    def delete_orphans(session: Session) -> int:
        """Entities nothing refers to any more (tracks of deleted runs, identities past retention)."""
        R, Ob = RelationRelationship, RelationObservation
        used = select(R.subject_id).union(select(R.object_id), select(Ob.entity_id), select(Ob.object_entity_id).where(Ob.object_entity_id.is_not(None)))
        places = ("zone", "gate", "route", "location", "camera", "experiment", "sensor")
        res = session.execute(delete(RelationEntity).where(RelationEntity.id.not_in(used), RelationEntity.entity_type.not_in(places)))
        return int(res.rowcount or 0)

    def sweep(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        out = {"relationships": 0, "observations": 0, "correlated": 0, "identity_links": 0, "entities": 0, "audit": 0}
        Session = get_session_factory()
        with Session() as session:
            rs = load_settings(session)
            ret = rs.retention
            if ret.days > 0:
                cutoff = now - timedelta(days=ret.days)
                out["correlated"] = int(session.execute(delete(RelationCorrelated).where(RelationCorrelated.start_at < cutoff)).rowcount or 0)
                out["relationships"] = int(session.execute(delete(RelationRelationship).where(RelationRelationship.start_at < cutoff, RelationRelationship.analysis_id.is_not(None))).rowcount or 0)
                out["observations"] = int(session.execute(delete(RelationObservation).where(RelationObservation.at < cutoff)).rowcount or 0)
            if ret.identity_days > 0:
                cutoff = now - timedelta(days=ret.identity_days)
                ident_types = ("IDENTIFIED_AS", "IDENTIFIED_BY_PLATE", "REGISTERED_AS")
                out["identity_links"] = int(session.execute(delete(RelationRelationship).where(RelationRelationship.relation_type.in_(ident_types), RelationRelationship.start_at < cutoff)).rowcount or 0)
                session.execute(delete(RelationObservation).where(RelationObservation.observation_type.in_(("recognized", "possible_match", "plate_read", "registered_vehicle")), RelationObservation.at < cutoff))
                # deviations and correlated events that name an identity go with it
                for c in session.scalars(select(RelationCorrelated).where(RelationCorrelated.start_at < cutoff)):
                    if "identity" in (c.roles or {}):
                        session.delete(c)
            # cross-camera transitions follow the same periods (identity-based ones: the identity period)
            from pathscope.location.models import CrossCameraTransition as T

            if ret.days > 0:
                out["transitions"] = int(session.execute(delete(T).where(T.arrived_at < now - timedelta(days=ret.days))).rowcount or 0)
            if ret.identity_days > 0:
                out["transitions"] = out.get("transitions", 0) + int(session.execute(delete(T).where(T.basis != "anonymous", T.arrived_at < now - timedelta(days=ret.identity_days))).rowcount or 0)
                session.execute(delete(RelationRelationship).where(RelationRelationship.rule_key == "crosscam", RelationRelationship.start_at < now - timedelta(days=ret.identity_days),
                                                                   RelationRelationship.relation_type != "CONTINUED_AS"))
            # no dangling support links, no entities without facts
            session.execute(delete(RelationSupport).where(RelationSupport.relationship_id.is_(None), RelationSupport.correlated_id.is_(None)))
            out["entities"] = self.delete_orphans(session)
            if ret.audit_days > 0:
                out["audit"] = int(session.execute(delete(RelationAudit).where(RelationAudit.at < now - timedelta(days=ret.audit_days))).rowcount or 0)
            if any(out.values()):
                session.add(RelationAudit(actor="system", actor_role="system", action="retention_sweep", detail=out))
            session.commit()
        return out

    @staticmethod
    def recover() -> int:
        """Live analyses of runs that stopped with the server; replays interrupted by a restart."""
        from pathscope.workers.supervisor import get_supervisor

        Session = get_session_factory()
        n = 0
        with Session() as session:
            active = {h.run_id for h in get_supervisor().active()}
            for a in session.scalars(select(RelationAnalysis).where(RelationAnalysis.status == "running")):
                if a.source == "live" and a.run_id in active:
                    continue
                a.status = "done" if a.source == "live" else "failed"
                a.error = a.error or ("CV-Scope stopped while this run was being analysed." if a.source == "live" else "CV-Scope restarted during the analysis.")
                a.finished_at = a.finished_at or datetime.now(UTC)
                n += 1
            session.commit()
        return n


_service: RelationshipService | None = None


def get_relationship_service() -> RelationshipService:
    global _service
    if _service is None:
        _service = RelationshipService()
    return _service


_stop = threading.Event()
_thread: threading.Thread | None = None


def start_maintenance(interval_s: float = 3600.0, first_delay_s: float = 120.0) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    try:
        from pathscope.relationships.relations import load_custom_types

        Session = get_session_factory()
        with Session() as session:
            load_custom_types([t.model_dump() for t in load_settings(session).custom_types])
        RelationshipService.recover()
    except Exception as exc:  # noqa: BLE001
        log.warning("relationship recovery failed", error=str(exc)[:200])

    def _loop() -> None:
        if _stop.wait(first_delay_s):
            return
        while True:
            try:
                get_relationship_service().sweep()
            except Exception as exc:  # noqa: BLE001
                log.warning("relationship retention sweep failed", error=str(exc)[:200])
            if _stop.wait(interval_s):
                return

    _thread = threading.Thread(target=_loop, name="relationship-maintenance", daemon=True)
    _thread.start()


def stop_maintenance() -> None:
    _stop.set()


_ = dt
