"""The visual graph: a query layer for the interactive graph view.

It is built from the stored entities, observations and relationships on
every request and never stored: the graph view is not a source of truth.

* **Nodes** carry a visual class (track, identity, place, location, camera,
  sensor, event, context) so the view can tell observed objects, recognized
  identities, physical places and sensors apart.
* **Edges** carry a *nature*: ``observed`` (a place event measured directly:
  entered, exited, crossed...), ``identity`` (a recognition result),
  ``inferred`` (a rule's conclusion), ``cross_camera`` (a correlation across
  cameras), ``external`` (an authorized registry) and ``context`` (derived
  from the location model: a track SEEN_AT its camera, a zone INSIDE a
  location). A ``sensor`` flag marks edges that sensor observations support.
* Every edge keeps the intervals of the relationships it merges, so the view
  can show a snapshot at time T, a time range, or replay how the graph grew.
* With ``project`` the tracks of a recognized identity are merged into the
  identity (for viewers allowed to see identities), which is how an
  investigator reads "Employee-017 approached Vehicle ABC12345".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.relationships import entities as E
from pathscope.relationships.graph import IDENTITY_LINKS, Filters, Presenter
from pathscope.relationships.models import RelationEntity, RelationRelationship
from pathscope.relationships.relations import relation_type

SENSOR_SOURCES = {"depth", "radar", "thermal", "lidar", "sensor"}
MAX_INTERVALS = 60


def edge_nature(r: RelationRelationship) -> str:
    if r.relation_type in ("IDENTIFIED_AS", "IDENTIFIED_BY_PLATE", "REGISTERED_AS"):
        return "identity"
    k = r.rule_key or ""
    if k == "crosscam":
        return "cross_camera"
    if k.startswith("registry:"):
        return "external"
    if k.startswith("builtin.places"):
        return "observed"
    return "inferred"


def node_class(e: dict) -> str:
    t = e.get("type")
    if t in E.TRACK_TYPES:
        return "track"
    if t in E.IDENTITY_TYPES:
        return "identity"
    if t in ("zone", "gate", "route"):
        return "place"
    if t == "location":
        return "location"
    if t == "camera":
        return "camera"
    if t == "sensor":
        return "sensor"
    if t == "event":
        return "event"
    return "context"


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d is not None else None


class VisualGraph:
    def __init__(self, session: Session, presenter: Presenter) -> None:
        from pathscope.location.topology import LocationGraph

        self.s = session
        self.p = presenter
        self.g = presenter.g
        self.loc = LocationGraph.load(session)
        self._cams: dict[int, str] | None = None

    def camera_names(self) -> dict[int, str]:
        if self._cams is None:
            from pathscope.db.models import Camera

            self._cams = {c.id: c.name for c in self.s.scalars(select(Camera))}
        return self._cams

    # ------------------------------------------------------------ queries
    def around(self, entity: RelationEntity, f: Filters, depth: int = 1, max_edges: int = 600, project: bool = True, context: bool = True) -> dict:
        ids, aliases = self.p._scope(entity)
        frontier, seen = set(ids), set(ids)
        rels: dict[int, RelationRelationship] = {}
        for _ in range(max(1, min(depth, 3))):
            batch = self.g.relationships(f, frontier, limit=max_edges)
            nxt: set[int] = set()
            for r in batch:
                rels[r.id] = r
                for x in (r.subject_id, r.object_id):
                    if x not in seen:
                        seen.add(x)
                        nxt.add(x)
                if len(rels) >= max_edges:
                    break
            frontier = nxt
            if not frontier or len(rels) >= max_edges:
                break
        out = self._build(list(rels.values()), project, context, center=entity, aliases=set(aliases))
        out["truncated"] = len(rels) >= max_edges
        return out

    def scope(self, f: Filters, max_edges: int = 800, project: bool = True, context: bool = True) -> dict:
        rels = self.g.relationships(f, None, limit=max_edges)
        out = self._build(rels, project, context)
        out["truncated"] = len(rels) >= max_edges
        return out

    def path(self, a: RelationEntity, b: RelationEntity, f: Filters, max_depth: int = 4, project: bool = True) -> dict:
        """Shortest chain of relationships between two entities (identities through their tracks)."""
        starts, _ = self.p._scope(a)
        goals, _ = self.p._scope(b)
        parent: dict[int, tuple[int | None, RelationRelationship | None]] = {x: (None, None) for x in starts}
        frontier = set(starts)
        hit: int | None = next(iter(starts & goals), None)
        depth = 0
        while hit is None and frontier and depth < max(1, min(max_depth, 6)):
            depth += 1
            nxt: set[int] = set()
            for r in self.g.relationships(f, frontier, limit=5000):
                for x, y in ((r.subject_id, r.object_id), (r.object_id, r.subject_id)):
                    if x in frontier and y not in parent:
                        parent[y] = (x, r)
                        nxt.add(y)
            hit = next((x for x in sorted(nxt) if x in goals), None)
            frontier = nxt
        if hit is None:
            return {"found": False, "nodes": [], "edges": [], "path_nodes": [], "path_edges": [], "depth": depth}
        chain: list[RelationRelationship] = []
        cur: int | None = hit
        while cur is not None:
            prev, r = parent[cur]
            if r is not None:
                chain.append(r)
            cur = prev
        chain.reverse()
        out = self._build(chain, project, context=False, center=a)
        order = [e["id"] for e in out["edges"]]
        out.update({"found": True, "path_edges": order, "path_nodes": [n["node"] for n in out["nodes"]], "depth": depth})
        return out

    # ------------------------------------------------------------ building
    def _node(self, e: RelationEntity) -> dict:
        d = self.p.entity(e)
        node = d["key"] or f"redacted-{e.id}"
        out = {**d, "node": node, "klass": node_class(d), "expandable": bool(d["key"])}
        if not d.get("redacted"):
            nid = self.loc.resolve_key(e.key)
            if nid is not None:
                out["location"] = {"id": nid, "name": self.loc.nodes[nid].name, "path": self.loc.path_label(nid)}
            if e.entity_type == "camera":
                try:
                    out["label"] = self.camera_names().get(int(e.ref), out["label"])
                except ValueError:
                    pass
        return out

    def _synthetic(self, key: str, label: str, type_id: str, extra: dict | None = None) -> dict:
        et = E.entity_type(type_id)
        d = {"id": None, "key": key, "type": type_id, "type_label": et.label, "category": et.category, "sensitive": False, "label": label, "redacted": False}
        return {**d, "node": key, "klass": node_class(d), "expandable": False, **(extra or {})}

    def _build(self, rels: list[RelationRelationship], project: bool, context: bool, center: RelationEntity | None = None, aliases: set[int] | None = None) -> dict:
        aliases = aliases or set()
        project = project and self.p.identities
        ent_ids = {x for r in rels for x in (r.subject_id, r.object_id)} | ({center.id} if center else set())
        ents = self.g.entities(ent_ids)
        lifted = self.g.identities_of({i for i, e in ents.items() if e.entity_type in E.TRACK_TYPES}) if project else {}
        ents.update(self.g.entities(set(lifted.values()) - set(ents)))
        self.p.load_names(ents)

        def node_of(eid: int) -> int:
            if center is not None and eid in aliases and project:
                return center.id
            li = lifted.get(eid)
            return li if (li is not None and self.p.visible(ents[li])) else eid

        nodes: dict[str, dict] = {}
        edges: dict[tuple, dict] = {}
        by_id: dict[int, str] = {}

        def add_node(eid: int) -> str:
            if eid in by_id:
                return by_id[eid]
            d = self._node(ents[eid])
            nodes.setdefault(d["node"], d)
            by_id[eid] = d["node"]
            return d["node"]

        def add_edge(a: str, b: str, rtype: str, nature: str, rid: int | None, start, end, state: str, conf: float, sensor: bool = False, derived: bool = False,
                     media: tuple | None = None, run_id: int | None = None, camera_id: int | None = None, merged: bool = False) -> None:
            k = (a, b, rtype)
            e = edges.get(k)
            if e is None:
                rt = relation_type(rtype)
                e = edges[k] = {"id": f"{a}>{b}>{rtype}", "source": a, "target": b, "type": rtype, "label": rt.label if rt else rtype.lower().replace("_", " "),
                                "nature": nature, "sensor": False, "derived": derived, "count": 0, "best_confidence": 0.0, "state": state, "ids": [], "intervals": [],
                                "first_at": None, "last_at": None, "merged": False}
            e["count"] += 1
            e["sensor"] = e["sensor"] or sensor
            e["merged"] = e["merged"] or merged
            if rid is not None:
                e["ids"].append(rid)
            if conf >= e["best_confidence"]:
                e["best_confidence"], e["state"] = round(conf, 4), state
            if len(e["intervals"]) < MAX_INTERVALS:
                e["intervals"].append({"id": rid, "start": _iso(start), "end": _iso(end), "start_media_s": media[0] if media else None, "end_media_s": media[1] if media else None,
                                       "state": state, "confidence": round(conf, 4), "run_id": run_id, "camera_id": camera_id})
            s_iso, e_iso = _iso(start), _iso(end or start)
            if s_iso and (e["first_at"] is None or s_iso < e["first_at"]):
                e["first_at"] = s_iso
            if e_iso and (e["last_at"] is None or e_iso > e["last_at"]):
                e["last_at"] = e_iso

        for r in rels:
            if project and r.relation_type in IDENTITY_LINKS and lifted.get(r.subject_id) is not None:
                continue  # merged into the identity node
            if center is not None and project and r.relation_type in IDENTITY_LINKS and r.subject_id in aliases:
                continue
            a, b = node_of(r.subject_id), node_of(r.object_id)
            if a == b or a not in ents or b not in ents:
                continue
            na, nb = add_node(a), add_node(b)
            add_edge(na, nb, r.relation_type, edge_nature(r), r.id, r.start_at, r.end_at, r.state, r.confidence,
                     sensor=bool(set(r.sources or []) & SENSOR_SOURCES) or (r.components or {}).get("sensor") is not None,
                     media=(r.start_media_s, r.end_media_s), run_id=r.run_id, camera_id=r.camera_id, merged=(a != r.subject_id or b != r.object_id))
        if center is not None:
            add_node(center.id)
        if context:
            self._context(ents, by_id, nodes, add_edge, node_of)
        times = [t for e in edges.values() for t in (e["first_at"], e["last_at"]) if t]
        counts: dict[str, int] = {}
        for e in edges.values():
            counts[e["nature"]] = counts.get(e["nature"], 0) + 1
        return {"center": by_id.get(center.id) if center is not None else None, "nodes": list(nodes.values()), "edges": list(edges.values()),
                "time_range": {"start": min(times) if times else None, "end": max(times) if times else None}, "counts": counts, "projected": project}

    def _context(self, ents: dict[int, RelationEntity], by_id: dict[int, str], nodes: dict[str, dict], add_edge, node_of) -> None:
        """Derived context: tracks SEEN_AT their camera, scene places and cameras INSIDE their location."""
        cams = self.camera_names()

        def camera_node(cid: int) -> str:
            key = E.camera_key(cid)
            if key not in nodes:
                ex = {"location": None}
                cn = self.loc.by_camera.get(cid)
                if cn is not None:
                    ex["location"] = {"id": cn, "name": self.loc.nodes[cn].name, "path": self.loc.path_label(cn)}
                nodes[key] = self._synthetic(key, cams.get(cid, f"Camera {cid}"), "camera", {"camera_id": cid, **ex})
            return key

        def location_node(nid: int) -> str:
            key = E.location_key(nid)
            if key not in nodes:
                n = self.loc.nodes[nid]
                nodes[key] = self._synthetic(key, n.name, "location", {"location": {"id": nid, "name": n.name, "path": self.loc.path_label(nid)}, "meta": {"kind": n.kind}})
            return key

        for eid, e in list(ents.items()):
            if e.entity_type in E.TRACK_TYPES and e.camera_id is not None:
                src = by_id.get(node_of(eid))  # a merged track speaks for its identity
                d = nodes.get(src) if src is not None else None
                if d is None or d.get("redacted"):
                    continue
                add_edge(src, camera_node(e.camera_id), "SEEN_AT", "context", None, e.first_seen, e.last_seen, "confirmed", float(e.confidence or 0.9), derived=True,
                         media=(e.first_media_s, e.last_media_s), run_id=e.run_id, camera_id=e.camera_id)
            elif e.entity_type in ("zone", "gate", "route") and eid in by_id:
                nid = self.loc.resolve_key(e.key)
                if nid is not None:
                    add_edge(by_id[eid], location_node(nid), "INSIDE", "context", None, None, None, "confirmed", 1.0, derived=True)
        for key, d in list(nodes.items()):
            if d.get("klass") == "camera" and d.get("camera_id") is None and d.get("key"):
                try:
                    d["camera_id"] = int(E.split_key(key)[1])
                except ValueError:
                    continue
            if d.get("klass") == "camera" and d.get("camera_id") is not None:
                cn = self.loc.by_camera.get(d["camera_id"])
                if cn is not None and self.loc.nodes[cn].parent_id is not None:
                    add_edge(key, location_node(self.loc.nodes[cn].parent_id), "INSIDE", "context", None, None, None, "confirmed", 1.0, derived=True)

