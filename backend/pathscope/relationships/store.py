"""Persist what the engine produced (one batch at a time).

Entities are merged by key (a track seen again extends its time span),
observations are inserted once, relationships are upserted by uid (an open
relationship is re-sent as it grows and when it closes), correlated events
are inserted once. Evidence is linked through ``relation_support`` by id.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.relationships import entities as E
from pathscope.relationships.models import (
    RelationCorrelated,
    RelationEntity,
    RelationObservation,
    RelationRelationship,
    RelationSupport,
)


def dt(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None


@dataclass
class StoreResult:
    relationships: list[RelationRelationship] = field(default_factory=list)  # new or changed
    relationship_ids: list[int] = field(default_factory=list)
    correlated: list[RelationCorrelated] = field(default_factory=list)
    publish: list[tuple[str, dict, object]] = field(default_factory=list)  # (kind, publish spec, row)


def ensure_entities(session: Session, mentions: list[dict], keys: set[str], context: dict) -> dict[str, int]:
    """Entity ids for these keys, creating or updating rows from the mentions."""
    by_key = {m["key"]: m for m in mentions}
    keys = set(keys) | set(by_key)
    if not keys:
        return {}
    rows = {r.key: r for r in session.scalars(select(RelationEntity).where(RelationEntity.key.in_(keys)))}
    for key in keys:
        m = by_key.get(key)
        row = rows.get(key)
        type_id, ref = E.split_key(key)
        if row is None:
            row = RelationEntity(
                key=key, entity_type=type_id, ref=ref, source=(m or {}).get("source") or "", label=(m or {}).get("label") or E.entity_type(type_id).label,
                secret_label=(m or {}).get("secret_label"), run_id=(m or {}).get("run_id") if type_id in E.TRACK_TYPES else None,
                camera_id=(m or {}).get("camera_id", context.get("camera_id")), experiment_id=(m or {}).get("experiment_id", context.get("experiment_id")),
                meta={}, confidence=None,
            )
            session.add(row)
            rows[key] = row
        if m is None:
            continue
        if m.get("label") and (row.label != m["label"]) and type_id not in E.IDENTITY_TYPES:
            row.label = m["label"]
        if m.get("secret_label"):
            row.secret_label = m["secret_label"]
        if m.get("confidence") is not None:
            row.confidence = m["confidence"]
        if m.get("metadata"):
            row.meta = {**(row.meta or {}), **m["metadata"]}
        fw, lw = dt(m.get("first_wall")), dt(m.get("last_wall"))
        if fw is not None and (row.first_seen is None or fw < row.first_seen):
            row.first_seen = fw
            if type_id in E.TRACK_TYPES:
                row.first_media_s = m.get("first_t")
        if lw is not None and (row.last_seen is None or lw > row.last_seen):
            row.last_seen = lw
            if type_id in E.TRACK_TYPES:
                row.last_media_s = m.get("last_t")
    session.flush()
    return {k: r.id for k, r in rows.items()}


def store_payload(session: Session, analysis_id: int | None, run_id: int | None, experiment_id: int | None, camera_id: int | None, payload: dict) -> StoreResult:
    res = StoreResult()
    context = {"run_id": run_id, "experiment_id": experiment_id, "camera_id": camera_id}
    obs_in = payload.get("observations") or []
    rel_in = payload.get("relationships") or []
    cor_in = payload.get("correlated") or []
    keys: set[str] = set()
    for o in obs_in:
        keys.add(o["subject"])
        if o.get("object"):
            keys.add(o["object"])
    for r in rel_in:
        keys.update((r["subject"], r["object"]))
    for c in cor_in:
        keys.update((c.get("roles") or {}).values())
    ids = ensure_entities(session, payload.get("entities") or [], keys, context)

    # observations (once)
    uids = [o["uid"] for o in obs_in]
    existing_obs = set(session.scalars(select(RelationObservation.uid).where(RelationObservation.uid.in_(uids)))) if uids else set()
    for o in obs_in:
        if o["uid"] in existing_obs:
            continue
        session.add(RelationObservation(
            uid=o["uid"], analysis_id=analysis_id, run_id=run_id, camera_id=camera_id, entity_id=ids[o["subject"]], object_entity_id=ids.get(o.get("object") or ""),
            observation_type=o["type"], media_time_s=o.get("t"), at=dt(o.get("wall")) or datetime.now(UTC), source=o.get("source") or "rgb",
            confidence=o.get("confidence"), value=o.get("value") or {},
        ))
    session.flush()

    # relationships (upsert by uid)
    ruids = [r["uid"] for r in rel_in]
    rows = {r.uid: r for r in session.scalars(select(RelationRelationship).where(RelationRelationship.uid.in_(ruids)))} if ruids else {}
    for r in rel_in:
        row = rows.get(r["uid"])
        new = row is None
        if new:
            row = RelationRelationship(uid=r["uid"], analysis_id=analysis_id, run_id=run_id, experiment_id=experiment_id, camera_id=camera_id,
                                       subject_id=ids[r["subject"]], relation_type=r["type"], object_id=ids[r["object"]])
            session.add(row)
            rows[r["uid"]] = row
        row.start_media_s = r.get("start_t")
        row.end_media_s = r.get("end_t")
        row.start_at = dt(r.get("start_wall")) or row.start_at or datetime.now(UTC)
        row.end_at = dt(r.get("end_wall"))
        row.status = r.get("status") or "open"
        # sensors may have corroborated it since: keep their part of the evidence
        comp = dict(r.get("components") or {})
        if not new and (row.components or {}).get("sensor") is not None and comp.get("sensor") is None:
            from pathscope.relationships.confidence import Components, combine, state_for

            comp["sensor"] = row.components["sensor"]
            c = Components(**{k: comp.get(k) for k in ("tracking", "recognition", "spatial", "temporal", "sensor")}, support=int(comp.get("support") or 1))
            row.confidence = combine(c)
            row.state = state_for(row.confidence)
            row.sources = sorted(set(r.get("sources") or []) | set(row.sources or []))
        else:
            row.confidence = float(r.get("confidence") or 0.0)
            row.state = r.get("state") or "possible"
            row.sources = r.get("sources") or ["rgb"]
        row.components = comp
        row.rule_key = r.get("rule_key") or ""
        row.rule_version = int(r.get("rule_version") or 1)
        row.rule_name = r.get("rule_name") or ""
        row.reason = r.get("reason") or ""
        row.zone_id = r.get("zone_id")
        row.calibration = r.get("calibration") or {}
        row.metrics = r.get("metrics") or {}
        res.relationships.append(row)
        if r.get("publish"):
            res.publish.append(("relationship", r["publish"], row))
    session.flush()
    res.relationship_ids = [rows[u].id for u in ruids if u in rows]
    _link_support(session, [(rows[r["uid"]].id, None, r.get("support") or [], r.get("support_relations") or []) for r in rel_in if r["uid"] in rows])

    # correlated events (once)
    cuids = [c["uid"] for c in cor_in]
    have = set(session.scalars(select(RelationCorrelated.uid).where(RelationCorrelated.uid.in_(cuids)))) if cuids else set()
    links = []
    for c in cor_in:
        if c["uid"] in have:
            continue
        row = RelationCorrelated(
            uid=c["uid"], analysis_id=analysis_id, run_id=run_id, experiment_id=experiment_id, camera_id=camera_id, kind=c.get("kind") or "correlated",
            event_type=c.get("label") or "", label=c.get("label") or "", start_media_s=c.get("start_t"), end_media_s=c.get("end_t"),
            start_at=dt(c.get("start_wall")) or datetime.now(UTC), end_at=dt(c.get("end_wall")), confidence=float(c.get("confidence") or 0.0), state=c.get("state") or "possible",
            description=c.get("description") or "", rule_key=c.get("rule_key") or "", rule_version=int(c.get("rule_version") or 1), rule_name=c.get("rule_name") or "",
            roles={role: ids.get(key) for role, key in (c.get("roles") or {}).items()}, temporal=c.get("temporal") or [], metrics=c.get("metrics") or {},
        )
        session.add(row)
        session.flush()
        res.correlated.append(row)
        links.append((None, row.id, c.get("support") or [], c.get("support_relations") or []))
        if c.get("publish"):
            res.publish.append(("correlated", c["publish"], row))
    _link_support(session, links)
    session.flush()
    return res


def _link_support(session: Session, items: list[tuple[int | None, int | None, list[str], list[str]]]) -> None:
    """Add support links that are not there yet (relationships re-sent as they grow)."""
    if not items:
        return
    obs_uids = {u for _r, _c, obs, _rels in items for u in obs}
    rel_uids = {u for _r, _c, _obs, rels in items for u in rels}
    obs_ids = dict(session.execute(select(RelationObservation.uid, RelationObservation.id).where(RelationObservation.uid.in_(obs_uids))).all()) if obs_uids else {}
    rel_ids = dict(session.execute(select(RelationRelationship.uid, RelationRelationship.id).where(RelationRelationship.uid.in_(rel_uids))).all()) if rel_uids else {}
    rel_owner = [r for r, _c, _o, _s in items if r is not None]
    cor_owner = [c for _r, c, _o, _s in items if c is not None]
    existing: set[tuple] = set()
    if rel_owner:
        for s in session.scalars(select(RelationSupport).where(RelationSupport.relationship_id.in_(rel_owner))):
            existing.add(("r", s.relationship_id, s.observation_id, s.supporting_relationship_id))
    if cor_owner:
        for s in session.scalars(select(RelationSupport).where(RelationSupport.correlated_id.in_(cor_owner))):
            existing.add(("c", s.correlated_id, s.observation_id, s.supporting_relationship_id))
    for rid, cid, obs, rels in items:
        owner = ("r", rid) if rid is not None else ("c", cid)
        for u in obs:
            oid = obs_ids.get(u)
            if oid is None or (*owner, oid, None) in existing:
                continue
            existing.add((*owner, oid, None))
            session.add(RelationSupport(relationship_id=rid, correlated_id=cid, observation_id=oid, role="observation"))
        for u in rels:
            sid = rel_ids.get(u)
            if sid is None or sid == rid or (*owner, None, sid) in existing:
                continue
            existing.add((*owner, None, sid))
            session.add(RelationSupport(relationship_id=rid, correlated_id=cid, supporting_relationship_id=sid, role="relationship"))
