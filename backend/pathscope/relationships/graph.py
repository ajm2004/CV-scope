"""Graph API over the relationship tables.

The rest of CV-Scope (API, patterns, summaries) asks graph questions here:
an entity's neighbours, a subgraph, a timeline, an entity's history, and
structured searches. ``GraphBackend`` is the contract; ``SqlGraph`` answers
it with indexed queries on the relational tables. A graph database can be
added behind the same contract when traversal depth or scale needs it.

Identity projection: relationships are stored between what was observed
(tracks). A recognized person's neighbourhood is the union of the
neighbourhoods of the tracks IDENTIFIED_AS that person (with at least
``likely`` confidence); the other side is lifted to its identity as well,
and every projected relationship says which track it came through. Only
viewers allowed to see identities get projections; for everyone else an
identity is an opaque "Recognized person" that cannot be opened.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from pathscope.relationships import entities as E
from pathscope.relationships.access import Viewer
from pathscope.relationships.confidence import STATE_LABELS, STATE_RANK, STATES, at_least
from pathscope.relationships.models import (
    RelationAnalysis,
    RelationCorrelated,
    RelationEntity,
    RelationObservation,
    RelationRelationship,
    RelationSupport,
)
from pathscope.relationships.observations import observation_type
from pathscope.relationships.relations import relation_type

IDENTITY_LINKS = ("IDENTIFIED_AS", "IDENTIFIED_BY_PLATE")
ASSOCIATION_TYPES = ("ASSOCIATED_WITH", "ARRIVED_WITH", "DEPARTED_WITH", "TRAVELLED_WITH", "NEAR", "APPROACHED", "STOPPED_NEAR", "ENTERED_VEHICLE", "EXITED_VEHICLE", "FOLLOWED", "MOVED_AWAY_FROM")
PLACE_TYPES = ("ENTERED", "EXITED", "CROSSED", "USED_ROUTE", "PARKED_IN", "REMAINED_IN", "OCCUPIED", "MOVED_FROM", "MOVED_TO")
TIMELINE_SKIP = {"ENTERED", "EXITED", "CROSSED", "IDENTIFIED_AS", "IDENTIFIED_BY_PLATE", "REGISTERED_AS", "OCCUPIED", "USED_ROUTE"}  # shown as observations


@dataclass
class Filters:
    types: list[str] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    camera_id: int | None = None
    experiment_id: int | None = None
    run_id: int | None = None
    zone_id: str | None = None
    min_state: str = "possible"
    analysis_id: int | None = None
    include_superseded: bool = False
    # a site or location of the location model: the cameras inside it
    camera_ids: set[int] | None = None


class GraphBackend(Protocol):
    """What the API needs from a graph store."""

    def entity(self, key: str) -> RelationEntity | None: ...
    def relationships(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 500, offset: int = 0) -> list[RelationRelationship]: ...
    def aliases(self, entity: RelationEntity) -> dict[int, RelationRelationship]: ...
    def identities_of(self, track_ids: set[int]) -> dict[int, int]: ...
    def observations(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 2000) -> list[RelationObservation]: ...
    def correlated(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 500) -> list[RelationCorrelated]: ...


class SqlGraph:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ------------------------------------------------------------------ basics
    def entity(self, key: str) -> RelationEntity | None:
        return self.s.scalar(select(RelationEntity).where(RelationEntity.key == key))

    def entities(self, ids: set[int]) -> dict[int, RelationEntity]:
        ids = {i for i in ids if i is not None}
        if not ids:
            return {}
        return {e.id: e for e in self.s.scalars(select(RelationEntity).where(RelationEntity.id.in_(ids)))}

    def _current(self, q, model, f: Filters):
        if f.analysis_id is not None:
            return q.where(model.analysis_id == f.analysis_id)
        if not f.include_superseded:
            cur = select(RelationAnalysis.id).where(RelationAnalysis.current.is_(True))
            q = q.where(or_(model.analysis_id.is_(None), model.analysis_id.in_(cur)))
        return q

    def relationships(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 500, offset: int = 0) -> list[RelationRelationship]:
        R = RelationRelationship
        q = self._current(select(R), R, f)
        if entity_ids is not None:
            if not entity_ids:
                return []
            q = q.where(or_(R.subject_id.in_(entity_ids), R.object_id.in_(entity_ids)))
        if f.types:
            q = q.where(R.relation_type.in_(f.types))
        if f.time_from is not None:
            q = q.where(or_(R.end_at.is_(None), R.end_at >= f.time_from))
        if f.time_to is not None:
            q = q.where(R.start_at <= f.time_to)
        if f.camera_id is not None:
            q = q.where(R.camera_id == f.camera_id)
        if f.camera_ids is not None:
            q = q.where(R.camera_id.in_(list(f.camera_ids)))
        if f.experiment_id is not None:
            q = q.where(R.experiment_id == f.experiment_id)
        if f.run_id is not None:
            q = q.where(R.run_id == f.run_id)
        if f.zone_id:
            q = q.where(R.zone_id == f.zone_id)
        if f.min_state and f.min_state != "insufficient":
            q = q.where(R.state.in_([s for s in STATES if STATE_RANK[s] >= STATE_RANK[f.min_state]]))
        return list(self.s.scalars(q.order_by(R.start_at.asc(), R.id.asc()).limit(limit).offset(offset)))

    def observations(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 2000) -> list[RelationObservation]:
        Ob = RelationObservation
        q = self._current(select(Ob), Ob, f)
        if entity_ids is not None:
            if not entity_ids:
                return []
            q = q.where(or_(Ob.entity_id.in_(entity_ids), Ob.object_entity_id.in_(entity_ids)))
        if f.time_from is not None:
            q = q.where(Ob.at >= f.time_from)
        if f.time_to is not None:
            q = q.where(Ob.at <= f.time_to)
        if f.camera_id is not None:
            q = q.where(Ob.camera_id == f.camera_id)
        if f.camera_ids is not None:
            q = q.where(Ob.camera_id.in_(list(f.camera_ids)))
        if f.run_id is not None:
            q = q.where(Ob.run_id == f.run_id)
        if f.experiment_id is not None:
            runs = select(RelationAnalysis.run_id).where(RelationAnalysis.experiment_id == f.experiment_id)
            q = q.where(Ob.run_id.in_(runs))
        return list(self.s.scalars(q.order_by(Ob.at.asc(), Ob.id.asc()).limit(limit)))

    def correlated(self, f: Filters, entity_ids: set[int] | None = None, limit: int = 500) -> list[RelationCorrelated]:
        C = RelationCorrelated
        q = self._current(select(C), C, f)
        if f.time_from is not None:
            q = q.where(or_(C.end_at.is_(None), C.end_at >= f.time_from))
        if f.time_to is not None:
            q = q.where(C.start_at <= f.time_to)
        if f.camera_id is not None:
            q = q.where(C.camera_id == f.camera_id)
        if f.camera_ids is not None:
            q = q.where(C.camera_id.in_(list(f.camera_ids)))
        if f.experiment_id is not None:
            q = q.where(C.experiment_id == f.experiment_id)
        if f.run_id is not None:
            q = q.where(C.run_id == f.run_id)
        if f.min_state and f.min_state != "insufficient":
            q = q.where(C.state.in_([s for s in STATES if STATE_RANK[s] >= STATE_RANK[f.min_state]]))
        rows = list(self.s.scalars(q.order_by(C.start_at.asc()).limit(limit * 4 if entity_ids is not None else limit)))
        if entity_ids is not None:
            rows = [c for c in rows if set((c.roles or {}).values()) & entity_ids][:limit]
        return rows

    # ------------------------------------------------------------------ identity projection
    def aliases(self, entity: RelationEntity) -> dict[int, RelationRelationship]:
        """Track entity id -> the identity link that ties it to this identity entity."""
        R = RelationRelationship
        f = Filters(min_state="likely")
        targets = {entity.id}
        if entity.entity_type == "registered_vehicle":
            # registered vehicle <- REGISTERED_AS - plate <- IDENTIFIED_BY_PLATE - vehicle track
            plates = self.s.scalars(self._current(select(R.subject_id).where(R.object_id == entity.id, R.relation_type == "REGISTERED_AS"), R, f))
            targets |= set(plates)
        if entity.entity_type not in E.IDENTITY_TYPES:
            return {}
        q = self._current(select(R).where(R.object_id.in_(targets), R.relation_type.in_(IDENTITY_LINKS)), R, f)
        out: dict[int, RelationRelationship] = {}
        for r in self.s.scalars(q):
            if at_least(r.state, "likely"):
                out[r.subject_id] = r
        return out

    def identities_of(self, track_ids: set[int]) -> dict[int, int]:
        """Track entity id -> its identity entity id (recognized person, else registered vehicle, else plate)."""
        if not track_ids:
            return {}
        R = RelationRelationship
        f = Filters(min_state="likely")
        rows = [r for r in self.s.scalars(self._current(select(R).where(R.subject_id.in_(track_ids), R.relation_type.in_(IDENTITY_LINKS)), R, f)) if at_least(r.state, "likely")]
        plate_ids = {r.object_id for r in rows if r.relation_type == "IDENTIFIED_BY_PLATE"}
        registered: dict[int, int] = {}
        if plate_ids:
            for r in self.s.scalars(self._current(select(R).where(R.subject_id.in_(plate_ids), R.relation_type == "REGISTERED_AS"), R, f)):
                registered[r.subject_id] = r.object_id
        out: dict[int, int] = {}
        best: dict[int, float] = {}
        for r in rows:
            target = registered.get(r.object_id, r.object_id) if r.relation_type == "IDENTIFIED_BY_PLATE" else r.object_id
            if r.confidence >= best.get(r.subject_id, -1):
                best[r.subject_id] = r.confidence
                out[r.subject_id] = target
        return out

    def support(self, relationship_id: int | None = None, correlated_id: int | None = None) -> tuple[list[RelationObservation], list[RelationRelationship]]:
        S = RelationSupport
        q = select(S)
        q = q.where(S.relationship_id == relationship_id) if relationship_id is not None else q.where(S.correlated_id == correlated_id)
        links = list(self.s.scalars(q))
        obs_ids = [x.observation_id for x in links if x.observation_id]
        rel_ids = [x.supporting_relationship_id for x in links if x.supporting_relationship_id]
        obs = list(self.s.scalars(select(RelationObservation).where(RelationObservation.id.in_(obs_ids)).order_by(RelationObservation.at))) if obs_ids else []
        rels = list(self.s.scalars(select(RelationRelationship).where(RelationRelationship.id.in_(rel_ids)).order_by(RelationRelationship.start_at))) if rel_ids else []
        return obs, rels

    def cited_by(self, relationship_id: int) -> tuple[list[RelationRelationship], list[RelationCorrelated]]:
        S = RelationSupport
        links = list(self.s.scalars(select(S).where(S.supporting_relationship_id == relationship_id)))
        rel_ids = [x.relationship_id for x in links if x.relationship_id]
        cor_ids = [x.correlated_id for x in links if x.correlated_id]
        rels = list(self.s.scalars(select(RelationRelationship).where(RelationRelationship.id.in_(rel_ids)))) if rel_ids else []
        cors = list(self.s.scalars(select(RelationCorrelated).where(RelationCorrelated.id.in_(cor_ids)))) if cor_ids else []
        return rels, cors


# ---------------------------------------------------------------------------- presentation (what a viewer may see)
class Presenter:
    def __init__(self, session: Session, viewer: Viewer, graph: SqlGraph | None = None) -> None:
        self.s = session
        self.viewer = viewer
        self.g = graph or SqlGraph(session)
        self._names: dict[int, str] = {}
        mods = viewer.settings.modules
        self.hidden_types = set()
        if not mods.face:
            self.hidden_types.add("recognized_person")
        if not mods.plate:
            self.hidden_types |= {"license_plate", "registered_vehicle"}

    @property
    def identities(self) -> bool:
        return self.viewer.sees_identities

    def visible(self, e: RelationEntity) -> bool:
        return not (E.is_sensitive(e.entity_type) and (not self.identities or e.entity_type in self.hidden_types))

    def load_names(self, ents: dict[int, RelationEntity]) -> None:
        """Names of identities, for viewers who may see them."""
        if not self.identities:
            return
        people = {e.ref: e.id for e in ents.values() if e.entity_type == "recognized_person" and e.id not in self._names}
        vehicles = {e.ref: e.id for e in ents.values() if e.entity_type == "registered_vehicle" and e.id not in self._names}
        try:
            from pathscope.recognition.registry.models import RecognitionPerson, RecognitionVehicle

            if people:
                for p in self.s.scalars(select(RecognitionPerson).where(RecognitionPerson.id.in_(list(people)))):
                    self._names[people[p.id]] = p.display_name
            if vehicles:
                for v in self.s.scalars(select(RecognitionVehicle).where(RecognitionVehicle.id.in_(list(vehicles)))):
                    self._names[vehicles[v.id]] = v.description or v.owner_ref or v.plate
        except Exception:  # noqa: BLE001 - names are a convenience; ids stay
            pass
        for e in ents.values():
            if e.entity_type == "license_plate" and e.secret_label:
                self._names[e.id] = e.secret_label

    def entity(self, e: RelationEntity | None, identity: RelationEntity | None = None) -> dict | None:
        if e is None:
            return None
        et = E.entity_type(e.entity_type)
        base = {"type": e.entity_type, "type_label": et.label, "category": et.category, "sensitive": et.sensitive}
        if not self.visible(e):
            return {**base, "id": None, "key": None, "label": et.label, "redacted": True}
        label = self._names.get(e.id) or e.label or et.label
        if et.sensitive and e.id not in self._names:
            label = f"{et.label} (not in the registry)" if e.entity_type != "license_plate" else et.label
        meta = {k: v for k, v in (e.meta or {}).items() if k not in ("groups",) or self.identities}
        out = {
            **base, "id": e.id, "key": e.key, "label": label, "redacted": False, "run_id": e.run_id, "camera_id": e.camera_id, "experiment_id": e.experiment_id,
            "confidence": e.confidence, "first_seen": e.first_seen, "last_seen": e.last_seen, "first_media_s": e.first_media_s, "last_media_s": e.last_media_s, "meta": meta,
        }
        if identity is not None and self.visible(identity):
            out["identity"] = {"id": identity.id, "key": identity.key, "type": identity.entity_type, "label": self._names.get(identity.id) or E.entity_type(identity.entity_type).label}
        return out

    def display(self, e: RelationEntity | None, identity: RelationEntity | None = None) -> str:
        """Short text label for sentences: 'Employee-017 (Person track #3)' for authorized viewers."""
        if e is None:
            return "?"
        d = self.entity(e, identity)
        if d.get("identity"):
            return f"{d['identity']['label']} ({d['label']})"
        return d["label"]

    def relationship(self, r: RelationRelationship, ents: dict[int, RelationEntity], lifted: dict[int, int] | None = None, via: RelationEntity | None = None) -> dict:
        rt = relation_type(r.relation_type)
        lifted = lifted or {}
        subj, obj = ents.get(r.subject_id), ents.get(r.object_id)
        out = {
            "id": r.id, "uid": r.uid, "type": r.relation_type, "label": rt.label if rt else r.relation_type.lower().replace("_", " "), "category": rt.category if rt else "association",
            "subject": self.entity(subj, ents.get(lifted.get(r.subject_id, -1)) if self.identities else None),
            "object": self.entity(obj, ents.get(lifted.get(r.object_id, -1)) if self.identities else None),
            "start_at": r.start_at, "end_at": r.end_at, "start_media_s": r.start_media_s, "end_media_s": r.end_media_s, "status": r.status,
            "confidence": round(r.confidence, 4), "state": r.state, "state_label": STATE_LABELS.get(r.state, r.state), "components": r.components or {},
            "rule": {"key": r.rule_key, "version": r.rule_version, "name": r.rule_name}, "reason": r.reason, "zone_id": r.zone_id, "sources": r.sources or [],
            "calibration": r.calibration or {}, "metrics": r.metrics or {}, "run_id": r.run_id, "camera_id": r.camera_id, "experiment_id": r.experiment_id, "analysis_id": r.analysis_id,
        }
        if via is not None:
            out["via"] = self.entity(via)
        return out

    def observation(self, o: RelationObservation, ents: dict[int, RelationEntity]) -> dict:
        return {
            "id": o.id, "uid": o.uid, "type": o.observation_type, "label": observation_type(o.observation_type).label, "entity": self.entity(ents.get(o.entity_id)),
            "object": self.entity(ents.get(o.object_entity_id)) if o.object_entity_id else None, "at": o.at, "media_time_s": o.media_time_s, "source": o.source,
            "confidence": o.confidence, "value": o.value or {}, "run_id": o.run_id, "camera_id": o.camera_id,
        }

    def correlated(self, c: RelationCorrelated, ents: dict[int, RelationEntity]) -> dict:
        return {
            "id": c.id, "uid": c.uid, "kind": c.kind, "label": c.label, "start_at": c.start_at, "end_at": c.end_at, "start_media_s": c.start_media_s, "end_media_s": c.end_media_s,
            "confidence": round(c.confidence, 4), "state": c.state, "state_label": STATE_LABELS.get(c.state, c.state), "description": c.description,
            "rule": {"key": c.rule_key, "version": c.rule_version, "name": c.rule_name},
            "roles": {role: self.entity(ents.get(eid)) for role, eid in (c.roles or {}).items()}, "temporal": c.temporal or [], "metrics": c.metrics or {},
            "run_id": c.run_id, "camera_id": c.camera_id, "experiment_id": c.experiment_id, "published": c.published,
        }

    # ------------------------------------------------------------------ queries
    def _scope(self, entity: RelationEntity) -> tuple[set[int], dict[int, RelationRelationship]]:
        """The entity itself plus, for identities, the tracks that resolve to it."""
        if entity.entity_type in E.IDENTITY_TYPES:
            al = self.g.aliases(entity)
            return {entity.id, *al.keys()}, al
        return {entity.id}, {}

    def neighbors(self, entity: RelationEntity, f: Filters, limit: int = 2000) -> dict:
        ids, aliases = self._scope(entity)
        rels = [r for r in self.g.relationships(f, ids, limit=limit) if not (r.relation_type in IDENTITY_LINKS and r.subject_id in aliases)]
        ents = self.g.entities({x for r in rels for x in (r.subject_id, r.object_id)} | set(aliases) | {entity.id})
        lifted = self.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if self.identities else {}
        ents.update(self.g.entities(set(lifted.values()) - set(ents)))
        self.load_names(ents)
        groups: dict[str, dict] = {}
        for r in rels:
            mine_is_subject = r.subject_id in ids
            other_id = r.object_id if mine_is_subject else r.subject_id
            other_lift = lifted.get(other_id)
            group_id = other_lift if (other_lift is not None and self.visible(ents[other_lift])) else other_id
            other = ents.get(group_id)
            if other is None:
                continue
            key = other.key if self.visible(other) else f"redacted:{other.entity_type}:{r.id}"
            via_id = r.subject_id if mine_is_subject else r.object_id
            item = self.relationship(r, ents, lifted, via=ents.get(via_id) if via_id != entity.id else None)
            item["direction"] = "outgoing" if mine_is_subject else "incoming"
            g = groups.get(key)
            if g is None:
                g = groups[key] = {"entity": self.entity(other), "relationships": [], "types": Counter(), "best_confidence": 0.0, "last_at": None, "sessions": set()}
            g["relationships"].append(item)
            g["types"][r.relation_type] += 1
            g["best_confidence"] = max(g["best_confidence"], r.confidence)
            end = r.end_at or r.start_at
            if g["last_at"] is None or end > g["last_at"]:
                g["last_at"] = end
            if r.run_id is not None:
                g["sessions"].add(r.run_id)
        out = []
        for g in groups.values():
            g["types"] = dict(g["types"])
            g["sessions"] = len(g["sessions"])
            out.append(g)
        out.sort(key=lambda g: (-g["best_confidence"], str(g["last_at"])))
        return {"entity": self.entity(entity), "aliases": [self.entity(ents[i]) for i in aliases if i in ents], "related": out, "count": len(rels)}

    def subgraph(self, entity: RelationEntity, f: Filters, depth: int = 1, max_edges: int = 400) -> dict:
        """Nodes and edges around an entity (depth 1 or 2), identity-projected for authorized viewers."""
        ids, aliases = self._scope(entity)
        frontier = set(ids)
        seen_nodes = set(ids)
        edges: dict[int, RelationRelationship] = {}
        for _ in range(max(1, min(depth, 2))):
            rels = self.g.relationships(f, frontier, limit=max_edges)
            nxt: set[int] = set()
            for r in rels:
                if r.relation_type in IDENTITY_LINKS and r.subject_id in aliases:
                    continue
                edges[r.id] = r
                for x in (r.subject_id, r.object_id):
                    if x not in seen_nodes:
                        nxt.add(x)
                        seen_nodes.add(x)
                if len(edges) >= max_edges:
                    break
            frontier = nxt
            if not frontier or len(edges) >= max_edges:
                break
        ents = self.g.entities(seen_nodes | {entity.id})
        lifted = self.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if self.identities else {}
        ents.update(self.g.entities(set(lifted.values()) - set(ents)))
        self.load_names(ents)

        def node_of(eid: int) -> int:
            if eid in aliases:
                return entity.id
            li = lifted.get(eid)
            return li if li is not None and self.visible(ents[li]) else eid

        nodes: dict[int, dict] = {}
        out_edges: dict[tuple, dict] = {}
        for r in edges.values():
            a, b = node_of(r.subject_id), node_of(r.object_id)
            if a == b:
                continue
            for n in (a, b):
                if n not in nodes:
                    d = self.entity(ents.get(n))
                    nodes[n] = {**d, "node": d["key"] or f"redacted-{n}"}
            k = (a, b, r.relation_type)
            e = out_edges.get(k)
            if e is None:
                e = out_edges[k] = {"source": nodes[a]["node"], "target": nodes[b]["node"], "type": r.relation_type, "count": 0, "best_confidence": 0.0, "state": r.state, "ids": []}
            e["count"] += 1
            e["ids"].append(r.id)
            if r.confidence > e["best_confidence"]:
                e["best_confidence"], e["state"] = round(r.confidence, 4), r.state
        if entity.id not in nodes:
            d = self.entity(entity)
            nodes[entity.id] = {**d, "node": d["key"]}
        return {"center": nodes[entity.id]["node"], "nodes": list(nodes.values()), "edges": list(out_edges.values())}

    def timeline(self, f: Filters, entity: RelationEntity | None = None, limit: int = 1500) -> list[dict]:
        ids = None
        if entity is not None:
            ids, _aliases = self._scope(entity)
        obs = self.g.observations(f, ids, limit=limit)
        rels = [r for r in self.g.relationships(f, ids, limit=limit) if r.relation_type not in TIMELINE_SKIP]
        cors = self.g.correlated(f, ids, limit=limit)
        ent_ids = {x for o in obs for x in (o.entity_id, o.object_entity_id)} | {x for r in rels for x in (r.subject_id, r.object_id)} | {x for c in cors for x in (c.roles or {}).values()}
        ents = self.g.entities(ent_ids)
        lifted = self.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if self.identities else {}
        ents.update(self.g.entities(set(lifted.values()) - set(ents)))
        self.load_names(ents)

        def who(eid: int | None) -> str:
            if eid is None:
                return ""
            return self.display(ents.get(eid), ents.get(lifted.get(eid, -1)))

        items: list[dict] = []
        for o in obs:
            if o.observation_type in ("appeared",) and entity is None and f.run_id is None:
                continue
            subject, obj = who(o.entity_id), who(o.object_entity_id)
            v = o.value or {}
            verb, target, extra = {
                "appeared": ("appeared", "", ""), "disappeared": ("was last seen", "", ""), "entered": ("entered", obj, ""), "exited": ("left", obj, ""),
                "crossed": ("crossed", obj, f"({v.get('direction')})" if v.get("direction") else ""), "route_completed": ("completed route", obj, ""),
                "stopped": ("stopped in", obj, ""), "recognized": ("was recognized as", obj, ""), "possible_match": ("possibly matched", obj, ""),
                "plate_read": ("had its plate read", "", ""), "registered_vehicle": ("is registered as", obj, ""),
                "sensor": ("reported", str(v.get("kind") or "a measurement"), ""), "event": ("had an event:", str(v.get("label") or v.get("event_type") or ""), ""),
            }.get(o.observation_type, (observation_type(o.observation_type).label, obj, ""))
            text = " ".join(x for x in (subject, verb, target, extra) if x)
            items.append({"kind": "observation", "id": o.id, "type": o.observation_type, "at": o.at, "media_time_s": o.media_time_s, "run_id": o.run_id,
                          "camera_id": o.camera_id, "text": text, "parts": {"subject": subject, "verb": verb, "object": target, "extra": extra},
                          "confidence": o.confidence, "source": o.source})
        for r in rels:
            rt = relation_type(r.relation_type)
            # media time is the run's own clock (a video file is analysed faster than real time)
            if r.end_media_s is not None and r.start_media_s is not None:
                dur = r.end_media_s - r.start_media_s
            else:
                dur = (r.end_at - r.start_at).total_seconds() if r.end_at else None
            extra = f"for {dur:.0f} s" if dur and dur >= 1 and r.relation_type in ("NEAR", "ASSOCIATED_WITH", "TRAVELLED_WITH", "FOLLOWED", "STOPPED_NEAR", "REMAINED_IN", "PARKED_IN") else ""
            parts = {"subject": who(r.subject_id), "verb": rt.label if rt else r.relation_type.lower().replace("_", " "), "object": who(r.object_id), "extra": extra}
            items.append({"kind": "relationship", "id": r.id, "type": r.relation_type, "at": r.start_at, "end_at": r.end_at, "media_time_s": r.start_media_s, "end_media_s": r.end_media_s,
                          "run_id": r.run_id, "camera_id": r.camera_id, "state": r.state, "confidence": round(r.confidence, 4),
                          "text": " ".join(x for x in parts.values() if x), "parts": parts})
        for c in cors:
            roles = {k: who(v) for k, v in (c.roles or {}).items()}
            items.append({"kind": "correlated", "id": c.id, "type": c.kind, "at": c.start_at, "end_at": c.end_at, "media_time_s": c.start_media_s, "end_media_s": c.end_media_s, "run_id": c.run_id,
                          "camera_id": c.camera_id, "state": c.state, "confidence": round(c.confidence, 4), "text": c.label, "description": c.description,
                          "roles": roles, "parts": {"subject": roles.get("A") or roles.get("subject") or "", "verb": c.label, "object": roles.get("B") or roles.get("other") or "", "extra": ""}})
        if f.run_id is not None:
            items.sort(key=lambda x: (x["media_time_s"] if x["media_time_s"] is not None else 1e18, 0 if x["kind"] == "observation" else 1))
        else:
            items.sort(key=lambda x: (x["at"], 0 if x["kind"] == "observation" else 1))
        return items[:limit]

    def history(self, entity: RelationEntity, f: Filters) -> dict:
        ids, aliases = self._scope(entity)
        rels = self.g.relationships(f, ids, limit=20000)
        ents = self.g.entities({x for r in rels for x in (r.subject_id, r.object_id)} | set(aliases))
        lifted = self.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if self.identities else {}
        ents.update(self.g.entities(set(lifted.values()) - set(ents)))
        self.load_names(ents)
        sessions = {r.run_id for r in rels if r.run_id is not None} | {ents[i].run_id for i in aliases if i in ents and ents[i].run_id is not None}
        cameras = Counter()
        places: dict[str, Counter] = defaultdict(Counter)
        partners: dict[str, dict] = {}
        moves = Counter()
        by_run_moves: dict[tuple, list] = defaultdict(list)
        for r in rels:
            if r.subject_id not in ids:
                continue
            if r.camera_id is not None:
                cameras[r.camera_id] += 1
            if r.relation_type in PLACE_TYPES:
                obj = ents.get(r.object_id)
                if obj is not None:
                    places[r.relation_type][obj.id] += 1
                if r.relation_type in ("MOVED_FROM", "MOVED_TO"):
                    by_run_moves[(r.run_id, r.subject_id, r.end_at)].append(r)
        for r in rels:
            if r.relation_type not in ASSOCIATION_TYPES:
                continue
            other = r.object_id if r.subject_id in ids else r.subject_id
            gid = lifted.get(other, other)
            oe = ents.get(gid)
            if oe is None:
                continue
            key = oe.key if self.visible(oe) else f"redacted:{gid}"
            p = partners.setdefault(key, {"entity": self.entity(oe), "sessions": set(), "types": Counter(), "best_confidence": 0.0})
            if r.run_id is not None:
                p["sessions"].add(r.run_id)
            p["types"][r.relation_type] += 1
            p["best_confidence"] = max(p["best_confidence"], r.confidence)
        for group in by_run_moves.values():
            src = next((g for g in group if g.relation_type == "MOVED_FROM"), None)
            dst = next((g for g in group if g.relation_type == "MOVED_TO"), None)
            if src is not None and dst is not None:
                moves[(src.object_id, dst.object_id)] += 1
        pe = self.g.entities({i for c in places.values() for i in c} | {i for pair in moves for i in pair})

        def top(counter: Counter, n: int = 5) -> list[dict]:
            return [{"entity": self.entity(pe.get(k)), "count": v} for k, v in counter.most_common(n) if pe.get(k) is not None]

        partner_list = []
        for p in partners.values():
            partner_list.append({**p, "sessions": len(p["sessions"]), "types": dict(p["types"])})
        partner_list.sort(key=lambda p: (-p["sessions"], -p["best_confidence"]))
        first = min((e.first_seen for i, e in ents.items() if i in ids and e.first_seen), default=entity.first_seen)
        last = max((e.last_seen for i, e in ents.items() if i in ids and e.last_seen), default=entity.last_seen)
        return {
            "entity": self.entity(entity), "sessions": len(sessions), "tracks": len(aliases) if aliases else (1 if entity.entity_type in E.TRACK_TYPES else 0),
            "first_seen": first, "last_seen": last, "cameras": [{"camera_id": k, "count": v} for k, v in cameras.most_common()],
            "associated": partner_list[:30],
            "entries": top(places["ENTERED"] + places["CROSSED"]), "parking": top(places["PARKED_IN"]), "routes": top(places["USED_ROUTE"]),
            "stays": top(places["REMAINED_IN"]),
            "moves": [{"from": self.entity(pe.get(a)), "to": self.entity(pe.get(b)), "count": n} for (a, b), n in moves.most_common(5) if pe.get(a) and pe.get(b)],
        }


def parse_filters(types: str | None = None, time_from: datetime | None = None, time_to: datetime | None = None, camera_id: int | None = None, experiment_id: int | None = None,
                  run_id: int | None = None, zone_id: str | None = None, min_state: str = "possible", analysis_id: int | None = None, include_superseded: bool = False,
                  last_hours: float | None = None, camera_ids: set[int] | None = None) -> Filters:
    if last_hours:
        from datetime import UTC

        time_from = datetime.now(UTC) - timedelta(hours=float(last_hours))
    tl = [t.strip().upper() for t in (types or "").split(",") if t.strip()] or None
    return Filters(tl, time_from, time_to, camera_id, experiment_id, run_id, zone_id, min_state if min_state in STATES else "possible", analysis_id, include_superseded, camera_ids)
