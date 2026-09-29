"""The location graph and what the correlation engine asks of it.

``LocationGraph`` is an in-memory view of the location tables (small: a site
has tens to hundreds of nodes). It answers:

* hierarchy: ancestors, "Site / Building / Floor / Corridor B" paths, the
  layout frame of a node, the cameras inside a node (site and location
  filters);
* Location Resolution: which location node a camera's scene zone is, which
  places a camera covers;
* plausibility of a move between two cameras: a direct camera link, or the
  shortest traversable path between the places they cover, with the
  expected travel time (configured per link, or estimated from the plan's
  metric distances and a speed range, or unknown) and whether the path is
  only possible against a one-way link.

Nothing here reads the relationship tables: the Location Engine is context
the correlation engine consumes.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.location.coordinates import Distance, centroid, haversine
from pathscope.location.models import LocationLink, LocationNode, LocationZoneLink

# kind -> (label, group); groups: org, building, road, place, device
NODE_KINDS: dict[str, tuple[str, str]] = {
    "organization": ("Organization", "org"),
    "site": ("Site", "org"),
    "building": ("Building", "building"),
    "floor": ("Floor", "building"),
    "area": ("Area", "place"),
    "room": ("Room", "place"),
    "corridor": ("Corridor", "place"),
    "entrance": ("Entrance", "place"),
    "gate": ("Gate", "place"),
    "zone": ("Zone", "place"),
    "parking": ("Parking area", "place"),
    "loading": ("Loading area", "place"),
    "stairs": ("Stairs / lift", "place"),
    "road_network": ("Road network", "road"),
    "road": ("Road", "road"),
    "junction": ("Junction", "road"),
    "camera": ("Camera", "device"),
    "sensor": ("Sensor", "device"),
    "other": ("Other", "place"),
}
LAYOUT_KINDS = {"organization", "site", "building", "floor", "area", "road_network", "parking"}

LINK_KINDS: dict[str, str] = {
    "CONNECTED_TO": "People or vehicles can move between the two (both ways unless one-way).",
    "ADJACENT_TO": "Next to each other with direct passage (neighbouring cameras or areas).",
    "LEADS_TO": "The first leads into the second (a door, a gate, a ramp).",
    "VISIBLE_FROM": "The place is covered by the camera.",
    "ABOVE": "Vertically above (floors); not a passage by itself.",
    "BELOW": "Vertically below; not a passage by itself.",
}
TRAVERSABLE = frozenset({"CONNECTED_TO", "ADJACENT_TO", "LEADS_TO"})

# speed ranges (m/s) used to estimate a travel time from a metric distance
SPEEDS = {"person": (0.4, 2.5), "vehicle": (1.0, 25.0), "other": (0.3, 25.0)}


@dataclass
class Travel:
    """Expected travel time between two points of the location graph."""

    min_s: float | None
    max_s: float | None
    source: str  # link | path | distance | partial | unknown

    @property
    def known(self) -> bool:
        return self.min_s is not None and self.max_s is not None and self.source != "unknown"


@dataclass
class TopologyEvidence:
    kind: str  # direct | overlap | path | unconnected | no_topology
    path: list[int] = field(default_factory=list)
    hops: int | None = None
    travel: Travel = field(default_factory=lambda: Travel(None, None, "unknown"))
    wrong_way: bool = False
    via: list[int] = field(default_factory=list)  # places between the cameras (for MOVED_THROUGH)
    note: str = ""

    @property
    def certainty(self) -> float:
        """How strongly the topology supports the move (the spatial component)."""
        if self.kind in ("direct", "overlap"):
            return 0.3 if self.wrong_way else 0.98
        if self.kind == "path":
            return 0.3 if self.wrong_way else max(0.72, 0.96 - 0.04 * max(0, (self.hops or 1) - 1))
        if self.kind == "no_topology":
            return 0.6
        return 0.35

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "hops": self.hops, "wrong_way": self.wrong_way, "via": self.via, "note": self.note,
                "travel": {"min_s": self.travel.min_s, "max_s": self.travel.max_s, "source": self.travel.source}}


def speed_class(object_class: str) -> str:
    from pathscope.domain.scene import VEHICLE_CLASSES

    if object_class == "person":
        return "person"
    return "vehicle" if object_class in VEHICLE_CLASSES else "other"


class LocationGraph:
    def __init__(self, nodes: list[LocationNode], links: list[LocationLink], zone_links: list[LocationZoneLink]) -> None:
        self.nodes: dict[int, LocationNode] = {n.id: n for n in nodes}
        self.links: list[LocationLink] = list(links)
        self.children: dict[int | None, list[int]] = {}
        for n in nodes:
            self.children.setdefault(n.parent_id, []).append(n.id)
        self.by_camera: dict[int, int] = {n.camera_id: n.id for n in nodes if n.camera_id is not None}
        self.by_sensor: dict[str, int] = {n.sensor_id: n.id for n in nodes if n.sensor_id}
        self.zones: dict[tuple[int, str], int] = {(z.camera_id, z.object_id): z.node_id for z in zone_links if z.node_id in self.nodes}
        self._move: dict[int, list[tuple[int, LocationLink, bool]]] = {}  # node -> [(next, link, forward)]
        self._cover: dict[int, set[int]] = {}
        for lk in self.links:
            if lk.source_id not in self.nodes or lk.target_id not in self.nodes:
                continue
            if lk.kind in TRAVERSABLE:
                self._move.setdefault(lk.source_id, []).append((lk.target_id, lk, True))
                self._move.setdefault(lk.target_id, []).append((lk.source_id, lk, False))
            elif lk.kind == "VISIBLE_FROM":
                cam, place = (lk.target_id, lk.source_id) if self.nodes[lk.target_id].kind == "camera" else (lk.source_id, lk.target_id)
                self._cover.setdefault(cam, set()).add(place)
        for (cam_id, _oid), nid in self.zones.items():
            cn = self.by_camera.get(cam_id)
            if cn is not None:
                self._cover.setdefault(cn, set()).add(nid)

    @classmethod
    def load(cls, session: Session) -> LocationGraph:
        return cls(list(session.scalars(select(LocationNode))), list(session.scalars(select(LocationLink))), list(session.scalars(select(LocationZoneLink))))

    @property
    def empty(self) -> bool:
        return not self.nodes

    # ------------------------------------------------------------------ hierarchy
    def ancestors(self, node_id: int) -> list[int]:
        """Root first, the node itself last."""
        out: list[int] = []
        seen: set[int] = set()
        cur: int | None = node_id
        while cur is not None and cur in self.nodes and cur not in seen:
            seen.add(cur)
            out.append(cur)
            cur = self.nodes[cur].parent_id
        return list(reversed(out))

    def path_label(self, node_id: int | None, skip_root: bool = False) -> str:
        if node_id is None or node_id not in self.nodes:
            return ""
        chain = self.ancestors(node_id)
        if skip_root and len(chain) > 1:
            chain = chain[1:]
        return " / ".join(self.nodes[i].name for i in chain)

    def frame(self, node_id: int) -> int | None:
        """The node whose layout gives this node's coordinates (nearest ancestor with a layout)."""
        n = self.nodes.get(node_id)
        cur = n.parent_id if n else None
        while cur is not None and cur in self.nodes:
            if self.nodes[cur].layout:
                return cur
            cur = self.nodes[cur].parent_id
        return None

    def subtree(self, node_id: int) -> set[int]:
        out: set[int] = set()
        stack = [node_id]
        while stack:
            cur = stack.pop()
            if cur in out:
                continue
            out.add(cur)
            stack.extend(self.children.get(cur, []))
        return out

    def cameras_in(self, node_id: int) -> set[int]:
        return {self.nodes[i].camera_id for i in self.subtree(node_id) if self.nodes[i].camera_id is not None}

    def site_of(self, node_id: int | None) -> int | None:
        if node_id is None:
            return None
        for i in self.ancestors(node_id):
            if self.nodes[i].kind == "site":
                return i
        chain = self.ancestors(node_id)
        return chain[0] if chain else None

    def lineage_names(self, node_id: int | None) -> list[dict]:
        if node_id is None or node_id not in self.nodes:
            return []
        return [{"id": i, "name": self.nodes[i].name, "kind": self.nodes[i].kind} for i in self.ancestors(node_id)]

    # ------------------------------------------------------------------ resolution
    def resolve(self, camera_id: int | None, object_id: str | None) -> int | None:
        if camera_id is None or not object_id:
            return None
        return self.zones.get((int(camera_id), str(object_id)))

    def resolve_key(self, entity_key: str | None) -> int | None:
        """``zone:c3.z_gate`` / ``gate:c3.l1`` / ``route:c3.r1`` / ``camera:3`` / ``location:12`` -> node id."""
        if not entity_key:
            return None
        t, _, ref = entity_key.partition(":")
        if t == "location":
            try:
                nid = int(ref)
            except ValueError:
                return None
            return nid if nid in self.nodes else None
        if t == "camera":
            try:
                return self.by_camera.get(int(ref))
            except ValueError:
                return None
        if t in ("zone", "gate", "route") and ref.startswith("c") and "." in ref:
            cam, _, oid = ref[1:].partition(".")
            try:
                return self.resolve(int(cam), oid)
            except ValueError:
                return None
        return None

    def coverage(self, camera_id: int) -> set[int]:
        """Places the camera sees; a camera with none configured stands for its parent area."""
        cn = self.by_camera.get(camera_id)
        if cn is None:
            return set()
        cov = set(self._cover.get(cn, set()))
        if not cov and self.nodes[cn].parent_id is not None:
            cov.add(self.nodes[cn].parent_id)
        return cov

    # ------------------------------------------------------------------ coordinates
    def position(self, node_id: int) -> tuple[float, float] | None:
        n = self.nodes.get(node_id)
        if n is None:
            return None
        if n.x is not None and n.y is not None:
            return float(n.x), float(n.y)
        return centroid(n.shape or [])

    def distance(self, a: int, b: int) -> Distance | None:
        na, nb = self.nodes.get(a), self.nodes.get(b)
        if na is None or nb is None:
            return None
        fa, fb = self.frame(a), self.frame(b)
        pa, pb = self.position(a), self.position(b)
        if fa is not None and fa == fb and pa and pb:
            unit = ((self.nodes[fa].layout or {}).get("unit") or "units")
            return Distance(math.hypot(pa[0] - pb[0], pa[1] - pb[1]), "m" if unit == "m" else "units", "plan")
        if None not in (na.lat, na.lon, nb.lat, nb.lon):
            return Distance(haversine(na.lat, na.lon, nb.lat, nb.lon), "m", "gps")
        return None

    def link_travel(self, lk: LocationLink, a: int, b: int, speed: str) -> Travel:
        if lk.travel_min_s is not None or lk.travel_max_s is not None:
            lo = lk.travel_min_s if lk.travel_min_s is not None else 0.0
            hi = lk.travel_max_s if lk.travel_max_s is not None else max(lo * 3.0, lo + 60.0)
            return Travel(float(lo), float(hi), "link")
        d = Distance(lk.distance, "m", "link") if lk.distance is not None else self.distance(a, b)
        if d is not None and d.metres is not None:
            vmin, vmax = SPEEDS.get(speed, SPEEDS["other"])
            return Travel(round(d.metres / vmax, 1), round(d.metres / vmin + 5.0, 1), "distance")
        return Travel(None, None, "unknown")

    # ------------------------------------------------------------------ plausibility
    def _direct(self, a: int, b: int) -> tuple[LocationLink, bool] | None:
        for nxt, lk, forward in self._move.get(a, []):
            if nxt == b:
                return lk, forward
        return None

    def _search(self, starts: set[int], goals: set[int], respect_one_way: bool, max_hops: int = 12) -> list[tuple[int, LocationLink | None]] | None:
        """Fewest-hops path from any start to any goal: [(node, link used to reach it)]."""
        if not starts or not goals:
            return None
        prev: dict[int, tuple[int | None, LocationLink | None]] = {s: (None, None) for s in starts}
        depth = {s: 0 for s in starts}
        q = deque(sorted(starts))
        while q:
            cur = q.popleft()
            if cur in goals:
                out: list[tuple[int, LocationLink | None]] = []
                node: int | None = cur
                while node is not None:
                    p, lk = prev[node]
                    out.append((node, lk))
                    node = p
                return list(reversed(out))
            if depth[cur] >= max_hops:
                continue
            for nxt, lk, forward in self._move.get(cur, []):
                if respect_one_way and lk.one_way and not forward:
                    continue
                if nxt not in prev:
                    prev[nxt] = (cur, lk)
                    depth[nxt] = depth[cur] + 1
                    q.append(nxt)
        return None

    def _path_travel(self, path: list[tuple[int, LocationLink | None]], speed: str) -> Travel:
        lo, hi, sources = 0.0, 0.0, set()
        for i in range(1, len(path)):
            node, lk = path[i]
            if lk is None:
                continue
            tr = self.link_travel(lk, path[i - 1][0], node, speed)
            sources.add(tr.source)
            if tr.known:
                lo += tr.min_s or 0.0
                hi += tr.max_s or 0.0
            else:
                hi = math.inf
        if not sources:
            return Travel(0.0, 0.0, "path")
        if hi == math.inf:
            return Travel(lo if lo > 0 else None, None, "partial" if lo > 0 else "unknown")
        if sources == {"link"}:
            return Travel(round(lo, 1), round(hi, 1), "path" if len(path) > 2 else "link")
        return Travel(round(lo, 1), round(hi, 1), "distance" if "distance" in sources and "link" not in sources else "path")

    def camera_transition(self, cam_a: int | None, cam_b: int | None, from_node: int | None = None, to_node: int | None = None, object_class: str = "person") -> TopologyEvidence:
        """How the location graph explains a move from camera A to camera B."""
        speed = speed_class(object_class)
        if cam_a is None or cam_b is None:
            return TopologyEvidence("no_topology", note="camera not known")
        na, nb = self.by_camera.get(cam_a), self.by_camera.get(cam_b)
        if na is None or nb is None:
            missing = [str(c) for c, n in ((cam_a, na), (cam_b, nb)) if n is None]
            return TopologyEvidence("no_topology", note=f"camera {', '.join(missing)} not placed in the location model")
        d = self._direct(na, nb)
        if d is not None:
            lk, forward = d
            tr = self.link_travel(lk, na, nb, speed)
            via = [x for x in (lk.via_id,) if x is not None]
            return TopologyEvidence("overlap" if lk.overlap else "direct", path=[na, *via, nb], hops=1, travel=tr, wrong_way=bool(lk.one_way and not forward), via=via,
                                    note="fields of view overlap" if lk.overlap else "directly connected cameras")
        attempts: list[tuple[set[int], set[int]]] = []
        precise_s = {from_node} if from_node is not None else set()
        precise_g = {to_node} if to_node is not None else set()
        wide_s = {na} | self.coverage(cam_a)
        wide_g = {nb} | self.coverage(cam_b)
        if precise_s or precise_g:
            attempts.append((precise_s or wide_s, precise_g or wide_g))
        attempts.append((wide_s, wide_g))
        for one_way in (True, False):
            for starts, goals in attempts:
                p = self._search(starts, goals, respect_one_way=one_way)
                if p is None:
                    continue
                via: list[int] = []
                for n, lk in p:
                    for x in ((lk.via_id if lk is not None else None), n):
                        if x is not None and x not in (na, nb) and x in self.nodes and self.nodes[x].kind != "camera" and x not in via:
                            via.append(x)
                places = f"{len(via)} place{'s' if len(via) != 1 else ''}"
                note = (f"connected through {places}" if via else "same place") if one_way else "only possible against a one-way link"
                return TopologyEvidence("path", path=[na, *[n for n, _ in p if n not in (na, nb)], nb], hops=max(1, len(p) - 1), travel=self._path_travel(p, speed),
                                        wrong_way=not one_way, via=via, note=note)
        return TopologyEvidence("unconnected", path=[na, nb], note="no connection between these cameras in the location model")

    # ------------------------------------------------------------------ export
    def node_dict(self, n: LocationNode) -> dict:
        label, group = NODE_KINDS.get(n.kind, (n.kind.capitalize(), "place"))
        return {
            "id": n.id, "parent_id": n.parent_id, "project_id": n.project_id, "kind": n.kind, "kind_label": label, "group": group, "name": n.name, "description": n.description,
            "camera_id": n.camera_id, "sensor_id": n.sensor_id, "x": n.x, "y": n.y, "w": n.w, "h": n.h, "shape": n.shape or [], "lat": n.lat, "lon": n.lon, "level": n.level,
            "orientation_deg": n.orientation_deg, "fov_deg": n.fov_deg, "view_range": n.view_range, "layout": n.layout, "is_entry": n.is_entry, "restricted": n.restricted,
            "meta": n.meta or {}, "frame_id": self.frame(n.id), "path": self.path_label(n.id),
        }

    @staticmethod
    def link_dict(lk: LocationLink) -> dict:
        return {"id": lk.id, "source_id": lk.source_id, "target_id": lk.target_id, "kind": lk.kind, "one_way": lk.one_way, "travel_min_s": lk.travel_min_s,
                "travel_max_s": lk.travel_max_s, "via_id": lk.via_id, "shared_id": lk.shared_id, "overlap": lk.overlap, "distance": lk.distance, "notes": lk.notes}

    def graph(self, root: int | None = None) -> dict:
        """Nodes and edges of the location graph (INSIDE from the hierarchy, the stored links)."""
        ids = self.subtree(root) if root is not None else set(self.nodes)
        edges = [{"source": n, "target": self.nodes[n].parent_id, "kind": "INSIDE", "derived": True} for n in ids if self.nodes[n].parent_id in ids]
        for lk in self.links:
            if lk.source_id in ids and lk.target_id in ids:
                edges.append({**self.link_dict(lk), "source": lk.source_id, "target": lk.target_id, "derived": False})
        zones = [{"camera_id": c, "object_id": o, "node_id": n} for (c, o), n in self.zones.items() if n in ids]
        return {"nodes": [self.node_dict(self.nodes[i]) for i in sorted(ids)], "edges": edges, "zone_links": zones}
