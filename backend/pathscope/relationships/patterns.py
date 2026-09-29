"""Deviations from configured and learned relationship patterns.

The anomaly side of the relationship graph. It reports *observable
deviation* only, never intent:

* **Configured expectations** (per experiment): "vehicles of group Delivery
  are expected in Loading Zone only" -> a registered delivery vehicle
  ENTERED Employee Parking is reported as outside the expectation.
* **Learned history** (per identity): after at least ``pattern_min_sessions``
  earlier sessions, a place the identity used in fewer than
  ``pattern_rare_share`` of them ("entered Gate C, used in 0 of 12 earlier
  sessions; usual: Gate A, 11 of 12"), or a partner it was never associated
  with before ("associated with a vehicle not seen with it in 12 earlier
  sessions").

Deviations are stored as correlated events of kind ``deviation`` that point
to the relationship they are about. Their text never contains a name; roles
carry entity ids, so names appear only for viewers allowed to see them.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.domain.entities import STATUS_RECOGNIZED, EntityRef, anonymous_entity
from pathscope.relationships import entities as E
from pathscope.relationships.confidence import Components, at_least, combine, state_for
from pathscope.relationships.graph import Filters, SqlGraph
from pathscope.relationships.models import (
    RelationAnalysis,
    RelationCorrelated,
    RelationEntity,
    RelationRelationship,
)
from pathscope.relationships.observations import new_uid
from pathscope.relationships.relations import relation_type
from pathscope.relationships.rules import RelationExperimentSettings

PLACE_KINDS = ("ENTERED", "CROSSED", "USED_ROUTE", "PARKED_IN", "REMAINED_IN")
PARTNER_KINDS = ("ASSOCIATED_WITH", "ARRIVED_WITH", "DEPARTED_WITH", "TRAVELLED_WITH", "ENTERED_VEHICLE", "EXITED_VEHICLE")


def _place_id(rel: RelationRelationship, ents: dict[int, RelationEntity]) -> str | None:
    if rel.zone_id:
        return rel.zone_id
    obj = ents.get(rel.object_id)
    if obj is not None and obj.entity_type in E.PLACE_TYPES:
        return obj.ref.split(".", 1)[-1]
    return None


def _entity_ref(track: RelationEntity, identity: RelationEntity | None) -> EntityRef:
    cls = (track.meta or {}).get("object_class", "")
    tid = E.parse_track_ref(track.ref)
    track_id = tid[1] if tid else 0
    if identity is None:
        return anonymous_entity(track_id, cls, settled=True)
    if identity.entity_type == "recognized_person":
        return EntityRef("enrolled_person", track_id, cls, identity_id=identity.ref, status=STATUS_RECOGNIZED, settled=True, confidence=identity.confidence)
    if identity.entity_type == "registered_vehicle":
        return EntityRef("registered_vehicle", track_id, cls, vehicle_id=identity.ref, groups=list((identity.meta or {}).get("groups") or []), status=STATUS_RECOGNIZED, settled=True)
    return EntityRef("recognized_plate", track_id, cls, plate=identity.secret_label, status=STATUS_RECOGNIZED, settled=True)


def _generic(e: RelationEntity | None) -> str:
    if e is None:
        return "?"
    if E.is_sensitive(e.entity_type):
        return E.entity_type(e.entity_type).label
    return e.label or E.entity_type(e.entity_type).label


def evaluate(session: Session, analysis: RelationAnalysis, settings: RelationExperimentSettings, relationship_ids: list[int] | None = None) -> list[dict]:
    """Deviation records (engine 'correlated' dicts, kind deviation) for this analysis's relationships."""
    if not (settings.expectations or settings.learn_patterns):
        return []
    R = RelationRelationship
    q = select(R).where(R.analysis_id == analysis.id, R.relation_type.in_(PLACE_KINDS + PARTNER_KINDS))
    if relationship_ids is not None:
        if not relationship_ids:
            return []
        q = q.where(R.id.in_(relationship_ids))
    rels = [r for r in session.scalars(q) if at_least(r.state, "likely") and (r.status == "closed" or r.relation_type in ("PARKED_IN", "REMAINED_IN"))]
    if not rels:
        return []
    done = {(c.metrics or {}).get("relationship_id") for c in session.scalars(select(RelationCorrelated).where(RelationCorrelated.analysis_id == analysis.id, RelationCorrelated.kind == "deviation"))}
    rels = [r for r in rels if r.id not in done]
    if not rels:
        return []
    g = SqlGraph(session)
    ents = g.entities({x for r in rels for x in (r.subject_id, r.object_id)})
    tracks = {i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}
    lifted = g.identities_of(tracks)
    ents.update(g.entities(set(lifted.values()) - set(ents)))
    out: list[dict] = []
    history_cache: dict[int, dict] = {}
    for r in rels:
        subj = ents.get(r.subject_id)
        if subj is None or subj.entity_type not in E.TRACK_TYPES:
            continue
        ident = ents.get(lifted.get(subj.id, -1))
        ref = _entity_ref(subj, ident)
        who = _generic(ident) if ident is not None else subj.label
        # ---- configured expectations
        if r.relation_type in PLACE_KINDS:
            place = _place_id(r, ents)
            obj = ents.get(r.object_id)
            for ex in settings.expectations:
                if not ex.enabled or ex.relation != r.relation_type or place is None:
                    continue
                if not ex.subject.class_ok(ref.object_class) or ex.subject.evaluate(ref) is not True:
                    continue
                outside = bool(ex.allowed_places) and place not in ex.allowed_places
                forbidden = place in ex.forbidden_places
                if not (outside or forbidden):
                    continue
                verb = relation_type(r.relation_type).label if relation_type(r.relation_type) else r.relation_type
                text = f"{who} {verb} {_generic(obj)}, " + ("which the expectation" if forbidden else "outside the places the expectation") + f" '{ex.name or ex.id}' " + ("lists as not expected." if forbidden else "allows.")
                out.append(_deviation(r, subj, ident, obj, "expectation", text, r.confidence, {"expectation": ex.id, "place": place}))
                break
        # ---- learned history of the identity
        if not settings.learn_patterns or ident is None:
            continue
        hist = history_cache.get(ident.id)
        if hist is None:
            hist = history_cache[ident.id] = _history(session, g, ident, analysis.run_id)
        if r.relation_type in PLACE_KINDS:
            per_type = hist["places"].get(r.relation_type)
            n = hist["place_sessions"].get(r.relation_type, 0)
            place_entity = r.object_id
            if per_type is None or n < settings.pattern_min_sessions:
                continue
            used = per_type.get(place_entity, 0)
            if used / n >= settings.pattern_rare_share:
                continue
            usual_id, usual_n = per_type.most_common(1)[0] if per_type else (None, 0)
            usual = session.get(RelationEntity, usual_id) if usual_id else None
            verb = relation_type(r.relation_type).label if relation_type(r.relation_type) else r.relation_type
            text = f"{who} {verb} {_generic(ents.get(r.object_id))}; in {n} earlier sessions it did so in {used}" + (f" (usually {_generic(usual)}, {usual_n} of {n})." if usual else ".")
            out.append(_deviation(r, subj, ident, ents.get(r.object_id), "history", text, r.confidence * min(1.0, n / (settings.pattern_min_sessions * 2)),
                                  {"sessions": n, "used": used, "usual_entity_id": usual_id, "usual_count": usual_n}))
        elif r.relation_type in PARTNER_KINDS:
            other_id = r.object_id if r.subject_id == subj.id else r.subject_id
            other_ident = lifted.get(other_id)
            other = ents.get(other_ident) if other_ident else None
            if other is None:
                continue  # an anonymous partner cannot be compared with history
            n = hist["partner_sessions"]
            if n < settings.pattern_min_sessions or hist["partners"].get(other.id, 0) > 0:
                continue
            verb = relation_type(r.relation_type).label if relation_type(r.relation_type) else r.relation_type
            text = f"{who} {verb} {_generic(other)}, which it was not observed with in {n} earlier sessions."
            out.append(_deviation(r, subj, ident, other, "history", text, r.confidence * min(1.0, n / (settings.pattern_min_sessions * 2)), {"sessions": n, "partner_entity_id": other.id}))
    return out


def _history(session: Session, g: SqlGraph, ident: RelationEntity, exclude_run: int) -> dict:
    """Earlier sessions of one identity: places per relation type and partners."""
    aliases = g.aliases(ident)
    ids = set(aliases)
    rels = [r for r in g.relationships(Filters(min_state="likely"), ids, limit=20000) if r.run_id != exclude_run]
    places: dict[str, Counter] = defaultdict(Counter)
    place_runs: dict[str, set] = defaultdict(set)
    place_seen: dict[tuple[str, int], set] = defaultdict(set)
    partner_runs: set = set()
    partner_ids: Counter = Counter()
    others = {r.object_id if r.subject_id in ids else r.subject_id for r in rels if r.relation_type in PARTNER_KINDS}
    lifted = g.identities_of(others)
    for r in rels:
        if r.relation_type in PLACE_KINDS and r.subject_id in ids:
            place_runs[r.relation_type].add(r.run_id)
            place_seen[(r.relation_type, r.object_id)].add(r.run_id)
        elif r.relation_type in PARTNER_KINDS:
            partner_runs.add(r.run_id)
            other = r.object_id if r.subject_id in ids else r.subject_id
            partner_ids[lifted.get(other, other)] += 1
    for (rt, oid), runs in place_seen.items():
        places[rt][oid] = len(runs)
    return {"places": places, "place_sessions": {k: len(v) for k, v in place_runs.items()}, "partners": partner_ids, "partner_sessions": len(partner_runs)}


def _deviation(r: RelationRelationship, subj: RelationEntity, ident: RelationEntity | None, other: RelationEntity | None, basis: str, text: str, strength: float, metrics: dict) -> dict:
    conf = combine(Components(temporal=1.0, spatial=max(0.05, min(1.0, strength)), support=4))
    roles = {"subject": subj.key}
    if ident is not None:
        roles["identity"] = ident.key
    if other is not None:
        roles["other"] = other.key
    return {
        "uid": new_uid(), "kind": "deviation", "label": "Pattern deviation" if basis == "history" else "Outside expectation",
        "rule_key": f"patterns.{basis}", "rule_version": 1, "rule_name": "Learned history" if basis == "history" else "Configured expectation",
        "start_t": r.start_media_s or 0.0, "end_t": r.end_media_s if r.end_media_s is not None else (r.start_media_s or 0.0),
        "start_wall": r.start_at.timestamp() if r.start_at else None, "end_wall": (r.end_at or r.start_at).timestamp() if (r.end_at or r.start_at) else None,
        "confidence": conf, "state": state_for(conf), "roles": roles, "description": text, "support": [], "support_relations": [r.uid], "temporal": [],
        "metrics": {**metrics, "relationship_id": r.id, "relation": r.relation_type, "basis": basis},
    }
