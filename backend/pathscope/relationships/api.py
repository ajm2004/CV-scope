"""HTTP API of the relationship engine: ``/api/relationships``.

Reads go through the graph API and the presenter, so every answer is what
the asking viewer may see (``access.py``). Entity keys contain ':' and are
passed as the ``key`` query parameter.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.db.models import Experiment, Run
from pathscope.relationships import entities as E
from pathscope.relationships.access import (
    CustomType,
    RelationshipSettings,
    Viewer,
    audit,
    audit_rows,
    can_change_settings,
    graph_viewer,
    load_settings,
    save_settings,
    viewer_dep,
)
from pathscope.relationships.confidence import STATE_LABELS, STATES, THRESHOLDS
from pathscope.relationships.graph import (
    ASSOCIATION_TYPES,
    Filters,
    Presenter,
    SqlGraph,
    parse_filters,
)
from pathscope.relationships.models import (
    RelationAnalysis,
    RelationCorrelated,
    RelationEntity,
    RelationObservation,
    RelationRelationship,
    RelationRule,
)
from pathscope.relationships.observations import observation_types
from pathscope.relationships.relations import relation_types
from pathscope.relationships.rules import (
    RelationRuleDefinition,
    RuleRef,
    relation_settings,
    templates,
)
from pathscope.relationships.service import _crosscam, get_relationship_service, latest_rules
from pathscope.relationships.summary import compose, reword

router = APIRouter(prefix="/relationships", tags=["relationships"])

PERSON_TYPES = {"person_track", "recognized_person"}
VEHICLE_TYPES = {"vehicle_track", "registered_vehicle", "license_plate"}


def filters_dep(
    types: str | None = Query(default=None, description="Comma-separated relationship types"),
    time_from: datetime | None = None, time_to: datetime | None = None, camera_id: int | None = None, experiment_id: int | None = None,
    run_id: int | None = None, zone_id: str | None = None, min_state: str = "possible", analysis_id: int | None = None,
    include_superseded: bool = False, last_hours: float | None = Query(default=None, gt=0),
    location_id: int | None = Query(default=None, description="A node of the location model: only its cameras"),
) -> Filters:
    cams = None
    if location_id is not None:
        from pathscope.db.session import get_session_factory
        from pathscope.location.topology import LocationGraph

        with get_session_factory()() as s:
            g = LocationGraph.load(s)
        if location_id not in g.nodes:
            raise HTTPException(404, "No such location.")
        cams = g.cameras_in(location_id)
    return parse_filters(types, time_from, time_to, camera_id, experiment_id, run_id, zone_id, min_state, analysis_id, include_superseded, last_hours, cams)


def _entity(session: Session, key: str, viewer: Viewer, presenter: Presenter) -> RelationEntity:
    e = SqlGraph(session).entity(key)
    if e is None:
        raise HTTPException(404, "No such entity.")
    if not presenter.visible(e):
        viewer.require("identity")
        raise HTTPException(403, "This identity is hidden by the relationship settings (module switched off).")
    return e


def _audit_identity(session: Session, viewer: Viewer, e: RelationEntity, what: str) -> None:
    if e.entity_type in E.IDENTITY_TYPES:
        audit(session, viewer, "identity_viewed", e.entity_type, e.id, {"view": what})
        session.commit()


# ---------------------------------------------------------------------------- meta and settings
@router.get("/meta")
def meta(viewer: Viewer = Depends(viewer_dep)) -> dict:
    return {
        "entity_types": [t.to_dict() for t in E.entity_types()],
        "relation_types": [t.to_dict() for t in relation_types()],
        "observation_types": [{"id": t.id, "label": t.label, "description": t.description} for t in observation_types()],
        "states": [{"id": s, "label": STATE_LABELS[s], "min": THRESHOLDS.get(s, 0.0)} for s in reversed(STATES)],
        "templates": templates(),
        "viewer": viewer.to_dict(),
    }


@router.get("/settings")
def get_settings_(viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    return {"settings": load_settings(session).model_dump(), "viewer": viewer.to_dict()}


@router.put("/settings")
def put_settings(body: RelationshipSettings, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    can_change_settings(session, viewer)
    before = load_settings(session).model_dump()
    try:
        save_settings(session, body)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    changed = {k: v for k, v in body.model_dump().items() if before.get(k) != v}
    audit(session, viewer, "settings_changed", "settings", None, {"changed": sorted(changed)})
    session.commit()
    return {"settings": body.model_dump(), "viewer": viewer.to_dict()}


@router.get("/audit")
def get_audit(limit: int = Query(default=200, le=1000), offset: int = 0, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> list[dict]:
    can_change_settings(session, viewer)
    return audit_rows(session, limit, offset)


# ---------------------------------------------------------------------------- rules (versioned)
class RuleIn(BaseModel):
    definition: RelationRuleDefinition
    note: str = Field(default="", max_length=2000)


def _rule_out(r: RelationRule, versions: int | None = None, usage: list[dict] | None = None) -> dict:
    try:
        summary = RelationRuleDefinition.model_validate(r.definition).summary()
    except ValueError:
        summary = "(no longer valid)"
    return {"key": r.key, "version": r.version, "name": r.name, "kind": r.kind, "definition": r.definition, "summary": summary, "note": r.note,
            "created_by": r.created_by, "created_at": r.created_at, "archived": r.archived, "versions": versions, "used_by": usage}


def _usage(session: Session) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in session.scalars(select(Experiment)):
        s = relation_settings(e.relations)
        for ref in s.rules:
            out.setdefault(ref.key, []).append({"experiment_id": e.id, "name": e.name, "version": ref.version, "enabled": s.enabled})
    return out


@router.get("/templates")
def get_templates() -> list[dict]:
    return templates()


@router.post("/rules/validate")
def validate_rule(body: dict) -> dict:
    try:
        d = RelationRuleDefinition.model_validate(body.get("definition", body))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"ok": True, "definition": d.model_dump(), "summary": d.summary()}


@router.get("/rules")
def list_rules(archived: bool = False, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> list[dict]:
    counts = dict(session.execute(select(RelationRule.key, func.count(RelationRule.id)).group_by(RelationRule.key)).all())
    usage = _usage(session)
    return [_rule_out(r, counts.get(r.key), usage.get(r.key, [])) for r in latest_rules(session, include_archived=archived) if archived or not r.archived]


@router.post("/rules", status_code=201)
def create_rule(body: RuleIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    from pathscope.relationships.rules import new_rule_key

    d = body.definition
    row = RelationRule(key=new_rule_key(), version=1, name=d.name or d.summary()[:200], kind=d.kind, definition=d.model_dump(), note=body.note, created_by=viewer.name)
    session.add(row)
    session.flush()
    audit(session, viewer, "rule_created", "rule", row.key, {"version": 1, "name": row.name})
    session.commit()
    return _rule_out(row, 1, [])


@router.get("/rules/{key}")
def get_rule(key: str, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> dict:
    rows = list(session.scalars(select(RelationRule).where(RelationRule.key == key).order_by(RelationRule.version.desc())))
    if not rows:
        raise HTTPException(404, "No such rule.")
    return {"latest": _rule_out(rows[0], len(rows), _usage(session).get(key, [])), "versions": [_rule_out(r) for r in rows]}


@router.put("/rules/{key}")
def new_rule_version(key: str, body: RuleIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """Editing never changes a stored version: it stores the next one."""
    viewer.require("rules")
    last = session.scalars(select(RelationRule).where(RelationRule.key == key).order_by(RelationRule.version.desc()).limit(1)).first()
    if last is None:
        raise HTTPException(404, "No such rule.")
    d = body.definition
    if d.model_dump() == last.definition:
        raise HTTPException(409, f"Nothing changed: the definition is the same as version {last.version}.")
    row = RelationRule(key=key, version=last.version + 1, name=d.name or last.name, kind=d.kind, definition=d.model_dump(), note=body.note, created_by=viewer.name, archived=last.archived)
    session.add(row)
    session.flush()
    audit(session, viewer, "rule_versioned", "rule", key, {"version": row.version, "previous": last.version, "note": body.note})
    session.commit()
    return _rule_out(row, row.version, _usage(session).get(key, []))


@router.post("/rules/{key}/archive")
def archive_rule(key: str, archived: bool = True, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    rows = list(session.scalars(select(RelationRule).where(RelationRule.key == key)))
    if not rows:
        raise HTTPException(404, "No such rule.")
    for r in rows:
        r.archived = archived
    audit(session, viewer, "rule_archived" if archived else "rule_restored", "rule", key)
    session.commit()
    return {"key": key, "archived": archived}


# ---------------------------------------------------------------------------- analyses
def _analysis_out(a: RelationAnalysis) -> dict:
    return {"id": a.id, "run_id": a.run_id, "experiment_id": a.experiment_id, "camera_id": a.camera_id, "source": a.source, "status": a.status, "current": a.current,
            "rules": a.rules or [], "settings": a.settings or {}, "calibration": a.calibration or {}, "stats": a.stats or {}, "error": a.error,
            "created_by": a.created_by, "started_at": a.started_at, "finished_at": a.finished_at, "job": get_relationship_service().job(a.id)}


@router.get("/analyses")
def list_analyses(run_id: int | None = None, experiment_id: int | None = None, limit: int = Query(default=100, le=1000), session: Session = Depends(db_session),
                  viewer: Viewer = Depends(graph_viewer)) -> list[dict]:
    q = select(RelationAnalysis)
    if run_id is not None:
        q = q.where(RelationAnalysis.run_id == run_id)
    if experiment_id is not None:
        q = q.where(RelationAnalysis.experiment_id == experiment_id)
    return [_analysis_out(a) for a in session.scalars(q.order_by(RelationAnalysis.id.desc()).limit(limit))]


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: int, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> dict:
    return _analysis_out(get_or_404(session, RelationAnalysis, analysis_id, "Analysis"))


class AnalyseIn(BaseModel):
    rules: list[RuleRef] | None = Field(default=None, description="None = the experiment's rules (latest versions unless pinned)")
    settings: dict | None = None


@router.post("/runs/{run_id}/analyse", status_code=202)
def analyse_run(run_id: int, body: AnalyseIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    run = get_or_404(session, Run, run_id, "Run")
    from pathscope.workers.supervisor import get_supervisor

    h = get_supervisor().get(run_id)
    if h is not None and not h.finished:
        raise HTTPException(409, "The run is still active; analyse it again once it has ended.")
    a = get_relationship_service().start_analysis(session, run, body.rules, viewer.name, body.settings)
    audit(session, viewer, "analysis_started", "run", run_id, {"analysis_id": a.id, "rules": a.rules})
    session.commit()
    return _analysis_out(a)


@router.post("/analyses/{analysis_id}/current")
def make_current(analysis_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    a = get_or_404(session, RelationAnalysis, analysis_id, "Analysis")
    if a.status != "done":
        raise HTTPException(409, "Only a finished analysis can become the current interpretation.")
    for other in session.scalars(select(RelationAnalysis).where(RelationAnalysis.run_id == a.run_id)):
        other.current = other.id == a.id
    audit(session, viewer, "analysis_current", "analysis", a.id, {"run_id": a.run_id})
    session.commit()
    _crosscam(a.run_id)
    return _analysis_out(a)


@router.delete("/analyses/{analysis_id}", status_code=204)
def delete_analysis(analysis_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    viewer.require("delete")
    a = get_or_404(session, RelationAnalysis, analysis_id, "Analysis")
    if a.status == "running":
        raise HTTPException(409, "The analysis is still running.")
    run_id, was_current = a.run_id, a.current
    session.delete(a)
    session.flush()
    if was_current:
        nxt = session.scalars(select(RelationAnalysis).where(RelationAnalysis.run_id == run_id, RelationAnalysis.status == "done").order_by(RelationAnalysis.id.desc()).limit(1)).first()
        if nxt is not None:
            nxt.current = True
    get_relationship_service().delete_orphans(session)
    audit(session, viewer, "analysis_deleted", "analysis", analysis_id, {"run_id": run_id})
    session.commit()
    _crosscam(run_id)
    return Response(status_code=204)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run_data(run_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    viewer.require("delete")
    session.execute(delete(RelationAnalysis).where(RelationAnalysis.run_id == run_id, RelationAnalysis.status != "running"))
    session.execute(delete(RelationObservation).where(RelationObservation.run_id == run_id, RelationObservation.analysis_id.is_(None)))
    get_relationship_service().delete_orphans(session)
    audit(session, viewer, "data_deleted", "run", run_id)
    session.commit()
    _crosscam(run_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------- entities and graph
@router.get("/entities")
def list_entities(type: str | None = None, q: str | None = None, run_id: int | None = None, experiment_id: int | None = None, camera_id: int | None = None,
                  limit: int = Query(default=100, le=1000), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> list[dict]:
    p = Presenter(session, viewer)
    qry = select(RelationEntity)
    if type:
        qry = qry.where(RelationEntity.entity_type.in_([t.strip() for t in type.split(",") if t.strip()]))
    if not p.identities:
        qry = qry.where(RelationEntity.entity_type.not_in(list(E.IDENTITY_TYPES)))
    if run_id is not None:
        qry = qry.where(RelationEntity.run_id == run_id)
    if experiment_id is not None:
        qry = qry.where(RelationEntity.experiment_id == experiment_id)
    if camera_id is not None:
        qry = qry.where(RelationEntity.camera_id == camera_id)
    rows = list(session.scalars(qry.order_by(RelationEntity.last_seen.desc().nulls_last(), RelationEntity.id.desc()).limit(limit * 5 if q else limit)))
    ents = {e.id: e for e in rows}
    p.load_names(ents)
    out = [p.entity(e) for e in rows if p.visible(e)]
    if q:
        needle = q.lower()
        out = [e for e in out if needle in (e["label"] or "").lower() or needle in (e["key"] or "").lower()][:limit]
    return out


@router.get("/entity")
def get_entity(key: str, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p)
    p.load_names({e.id: e})
    _audit_identity(session, viewer, e, "entity")
    return p.entity(e)


@router.get("/entity/neighbors")
def neighbors(key: str, f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p)
    _audit_identity(session, viewer, e, "neighbors")
    return p.neighbors(e, f)


@router.get("/entity/graph")
def graph(key: str, depth: int = Query(default=1, ge=1, le=2), f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p)
    _audit_identity(session, viewer, e, "graph")
    return p.subgraph(e, f, depth)


@router.get("/entity/history")
def history(key: str, f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p)
    _audit_identity(session, viewer, e, "history")
    f.min_state = f.min_state if f.min_state != "possible" else "likely"
    return p.history(e, f)


@router.get("/visual")
def visual(key: str | None = None, depth: int = Query(default=1, ge=1, le=3), project: bool = True, context: bool = True, max_edges: int = Query(default=600, ge=10, le=3000),
           f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """The interactive graph: around an entity, or everything in a run, experiment, time range or location.
    Built from the stored relationships on each request (the graph is a view, not a store)."""
    from pathscope.relationships.visual import VisualGraph

    p = Presenter(session, viewer)
    vg = VisualGraph(session, p)
    if key:
        e = _entity(session, key, viewer, p)
        _audit_identity(session, viewer, e, "visual_graph")
        return vg.around(e, f, depth, max_edges, project, context)
    if f.run_id is None and f.experiment_id is None and f.time_from is None and f.camera_ids is None and f.camera_id is None:
        raise HTTPException(422, "Choose an entity, a run, an experiment, a location or a time range.")
    return vg.scope(f, max_edges, project, context)


@router.get("/visual/path")
def visual_path(from_key: str, to_key: str, max_depth: int = Query(default=4, ge=1, le=6), project: bool = True, f: Filters = Depends(filters_dep),
                viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """The shortest chain of relationships connecting two entities."""
    from pathscope.relationships.visual import VisualGraph

    p = Presenter(session, viewer)
    a = _entity(session, from_key, viewer, p)
    b = _entity(session, to_key, viewer, p)
    for e in (a, b):
        _audit_identity(session, viewer, e, "path")
    return VisualGraph(session, p).path(a, b, f, max_depth, project)


# ---------------------------------------------------------------------------- relationships and correlated events
@router.get("/list")
def list_relationships(f: Filters = Depends(filters_dep), subject_type: str | None = None, object_type: str | None = None, limit: int = Query(default=200, le=2000),
                       offset: int = 0, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    g = p.g
    rels = g.relationships(f, None, limit=limit * 3 if (subject_type or object_type) else limit, offset=offset)
    ents = g.entities({x for r in rels for x in (r.subject_id, r.object_id)})
    if subject_type:
        rels = [r for r in rels if ents.get(r.subject_id) is not None and ents[r.subject_id].entity_type in subject_type.split(",")]
    if object_type:
        rels = [r for r in rels if ents.get(r.object_id) is not None and ents[r.object_id].entity_type in object_type.split(",")]
    rels = rels[:limit]
    lifted = g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if p.identities else {}
    ents.update(g.entities(set(lifted.values()) - set(ents)))
    p.load_names(ents)
    return {"items": [p.relationship(r, ents, lifted) for r in rels], "count": len(rels)}


@router.get("/relationship/{rel_id}")
def relationship_detail(rel_id: int, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """Why the relationship exists: rule version, reason, measurements, calibration, confidence, evidence."""
    p = Presenter(session, viewer)
    r = get_or_404(session, RelationRelationship, rel_id, "Relationship")
    obs, sup = p.g.support(relationship_id=r.id)
    cited_rels, cited_cors = p.g.cited_by(r.id)
    ids = {r.subject_id, r.object_id} | {o.entity_id for o in obs} | {o.object_entity_id for o in obs if o.object_entity_id} | {x for s in sup + cited_rels for x in (s.subject_id, s.object_id)}
    ents = p.g.entities(ids)
    lifted = p.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if p.identities else {}
    ents.update(p.g.entities(set(lifted.values()) - set(ents)))
    p.load_names(ents)
    out = p.relationship(r, ents, lifted)
    if (out["subject"] or {}).get("redacted") and (out["object"] or {}).get("redacted"):
        viewer.require("identity")
    rule = session.scalar(select(RelationRule).where(RelationRule.key == r.rule_key, RelationRule.version == r.rule_version))
    analysis = session.get(RelationAnalysis, r.analysis_id) if r.analysis_id else None
    out.update({
        "evidence": {
            "observations": [p.observation(o, ents) for o in obs],
            "relationships": [p.relationship(s, ents, lifted) for s in sup],
        },
        "cited_by": {"relationships": [p.relationship(s, ents, lifted) for s in cited_rels], "correlated": [p.correlated(c, ents) for c in cited_cors]},
        "rule_definition": rule.definition if rule else None, "rule_summary": _rule_out(rule)["summary"] if rule else None,
        "analysis": {"id": analysis.id, "source": analysis.source, "current": analysis.current, "status": analysis.status} if analysis else None,
    })
    return out


@router.get("/correlated")
def list_correlated(f: Filters = Depends(filters_dep), kind: str | None = None, limit: int = Query(default=200, le=2000), viewer: Viewer = Depends(graph_viewer),
                    session: Session = Depends(db_session)) -> list[dict]:
    p = Presenter(session, viewer)
    rows = p.g.correlated(f, None, limit=limit)
    if kind:
        rows = [c for c in rows if c.kind == kind]
    ents = p.g.entities({x for c in rows for x in (c.roles or {}).values()})
    p.load_names(ents)
    return [p.correlated(c, ents) for c in rows]


@router.get("/correlated/{cor_id}")
def correlated_detail(cor_id: int, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    c = get_or_404(session, RelationCorrelated, cor_id, "Correlated event")
    obs, sup = p.g.support(correlated_id=c.id)
    ids = set((c.roles or {}).values()) | {o.entity_id for o in obs} | {o.object_entity_id for o in obs if o.object_entity_id} | {x for s in sup for x in (s.subject_id, s.object_id)}
    ents = p.g.entities(ids)
    lifted = p.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if p.identities else {}
    ents.update(p.g.entities(set(lifted.values()) - set(ents)))
    p.load_names(ents)
    rule = session.scalar(select(RelationRule).where(RelationRule.key == c.rule_key, RelationRule.version == c.rule_version))
    return {**p.correlated(c, ents), "evidence": {"observations": [p.observation(o, ents) for o in obs], "relationships": [p.relationship(s, ents, lifted) for s in sup]},
            "rule_definition": rule.definition if rule else None}


# ---------------------------------------------------------------------------- timeline, summary, search
@router.get("/timeline")
def timeline(key: str | None = None, f: Filters = Depends(filters_dep), limit: int = Query(default=1500, le=10000), viewer: Viewer = Depends(graph_viewer),
             session: Session = Depends(db_session)) -> dict:
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p) if key else None
    if e is not None:
        _audit_identity(session, viewer, e, "timeline")
    if e is None and f.run_id is None and f.experiment_id is None and f.time_from is None and f.camera_ids is None:
        raise HTTPException(422, "Choose a run, an experiment, an entity, a location or a time range.")
    return {"items": p.timeline(f, e, limit), "entity": p.entity(e) if e else None}


class SummaryIn(BaseModel):
    key: str | None = None
    run_id: int | None = None
    experiment_id: int | None = None
    camera_id: int | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    min_state: str = "likely"
    tz_offset_min: int = Field(default=0, ge=-900, le=900, description="Minutes to add to UTC for the clock times")
    llm: bool = False


@router.post("/summary")
def summary(body: SummaryIn, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    f = Filters(time_from=body.time_from, time_to=body.time_to, camera_id=body.camera_id, experiment_id=body.experiment_id, run_id=body.run_id, min_state=body.min_state)
    p = Presenter(session, viewer)
    e = _entity(session, body.key, viewer, p) if body.key else None
    if e is None and f.run_id is None and f.experiment_id is None and f.time_from is None:
        raise HTTPException(422, "Choose a run, an experiment, an entity or a time range.")
    run = session.get(Run, body.run_id) if body.run_id else None
    media = run is not None and (run.snapshot or {}).get("source_type") == "file"
    out = {"deterministic": compose(p.timeline(f, e), body.tz_offset_min, media_time=media), "model": None}
    if body.llm:
        rs = load_settings(session)
        if not rs.llm_summaries:
            raise HTTPException(403, "Model-written summaries are off (Relationship settings).")
        if e is not None and e.entity_type in E.IDENTITY_TYPES:
            raise HTTPException(422, "Model-written summaries are available for runs and places only, never for an identity.")
        from pathscope.anomaly.llm.client import LLMError
        from pathscope.anomaly.llm.settings import load_settings as load_llm
        from pathscope.anomaly.service import key_store
        from pathscope.relationships.access import Viewer as V

        # the model sees the anonymous text only: no names, no plates
        anon = Presenter(session, V("model", "none", rs.model_copy(update={"access": rs.access.model_copy(update={"identity_role": "admin"})})))
        text = compose(anon.timeline(f, e), body.tz_offset_min, media_time=media)["text"]
        llm = load_llm(session)
        key, _ = key_store().get(llm.provider)
        try:
            out["model"] = {**reword(text, llm, key), "based_on": text}
        except LLMError as exc:
            raise HTTPException(422, str(exc)) from exc
        audit(session, viewer, "summary_model", "summary", None, {"provider": llm.provider, "model": llm.resolved_model, "facts": text.count("\n") + 1})
        session.commit()
    return out


@router.get("/search")
def search(kind: Literal["events", "associated", "near", "entered_after", "routes", "correlated"], key: str | None = None, target: Literal["any", "person", "vehicle"] = "any",
           zone_key: str | None = None, window_s: float = Query(default=600.0, gt=0, le=86400 * 7), f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer),
           session: Session = Depends(db_session)) -> dict:
    """Structured questions: events involving X, entities associated with / near X,
    entities that entered a zone after X arrived, route use, correlated events."""
    p = Presenter(session, viewer)
    e = _entity(session, key, viewer, p) if key else None
    if e is not None:
        _audit_identity(session, viewer, e, f"search:{kind}")
    if kind in ("events", "associated", "near", "entered_after") and e is None:
        raise HTTPException(422, "This search needs an entity.")
    if kind == "events":
        return {"kind": kind, "entity": p.entity(e), "items": p.timeline(f, e)}
    if kind in ("associated", "near"):
        f.types = list(ASSOCIATION_TYPES) if kind == "associated" else ["NEAR", "APPROACHED", "STOPPED_NEAR", "ASSOCIATED_WITH", "TRAVELLED_WITH"]
        res = p.neighbors(e, f)
        want = PERSON_TYPES if target == "person" else VEHICLE_TYPES if target == "vehicle" else None
        related = [g for g in res["related"] if want is None or g["entity"]["type"] in want]
        return {"kind": kind, "entity": res["entity"], "items": related}
    if kind == "entered_after":
        if not zone_key:
            raise HTTPException(422, "Choose the zone.")
        zone = _entity(session, zone_key, viewer, p)
        ids, _al = p._scope(e)
        arrivals = [o.at for o in p.g.observations(f, ids) if o.observation_type in ("appeared", "entered") and o.entity_id in ids]
        if not arrivals:
            return {"kind": kind, "entity": p.entity(e), "zone": p.entity(zone), "items": [], "arrivals": []}
        entries = p.g.relationships(Filters(types=["ENTERED"], camera_id=f.camera_id, experiment_id=f.experiment_id, run_id=f.run_id, min_state=f.min_state), {zone.id}, limit=5000)
        ents = p.g.entities({r.subject_id for r in entries})
        lifted = p.g.identities_of(set(ents)) if p.identities else {}
        ents.update(p.g.entities(set(lifted.values()) - set(ents)))
        p.load_names(ents)
        items = []
        for r in entries:
            if r.subject_id in ids:
                continue
            before = [a for a in arrivals if a <= r.start_at and (r.start_at - a).total_seconds() <= window_s]
            if not before:
                continue
            a = max(before)
            items.append({"entity": p.entity(ents.get(r.subject_id), ents.get(lifted.get(r.subject_id, -1))), "at": r.start_at, "after_s": round((r.start_at - a).total_seconds(), 1),
                          "relationship_id": r.id, "run_id": r.run_id, "media_time_s": r.start_media_s})
        return {"kind": kind, "entity": p.entity(e), "zone": p.entity(zone), "arrivals": sorted(arrivals), "items": items}
    if kind == "routes":
        f.types = ["USED_ROUTE"]
        rels = p.g.relationships(f, {e.id} if e is not None else None, limit=5000)
        ents = p.g.entities({x for r in rels for x in (r.subject_id, r.object_id)})
        lifted = p.g.identities_of({i for i, x in ents.items() if x.entity_type in E.TRACK_TYPES}) if p.identities else {}
        ents.update(p.g.entities(set(lifted.values()) - set(ents)))
        p.load_names(ents)
        by_route: dict[int, dict] = {}
        for r in rels:
            g = by_route.setdefault(r.object_id, {"route": p.entity(ents.get(r.object_id)), "count": 0, "items": []})
            g["count"] += 1
            if len(g["items"]) < 200:
                g["items"].append(p.relationship(r, ents, lifted))
        return {"kind": kind, "items": sorted(by_route.values(), key=lambda g: -g["count"])}
    rows = p.g.correlated(f, {e.id} if e is not None else None)
    ents = p.g.entities({x for c in rows for x in (c.roles or {}).values()})
    p.load_names(ents)
    return {"kind": kind, "items": [p.correlated(c, ents) for c in rows]}


# ---------------------------------------------------------------------------- sensors and registry
class SensorRef(BaseModel):
    key: str | None = None
    track_id: int | None = None
    object_class: str | None = None
    object_id: str | None = None
    object_type: str | None = None


class SensorObservationIn(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=100)
    sensor_type: Literal["depth", "radar", "thermal", "lidar", "rgb", "other"] = "other"
    run_id: int | None = None
    at: datetime | None = None
    media_time_s: float | None = None
    subject: SensorRef | None = None
    object: SensorRef | None = None
    measurement: dict = Field(default_factory=dict, description="{kind: distance|presence|movement, value, unit}")
    confidence: float | None = Field(default=None, ge=0, le=1)


@router.post("/observations", status_code=201)
def sensor_observation(body: SensorObservationIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """An observation from an external sensor (depth, radar, thermal...). It is
    linked to the relationships it concerns and changes their confidence."""
    if not load_settings(session).modules.sensors:
        raise HTTPException(403, "External sensor observations are switched off (Relationship settings).")
    viewer.require("rules")
    try:
        out = get_relationship_service().ingest_sensor(session, body.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    audit(session, viewer, "sensor_observation", "sensor", body.sensor_id, {"run_id": body.run_id, "corroborated": len(out["corroborated"])})
    session.commit()
    return out


class RegistryItem(BaseModel):
    relation: str
    subject: str = Field(description="Entity key, for example recognized_person:<id>")
    object: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None


class RegistryIn(BaseModel):
    source: str = Field(min_length=2, max_length=100, description="Name of the authorized registry")
    items: list[RegistryItem] = Field(min_length=1, max_length=5000)


@router.post("/registry", status_code=201)
def import_registry(body: RegistryIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """Relations supplied by an authorized external registry (the only way a
    personal or organisational relation can enter the graph). Administrators only."""
    if not viewer.has("admin"):
        raise HTTPException(401 if viewer.role == "none" else 403, "Importing from a registry needs a recognition access token with the 'admin' role.")
    from pathscope.relationships.relations import relation_type

    for it in body.items:
        rt = relation_type(it.relation.upper())
        if rt is None or not rt.external_only:
            raise HTTPException(422, f"{it.relation} is not a registry relationship type: define it under Relationship settings as 'external only' first.")
        for k in (it.subject, it.object):
            t, ref = E.split_key(k)
            if not ref or t not in {x.id for x in E.entity_types()}:
                raise HTTPException(422, f"'{k}' is not an entity key (type:reference).")
    ids = get_relationship_service().import_registry(session, [i.model_dump() for i in body.items], body.source, viewer.name)
    audit(session, viewer, "registry_import", "registry", body.source, {"count": len(ids)})
    session.commit()
    return {"imported": len(ids), "ids": ids}


@router.delete("/relationship/{rel_id}", status_code=204)
def delete_registry_relationship(rel_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    """Withdraw a relation imported from a registry (observed relationships are
    removed with their analysis, never one by one)."""
    if not viewer.has("admin"):
        raise HTTPException(401 if viewer.role == "none" else 403, "Withdrawing registry relations needs the 'admin' role.")
    r = get_or_404(session, RelationRelationship, rel_id, "Relationship")
    if r.analysis_id is not None or not r.rule_key.startswith("registry:"):
        raise HTTPException(409, "Only relations imported from a registry can be withdrawn one by one.")
    session.delete(r)
    audit(session, viewer, "data_deleted", "relationship", rel_id, {"registry": r.rule_key})
    get_relationship_service().delete_orphans(session)
    session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------- export
EXPORT_COLUMNS = ["id", "type", "subject_type", "subject", "subject_key", "object_type", "object", "object_key", "start_at", "end_at", "start_media_s", "end_media_s",
                  "status", "state", "confidence", "rule_key", "rule_version", "rule_name", "reason", "sources", "measure", "unit", "run_id", "camera_id", "experiment_id", "analysis_id"]


@router.get("/export")
def export(format: Literal["csv", "json"] = "csv", identities: bool = False, f: Filters = Depends(filters_dep), limit: int = Query(default=100000, le=500000),
           viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> Response:
    viewer.require("export_identity" if identities else "export")
    from pathscope.relationships.access import Viewer as V

    shown = viewer if identities else V(viewer.name, "none", viewer.settings.model_copy(update={"access": viewer.settings.access.model_copy(update={"identity_role": "admin"})}))
    p = Presenter(session, shown)
    rels = p.g.relationships(f, None, limit=limit)
    ents = p.g.entities({x for r in rels for x in (r.subject_id, r.object_id)})
    p.load_names(ents)
    rows = []
    for r in rels:
        d = p.relationship(r, ents)
        s, o = d["subject"] or {}, d["object"] or {}
        rows.append({
            "id": r.id, "type": r.relation_type, "subject_type": s.get("type"), "subject": s.get("label"), "subject_key": s.get("key"), "object_type": o.get("type"),
            "object": o.get("label"), "object_key": o.get("key"), "start_at": r.start_at.isoformat() if r.start_at else None, "end_at": r.end_at.isoformat() if r.end_at else None,
            "start_media_s": r.start_media_s, "end_media_s": r.end_media_s, "status": r.status, "state": r.state, "confidence": round(r.confidence, 4), "rule_key": r.rule_key,
            "rule_version": r.rule_version, "rule_name": r.rule_name, "reason": r.reason, "sources": ",".join(r.sources or []), "measure": (r.calibration or {}).get("measure"),
            "unit": (r.calibration or {}).get("unit"), "run_id": r.run_id, "camera_id": r.camera_id, "experiment_id": r.experiment_id, "analysis_id": r.analysis_id,
        })
    audit(session, viewer, "export", "relationships", None, {"format": format, "identities": identities, "rows": len(rows)})
    session.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    if format == "json":
        return Response(json.dumps(rows, indent=2), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="relationships-{stamp}.json"'})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="relationships-{stamp}.csv"'})


# ---------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(f: Filters = Depends(filters_dep), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """Counts for the explorer's landing view."""
    R, C = RelationRelationship, RelationCorrelated
    cur = select(RelationAnalysis.id).where(RelationAnalysis.current.is_(True))
    q = select(R.relation_type, func.count(R.id)).where(or_(R.analysis_id.is_(None), R.analysis_id.in_(cur)))
    if f.experiment_id is not None:
        q = q.where(R.experiment_id == f.experiment_id)
    if f.run_id is not None:
        q = q.where(R.run_id == f.run_id)
    by_type = dict(session.execute(q.group_by(R.relation_type)).all())
    cq = select(C.kind, func.count(C.id)).where(or_(C.analysis_id.is_(None), C.analysis_id.in_(cur)))
    if f.experiment_id is not None:
        cq = cq.where(C.experiment_id == f.experiment_id)
    if f.run_id is not None:
        cq = cq.where(C.run_id == f.run_id)
    by_kind = dict(session.execute(cq.group_by(C.kind)).all())
    ent_q = select(RelationEntity.entity_type, func.count(RelationEntity.id)).group_by(RelationEntity.entity_type)
    by_entity = dict(session.execute(ent_q).all())
    if not viewer.sees_identities:
        by_entity = {k: v for k, v in by_entity.items() if k not in E.IDENTITY_TYPES}
    return {"relationships": by_type, "correlated": by_kind, "entities": by_entity, "analyses": session.scalar(select(func.count(RelationAnalysis.id))) or 0,
            "rules": len(latest_rules(session)), "viewer": viewer.to_dict()}


_ = CustomType
