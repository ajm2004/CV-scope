"""Journeys and transitions as a viewer may see them.

A journey is an entity's sightings in time order, each with the camera, the
location it resolves to and the place events it produced there (entered,
exited, parked...), joined by the stored cross-camera transitions. It is the
data behind the journey timeline, the location path on the site view and
the synchronized graph.

Identity-based transitions reveal that two tracks are the same recognized
person or vehicle, so they are shown only to viewers allowed to see
identities; everybody else sees anonymous (timing-only) transitions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select

from pathscope.crosscam.engine import (
    IDENTITY_LINKS,
    Correlator,
    Namer,
    Sighting,
    build_sightings,
    identity_map,
    stable_uid,
)
from pathscope.location.models import CrossCameraTransition
from pathscope.location.settings import load_crosscam_settings
from pathscope.location.topology import LocationGraph
from pathscope.relationships import entities as E
from pathscope.relationships.confidence import STATE_LABELS, STATE_RANK, STATES
from pathscope.relationships.graph import Presenter
from pathscope.relationships.models import RelationEntity, RelationRelationship
from pathscope.relationships.relations import relation_type

PLACE_VERBS = {"ENTERED": "Entered", "EXITED": "Exited", "CROSSED": "Crossed", "PARKED_IN": "Parked in", "REMAINED_IN": "Stayed in", "USED_ROUTE": "Used route",
               "STOPPED_NEAR": "Stopped near", "OCCUPIED": "Was in"}


def node_ref(loc: LocationGraph, nid: int | None) -> dict | None:
    if nid is None or nid not in loc.nodes:
        return None
    n = loc.nodes[nid]
    return {"id": nid, "name": n.name, "kind": n.kind, "path": loc.path_label(nid), "frame_id": loc.frame(nid), "x": n.x, "y": n.y, "restricted": n.restricted, "is_entry": n.is_entry}


def camera_ref(loc: LocationGraph, nm: Namer, cid: int | None) -> dict:
    nid = loc.by_camera.get(cid) if cid is not None else None
    return {"id": cid, "name": nm.camera(cid), "node": node_ref(loc, nid)}


def visible_basis(p: Presenter, basis: str) -> bool:
    return basis == "anonymous" or p.identities


def transition_out(p: Presenter, loc: LocationGraph, nm: Namer, t: CrossCameraTransition, ents: dict[int, RelationEntity]) -> dict:
    subj = ents.get(t.subject_id)
    return {
        "id": t.id, "uid": t.uid, "basis": t.basis, "status": t.status, "subject": p.entity(subj),
        "from": {"camera": camera_ref(loc, nm, t.from_camera_id), "node": node_ref(loc, t.from_node_id), "track": p.entity(ents.get(t.from_track_id)), "run_id": t.from_run_id,
                 "media_s": t.left_media_s, "at": t.left_at},
        "to": {"camera": camera_ref(loc, nm, t.to_camera_id), "node": node_ref(loc, t.to_node_id), "track": p.entity(ents.get(t.to_track_id)), "run_id": t.to_run_id,
               "media_s": t.arrived_media_s, "at": t.arrived_at},
        "left_at": t.left_at, "arrived_at": t.arrived_at, "gap_s": t.gap_s,
        "expected": {"min_s": t.expected_min_s, "max_s": t.expected_max_s, "source": t.expected_source},
        "topology": {"kind": t.topology, "hops": t.hops, "path": [node_ref(loc, n) for n in (t.path or []) if n in loc.nodes]},
        "identity_confidence": t.identity_confidence, "components": t.components or {}, "confidence": round(t.confidence, 4), "state": t.state,
        "state_label": STATE_LABELS.get(t.state, t.state), "sensors": t.sensor_evidence or [], "flags": t.flags or [], "reason": t.reason,
        "relationships": {"moved_from": _rel_id(p, stable_uid("from", t.uid)), "moved_to": _rel_id(p, stable_uid("to", t.uid))},
    }


def _rel_id(p: Presenter, uid: str) -> int | None:
    return p.s.scalar(select(RelationRelationship.id).where(RelationRelationship.uid == uid))


def transitions(p: Presenter, f: dict, limit: int = 500) -> list[dict]:
    T = CrossCameraTransition
    q = select(T)
    if not f.get("include_withdrawn"):
        q = q.where(T.status == "active")
    if f.get("time_from") is not None:
        q = q.where(T.arrived_at >= f["time_from"])
    if f.get("time_to") is not None:
        q = q.where(T.left_at <= f["time_to"])
    if f.get("camera_ids") is not None:
        cams = list(f["camera_ids"])
        q = q.where(or_(T.from_camera_id.in_(cams), T.to_camera_id.in_(cams)))
    if f.get("run_id") is not None:
        q = q.where(or_(T.from_run_id == f["run_id"], T.to_run_id == f["run_id"]))
    if f.get("subject_ids") is not None:
        q = q.where(T.subject_id.in_(list(f["subject_ids"])))
    if f.get("track_ids") is not None:
        ids = list(f["track_ids"])
        q = q.where(or_(T.from_track_id.in_(ids), T.to_track_id.in_(ids)))
    if not p.identities:
        q = q.where(T.basis == "anonymous")
    ms = f.get("min_state") or "possible"
    if ms in STATES and ms != "insufficient":
        q = q.where(T.state.in_([s for s in STATES if STATE_RANK[s] >= STATE_RANK[ms]]))
    if f.get("flagged"):
        q = q.where(T.flags != [])
    rows = list(p.s.scalars(q.order_by(T.arrived_at.desc()).limit(limit)))
    loc = LocationGraph.load(p.s)
    nm = Namer(p.s, loc)
    ents = p.g.entities({x for t in rows for x in (t.subject_id, t.from_track_id, t.to_track_id)})
    p.load_names(ents)
    return [transition_out(p, loc, nm, t, ents) for t in rows]


def _sighting_out(p: Presenter, loc: LocationGraph, nm: Namer, s: Sighting, ents: dict[int, RelationEntity], index: int) -> dict:
    events = []
    for r in s.places:
        obj = ents.get(r.object_id)
        nid = loc.resolve_key(obj.key) if obj is not None else None
        events.append({
            "relationship_id": r.id, "type": r.relation_type, "verb": PLACE_VERBS.get(r.relation_type) or (relation_type(r.relation_type).label if relation_type(r.relation_type) else r.relation_type),
            "place": p.entity(obj)["label"] if obj is not None else "?", "node": node_ref(loc, nid), "at": r.start_at, "end_at": r.end_at,
            "media_s": r.start_media_s, "end_media_s": r.end_media_s, "state": r.state, "confidence": round(r.confidence, 4),
        })
    node = s.entry_node or s.exit_node or (loc.by_camera.get(s.camera_id) if s.camera_id is not None else None)
    return {
        "index": index, "track": p.entity(s.track), "basis": s.basis, "identity_confidence": s.identity.confidence if s.identity else None,
        "camera": camera_ref(loc, nm, s.camera_id), "run_id": s.run_id, "experiment_id": s.experiment_id, "object_class": s.object_class,
        "first_at": s.first_at, "last_at": s.last_at, "first_media_s": s.first_media, "last_media_s": s.last_media,
        "entry": node_ref(loc, s.entry_node), "exit": node_ref(loc, s.exit_node), "node": node_ref(loc, node), "events": events,
        "summary": _summary(nm, s, events),
    }


def _summary(nm: Namer, s: Sighting, events: list[dict]) -> str:
    if not events:
        return f"Observed on {nm.camera(s.camera_id)}"
    first = events[0]
    return f"{first['verb']} {first['place']}" + (f" (+{len(events) - 1} more)" if len(events) > 1 else "")


def journey(p: Presenter, entity: RelationEntity, time_from: datetime | None, time_to: datetime | None, max_sightings: int = 400) -> dict:
    s = p.s
    loc = LocationGraph.load(s)
    cfg = load_crosscam_settings(s)
    nm = Namer(s, loc)
    t1 = time_to or datetime.now(UTC)
    t0 = time_from or (t1 - timedelta(days=7))
    T = CrossCameraTransition
    if entity.entity_type in E.IDENTITY_TYPES:
        c = Correlator(s, loc, cfg)
        tracks = c._tracks_of_subject(entity.id, t0, t1)
        idents = identity_map(s, {t.id for t in tracks}, cfg.min_identity_state)
        tracks = [t for t in tracks if t.id in idents and idents[t.id].subject_id == entity.id]
        trans = list(s.scalars(select(T).where(T.subject_id == entity.id, T.status == "active", T.arrived_at >= t0, T.left_at <= t1).order_by(T.arrived_at)))
    else:
        # a track: itself, plus the anonymous transitions that continue it on other cameras
        idents = {}
        chain = {entity.id}
        frontier = {entity.id}
        trans = []
        seen_t = set()
        for _ in range(50):
            if not frontier:
                break
            rows = list(s.scalars(select(T).where(T.status == "active", T.basis == "anonymous", or_(T.from_track_id.in_(frontier), T.to_track_id.in_(frontier)))))
            frontier = set()
            for t in rows:
                if t.id in seen_t:
                    continue
                seen_t.add(t.id)
                trans.append(t)
                for x in (t.from_track_id, t.to_track_id):
                    if x not in chain:
                        chain.add(x)
                        frontier.add(x)
        tracks = list(s.scalars(select(RelationEntity).where(RelationEntity.id.in_(chain))))
        trans.sort(key=lambda t: t.arrived_at)
        if p.identities:
            idents = identity_map(s, {t.id for t in tracks}, cfg.min_identity_state)
    sightings = build_sightings(s, tracks, idents, loc)[-max_sightings:]
    ents = p.g.entities({x.track.id for x in sightings} | {r.object_id for x in sightings for r in x.places} | {entity.id} | {x for t in trans for x in (t.subject_id, t.from_track_id, t.to_track_id)})
    p.load_names(ents)
    steps = [_sighting_out(p, loc, nm, x, ents, i) for i, x in enumerate(sightings)]
    tout = [transition_out(p, loc, nm, t, ents) for t in trans if visible_basis(p, t.basis)]
    by_track = {x.track.id: i for i, x in enumerate(sightings)}
    for t, raw in zip(tout, [t for t in trans if visible_basis(p, t.basis)], strict=False):
        t["from_index"] = by_track.get(raw.from_track_id)
        t["to_index"] = by_track.get(raw.to_track_id)
    path = []
    for st in steps:
        n = st["node"] or (st["camera"]["node"])
        if n is not None and (not path or path[-1]["node"]["id"] != n["id"]):
            path.append({"node": n, "camera": st["camera"], "at": st["first_at"], "index": st["index"]})
    return {"entity": p.entity(entity), "time_from": t0, "time_to": t1, "sightings": steps, "transitions": tout, "path": path,
            "cameras": sorted({x.camera_id for x in sightings if x.camera_id is not None})}


def last_seen(p: Presenter, entity: RelationEntity) -> dict | None:
    s = p.s
    loc = LocationGraph.load(s)
    nm = Namer(s, loc)
    if entity.entity_type in E.IDENTITY_TYPES:
        al = p.g.aliases(entity)
        tracks = list(s.scalars(select(RelationEntity).where(RelationEntity.id.in_(list(al))))) if al else []
    elif entity.entity_type in E.TRACK_TYPES:
        tracks = [entity]
    else:
        return None
    tracks = [t for t in tracks if t.last_seen is not None]
    if not tracks:
        return None
    t = max(tracks, key=lambda x: x.last_seen)
    sights = build_sightings(s, [t], {}, loc)
    sg = sights[0] if sights else None
    node = (sg.exit_node or sg.entry_node) if sg else None
    return {"track": p.entity(t), "camera": camera_ref(loc, nm, t.camera_id), "node": node_ref(loc, node) or camera_ref(loc, nm, t.camera_id)["node"],
            "at": t.last_seen, "media_s": t.last_media_s, "run_id": t.run_id}


_ = IDENTITY_LINKS
