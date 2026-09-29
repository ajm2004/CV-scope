"""HTTP API of the Location Engine and cross-camera correlation: ``/api/locations``.

Topology (hierarchy, links, zone mapping, layouts) is configuration: reading
it needs the graph role, changing it the rules role. Transitions, journeys
and live overlays go through the relationship presenter, so identities are
shown only to viewers allowed to see them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.config import get_settings
from pathscope.db.models import Camera, Event, SceneConfig
from pathscope.location.models import (
    CrossCameraTransition,
    LocationLink,
    LocationNode,
    LocationZoneLink,
)
from pathscope.location.settings import (
    CrossCameraSettings,
    load_crosscam_settings,
    save_crosscam_settings,
)
from pathscope.location.topology import LINK_KINDS, NODE_KINDS, LocationGraph
from pathscope.relationships import entities as E
from pathscope.relationships.access import (
    Viewer,
    audit,
    can_change_settings,
    graph_viewer,
    viewer_dep,
)
from pathscope.relationships.graph import Presenter, SqlGraph
from pathscope.relationships.models import RelationCorrelated, RelationEntity

router = APIRouter(prefix="/locations", tags=["locations"])

IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
MAX_IMAGE = 15 * 1024 * 1024


def _image_dir() -> Path:
    p = Path(get_settings().resolved_data_dir) / "locations"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------- models
class LayoutIn(BaseModel):
    mode: Literal["plan", "schematic", "map"] = "schematic"
    width: float = Field(default=100.0, gt=0, le=1e7)
    height: float = Field(default=60.0, gt=0, le=1e7)
    unit: Literal["m", "units"] = "m"
    image: str | None = None
    # map mode: the geographic box the layout covers (optional)
    bounds: dict[str, float] | None = None


class NodeIn(BaseModel):
    parent_id: int | None = None
    project_id: int | None = None
    kind: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    camera_id: int | None = None
    sensor_id: str | None = Field(default=None, max_length=100)
    x: float | None = None
    y: float | None = None
    w: float | None = Field(default=None, ge=0)
    h: float | None = Field(default=None, ge=0)
    shape: list[list[float]] = Field(default_factory=list, max_length=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    level: int | None = Field(default=None, ge=-50, le=300)
    orientation_deg: float | None = Field(default=None, ge=-360, le=360)
    fov_deg: float | None = Field(default=None, gt=0, le=360)
    view_range: float | None = Field(default=None, gt=0)
    layout: LayoutIn | None = None
    is_entry: bool = False
    restricted: bool = False
    meta: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> NodeIn:
        if self.kind not in NODE_KINDS:
            raise ValueError(f"unknown kind '{self.kind}' (one of {', '.join(NODE_KINDS)})")
        if self.kind == "camera" and self.camera_id is None:
            raise ValueError("a camera node needs the camera it stands for")
        if self.kind != "camera" and self.camera_id is not None:
            raise ValueError("only a camera node can stand for a camera")
        if self.kind == "sensor" and not self.sensor_id:
            raise ValueError("a sensor node needs the sensor id its observations use")
        return self


class LinkIn(BaseModel):
    source_id: int
    target_id: int
    kind: str = "CONNECTED_TO"
    one_way: bool = False
    travel_min_s: float | None = Field(default=None, ge=0, le=7 * 86400)
    travel_max_s: float | None = Field(default=None, ge=0, le=7 * 86400)
    via_id: int | None = None
    shared_id: int | None = None
    overlap: bool = False
    distance: float | None = Field(default=None, ge=0)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def _check(self) -> LinkIn:
        if self.kind not in LINK_KINDS:
            raise ValueError(f"unknown link kind '{self.kind}' (one of {', '.join(LINK_KINDS)})")
        if self.source_id == self.target_id:
            raise ValueError("a link needs two different nodes")
        if self.travel_min_s is not None and self.travel_max_s is not None and self.travel_max_s < self.travel_min_s:
            raise ValueError("the longest travel time is shorter than the shortest")
        return self


class PositionIn(BaseModel):
    id: int
    x: float | None = None
    y: float | None = None
    w: float | None = None
    h: float | None = None
    shape: list[list[float]] | None = None


class ZoneLinkIn(BaseModel):
    object_id: str = Field(min_length=1, max_length=100)
    object_kind: Literal["zone", "line", "route"] = "zone"
    node_id: int | None = None


# ---------------------------------------------------------------------------- helpers
def _graph(session: Session) -> LocationGraph:
    return LocationGraph.load(session)


def _check_parent(session: Session, node_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    if session.get(LocationNode, parent_id) is None:
        raise HTTPException(422, f"Parent {parent_id} does not exist.")
    if node_id is None:
        return
    g = _graph(session)
    if parent_id in g.subtree(node_id):
        raise HTTPException(422, "A node cannot be placed inside itself or one of its children.")


def _apply(n: LocationNode, body: NodeIn) -> None:
    for k in ("parent_id", "project_id", "kind", "name", "description", "camera_id", "sensor_id", "x", "y", "w", "h", "shape", "lat", "lon", "level",
              "orientation_deg", "fov_deg", "view_range", "is_entry", "restricted", "meta"):
        setattr(n, k, getattr(body, k))
    if body.layout is not None:
        old = (n.layout or {}).get("image")
        n.layout = {**body.layout.model_dump(), "image": body.layout.image or old}
    else:
        n.layout = None


def _changed(session: Session, viewer: Viewer, what: str, target, detail: dict | None = None) -> None:
    audit(session, viewer, "topology_changed", what, target, detail or {})


# ---------------------------------------------------------------------------- meta and tree
@router.get("/meta")
def meta(viewer: Viewer = Depends(graph_viewer)) -> dict:
    return {
        "node_kinds": [{"id": k, "label": v[0], "group": v[1]} for k, v in NODE_KINDS.items()],
        "link_kinds": [{"id": k, "description": v} for k, v in LINK_KINDS.items()],
        "viewer": viewer.to_dict(),
    }


@router.get("/graph")
def location_graph(root_id: int | None = None, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> dict:
    g = _graph(session)
    if root_id is not None and root_id not in g.nodes:
        raise HTTPException(404, "No such location.")
    out = g.graph(root_id)
    cams = {c.id: c for c in session.scalars(select(Camera))}
    for n in out["nodes"]:
        if n["camera_id"] is not None and n["camera_id"] in cams:
            c = cams[n["camera_id"]]
            n["camera"] = {"id": c.id, "name": c.name, "source_type": c.source_type, "project_id": c.project_id, "enabled": c.enabled}
    placed = set(g.by_camera)
    out["unplaced_cameras"] = [{"id": c.id, "name": c.name, "project_id": c.project_id} for c in cams.values() if c.id not in placed]
    return out


@router.post("/nodes", status_code=201)
def create_node(body: NodeIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    _check_parent(session, None, body.parent_id)
    if body.camera_id is not None:
        get_or_404(session, Camera, body.camera_id, "Camera")
        if session.scalar(select(LocationNode.id).where(LocationNode.camera_id == body.camera_id)) is not None:
            raise HTTPException(409, "This camera is already placed in the location model.")
    n = LocationNode()
    _apply(n, body)
    session.add(n)
    session.flush()
    _changed(session, viewer, "location", n.id, {"action": "created", "kind": n.kind, "name": n.name})
    session.commit()
    return _graph(session).node_dict(n)


@router.put("/nodes/{node_id}")
def update_node(node_id: int, body: NodeIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    n = get_or_404(session, LocationNode, node_id, "Location")
    _check_parent(session, node_id, body.parent_id)
    if body.camera_id is not None and body.camera_id != n.camera_id:
        get_or_404(session, Camera, body.camera_id, "Camera")
        if session.scalar(select(LocationNode.id).where(LocationNode.camera_id == body.camera_id, LocationNode.id != node_id)) is not None:
            raise HTTPException(409, "This camera is already placed in the location model.")
    _apply(n, body)
    _changed(session, viewer, "location", n.id, {"action": "updated", "name": n.name})
    session.commit()
    return _graph(session).node_dict(n)


@router.put("/positions")
def update_positions(items: list[PositionIn], viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """Positions dragged in the layout editor (one request per drop)."""
    viewer.require("rules")
    for it in items[:500]:
        n = session.get(LocationNode, it.id)
        if n is None:
            continue
        for k in ("x", "y", "w", "h", "shape"):
            v = getattr(it, k)
            if v is not None or k in it.model_fields_set:
                setattr(n, k, v if v is not None else ([] if k == "shape" else None))
    session.commit()
    return {"updated": len(items)}


@router.delete("/nodes/{node_id}", status_code=204)
def delete_node(node_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    """Deletes the node and everything inside it (links and zone mappings go with them)."""
    viewer.require("rules")
    n = get_or_404(session, LocationNode, node_id, "Location")
    g = _graph(session)
    ids = g.subtree(node_id)
    for nid in ids:
        img = ((g.nodes[nid].layout or {}) if nid in g.nodes else {}).get("image")
        if img:
            (_image_dir() / Path(img).name).unlink(missing_ok=True)
    session.query(LocationZoneLink).filter(LocationZoneLink.node_id.in_(ids)).delete(synchronize_session=False)
    session.query(LocationLink).filter((LocationLink.source_id.in_(ids)) | (LocationLink.target_id.in_(ids))).delete(synchronize_session=False)
    for nid in sorted(ids, key=lambda i: -len(g.ancestors(i))):
        row = session.get(LocationNode, nid)
        if row is not None:
            session.delete(row)
            session.flush()
    _changed(session, viewer, "location", node_id, {"action": "deleted", "name": n.name, "nodes": len(ids)})
    session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------- links
def _check_link(session: Session, body: LinkIn) -> None:
    a = get_or_404(session, LocationNode, body.source_id, "Location")
    b = get_or_404(session, LocationNode, body.target_id, "Location")
    for x in (body.via_id, body.shared_id):
        if x is not None:
            get_or_404(session, LocationNode, x, "Location")
    if body.kind == "VISIBLE_FROM" and "camera" not in (a.kind, b.kind):
        raise HTTPException(422, "VISIBLE_FROM links a place to the camera that covers it.")
    if body.kind in ("ABOVE", "BELOW") and (body.travel_min_s is not None or body.travel_max_s is not None):
        raise HTTPException(422, "ABOVE / BELOW describe floors, not a passage: add a CONNECTED_TO link (stairs, a lift) for movement.")


@router.post("/links", status_code=201)
def create_link(body: LinkIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    _check_link(session, body)
    lk = LocationLink(**body.model_dump())
    session.add(lk)
    session.flush()
    _changed(session, viewer, "location_link", lk.id, {"action": "created", "kind": lk.kind})
    session.commit()
    return LocationGraph.link_dict(lk)


@router.put("/links/{link_id}")
def update_link(link_id: int, body: LinkIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    lk = get_or_404(session, LocationLink, link_id, "Link")
    _check_link(session, body)
    for k, v in body.model_dump().items():
        setattr(lk, k, v)
    _changed(session, viewer, "location_link", lk.id, {"action": "updated", "kind": lk.kind})
    session.commit()
    return LocationGraph.link_dict(lk)


@router.delete("/links/{link_id}", status_code=204)
def delete_link(link_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    viewer.require("rules")
    lk = get_or_404(session, LocationLink, link_id, "Link")
    session.delete(lk)
    _changed(session, viewer, "location_link", link_id, {"action": "deleted"})
    session.commit()
    return Response(status_code=204)


@router.get("/check")
def check_transition(from_camera: int, to_camera: int, object_class: str = "person", from_node: int | None = None, to_node: int | None = None,
                     session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> dict:
    """What the correlation engine would conclude about a move between two cameras."""
    g = _graph(session)
    ev = g.camera_transition(from_camera, to_camera, from_node, to_node, object_class)
    out = ev.to_dict()
    out["certainty"] = ev.certainty
    out["path_nodes"] = [{"id": n, "name": g.nodes[n].name, "kind": g.nodes[n].kind} for n in ev.path if n in g.nodes]
    return out


# ---------------------------------------------------------------------------- zones of camera scenes (Location Resolution)
@router.get("/cameras/{camera_id}/zones")
def camera_zones(camera_id: int, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> dict:
    cam = get_or_404(session, Camera, camera_id, "Camera")
    sc = session.scalars(select(SceneConfig).where(SceneConfig.camera_id == camera_id).order_by(SceneConfig.version.desc()).limit(1)).first()
    doc = (sc.document if sc else {}) or {}
    links = {z.object_id: z for z in session.scalars(select(LocationZoneLink).where(LocationZoneLink.camera_id == camera_id))}
    items = []
    for o in doc.get("objects") or []:
        if o.get("type") == "ignore":
            continue
        kind = "line" if o.get("type") in ("line", "gate") else "zone"
        z = links.get(o.get("id"))
        items.append({"object_id": o.get("id"), "name": o.get("name") or o.get("id"), "type": o.get("type"), "object_kind": kind, "node_id": z.node_id if z else None})
    for r in doc.get("routes") or []:
        z = links.get(r.get("id"))
        items.append({"object_id": r.get("id"), "name": r.get("name") or r.get("id"), "type": "route", "object_kind": "route", "node_id": z.node_id if z else None})
    known = {i["object_id"] for i in items}
    for oid, z in links.items():
        if oid not in known:
            items.append({"object_id": oid, "name": f"{oid} (not in the latest scene)", "type": z.object_kind, "object_kind": z.object_kind, "node_id": z.node_id})
    return {"camera": {"id": cam.id, "name": cam.name}, "scene_version": sc.version if sc else None, "items": items}


@router.put("/cameras/{camera_id}/zones")
def set_camera_zones(camera_id: int, items: list[ZoneLinkIn], viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    viewer.require("rules")
    get_or_404(session, Camera, camera_id, "Camera")
    for it in items:
        if it.node_id is not None:
            get_or_404(session, LocationNode, it.node_id, "Location")
    session.query(LocationZoneLink).filter(LocationZoneLink.camera_id == camera_id).delete(synchronize_session=False)
    n = 0
    for it in items:
        if it.node_id is None:
            continue
        session.add(LocationZoneLink(camera_id=camera_id, object_id=it.object_id, object_kind=it.object_kind, node_id=it.node_id))
        n += 1
    _changed(session, viewer, "camera_zones", camera_id, {"mapped": n})
    session.commit()
    return camera_zones(camera_id, session, viewer)


# ---------------------------------------------------------------------------- layout images
@router.post("/nodes/{node_id}/image")
async def upload_image(node_id: int, file: UploadFile, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """A floor plan, a site drawing or a map picture shown under the layout."""
    viewer.require("rules")
    n = get_or_404(session, LocationNode, node_id, "Location")
    if not n.layout:
        raise HTTPException(422, "Give the node a layout first (width, height, unit).")
    ext = IMAGE_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(415, "Use a PNG, JPEG or WebP picture.")
    data = await file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "The picture is larger than 15 MB.")
    old = (n.layout or {}).get("image")
    if old:
        (_image_dir() / Path(old).name).unlink(missing_ok=True)
    name = f"node-{node_id}-{int(datetime.now(UTC).timestamp())}{ext}"
    (_image_dir() / name).write_bytes(data)
    n.layout = {**(n.layout or {}), "image": name}
    _changed(session, viewer, "location", node_id, {"action": "image", "bytes": len(data)})
    session.commit()
    return _graph(session).node_dict(n)


@router.get("/nodes/{node_id}/image")
def get_image(node_id: int, session: Session = Depends(db_session), viewer: Viewer = Depends(graph_viewer)) -> FileResponse:
    n = get_or_404(session, LocationNode, node_id, "Location")
    name = (n.layout or {}).get("image")
    if not name:
        raise HTTPException(404, "This layout has no picture.")
    p = _image_dir() / Path(name).name
    if not p.is_file():
        raise HTTPException(404, "The picture file is missing.")
    return FileResponse(p)


@router.delete("/nodes/{node_id}/image", status_code=204)
def delete_image(node_id: int, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> Response:
    viewer.require("rules")
    n = get_or_404(session, LocationNode, node_id, "Location")
    name = (n.layout or {}).get("image")
    if name:
        (_image_dir() / Path(name).name).unlink(missing_ok=True)
        n.layout = {**(n.layout or {}), "image": None}
        session.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------------------- cross-camera settings and correlation
@router.get("/settings")
def get_crosscam_settings(session: Session = Depends(db_session), viewer: Viewer = Depends(viewer_dep)) -> dict:
    return {"settings": load_crosscam_settings(session).model_dump(), "viewer": viewer.to_dict()}


@router.put("/settings")
def put_crosscam_settings(body: CrossCameraSettings, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    can_change_settings(session, viewer)
    before = load_crosscam_settings(session).model_dump()
    save_crosscam_settings(session, body)
    audit(session, viewer, "settings_changed", "crosscam", None, {"changed": sorted(k for k, v in body.model_dump().items() if before.get(k) != v)})
    session.commit()
    return {"settings": body.model_dump(), "viewer": viewer.to_dict()}


class CorrelateIn(BaseModel):
    run_ids: list[int] | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    hours: float | None = Field(default=None, gt=0, le=24 * 90)


@router.post("/correlate")
def correlate(body: CorrelateIn, viewer: Viewer = Depends(viewer_dep), session: Session = Depends(db_session)) -> dict:
    """Correlate runs across cameras again (after a topology edit)."""
    viewer.require("rules")
    from pathscope.crosscam.service import get_crosscam_service

    svc = get_crosscam_service()
    if body.run_ids:
        out = svc.correlate(set(body.run_ids))
    else:
        t_from = body.time_from or (datetime.now(UTC) - timedelta(hours=body.hours or 24))
        out = svc.correlate_window(session, t_from, body.time_to)
    audit(session, viewer, "crosscam_correlated", "runs", None, {k: out.get(k) for k in ("transitions", "withdrawn", "deviations")} | {"runs": len(out.get("runs") or [])})
    session.commit()
    return out


# ---------------------------------------------------------------------------- transitions and journeys
def _camera_scope(session: Session, location_id: int | None) -> set[int] | None:
    if location_id is None:
        return None
    g = _graph(session)
    if location_id not in g.nodes:
        raise HTTPException(404, "No such location.")
    return g.cameras_in(location_id)


@router.get("/transitions")
def list_transitions(time_from: datetime | None = None, time_to: datetime | None = None, location_id: int | None = None, camera_id: int | None = None, run_id: int | None = None,
                     key: str | None = None, min_state: str = "possible", flagged: bool = False, include_withdrawn: bool = False, limit: int = Query(default=200, le=2000),
                     viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> list[dict]:
    from pathscope.crosscam.journey import transitions

    p = Presenter(session, viewer)
    f: dict = {"time_from": time_from, "time_to": time_to, "run_id": run_id, "min_state": min_state, "flagged": flagged, "include_withdrawn": include_withdrawn}
    cams = _camera_scope(session, location_id)
    if camera_id is not None:
        cams = {camera_id} if cams is None else cams & {camera_id}
    f["camera_ids"] = cams
    if key:
        e = _visible_entity(session, key, viewer, p)
        if e.entity_type in E.TRACK_TYPES:
            f["track_ids"] = {e.id}
        else:
            f["subject_ids"] = {e.id}
    return transitions(p, f, limit)


@router.get("/transitions/{transition_id}")
def transition_detail(transition_id: int, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    from pathscope.crosscam.engine import Namer
    from pathscope.crosscam.journey import transition_out, visible_basis

    p = Presenter(session, viewer)
    t = get_or_404(session, CrossCameraTransition, transition_id, "Transition")
    if not visible_basis(p, t.basis):
        viewer.require("identity")
    g = _graph(session)
    ents = p.g.entities({t.subject_id, t.from_track_id, t.to_track_id})
    p.load_names(ents)
    out = transition_out(p, g, Namer(session, g), t, ents)
    devs = [c for c in session.scalars(select(RelationCorrelated).where(RelationCorrelated.rule_key.like("crosscam.%"), RelationCorrelated.run_id == t.to_run_id))
            if (c.metrics or {}).get("transition_uid") == t.uid]
    dents = p.g.entities({x for c in devs for x in (c.roles or {}).values()})
    p.load_names(dents)
    out["deviations"] = [p.correlated(c, dents) for c in devs]
    return out


def _visible_entity(session: Session, key: str, viewer: Viewer, p: Presenter) -> RelationEntity:
    e = SqlGraph(session).entity(key)
    if e is None:
        raise HTTPException(404, "No such entity.")
    if not p.visible(e):
        viewer.require("identity")
        raise HTTPException(403, "This identity is hidden by the relationship settings (module switched off).")
    return e


@router.get("/journey")
def get_journey(key: str, time_from: datetime | None = None, time_to: datetime | None = None, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """An entity's sightings across cameras, the transitions between them and its location path."""
    from pathscope.crosscam.journey import journey

    p = Presenter(session, viewer)
    e = _visible_entity(session, key, viewer, p)
    if e.entity_type not in E.IDENTITY_TYPES and e.entity_type not in E.TRACK_TYPES:
        raise HTTPException(422, "A journey belongs to a person, a vehicle, a plate or a track.")
    if e.entity_type in E.IDENTITY_TYPES:
        audit(session, viewer, "identity_viewed", e.entity_type, e.id, {"view": "journey"})
        session.commit()
    return journey(p, e, time_from, time_to)


@router.get("/last-seen")
def get_last_seen(key: str, viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    from pathscope.crosscam.journey import last_seen

    p = Presenter(session, viewer)
    e = _visible_entity(session, key, viewer, p)
    if e.entity_type in E.IDENTITY_TYPES:
        audit(session, viewer, "identity_viewed", e.entity_type, e.id, {"view": "last_seen"})
        session.commit()
    p.load_names({e.id: e})
    return {"entity": p.entity(e), "last": last_seen(p, e)}


@router.get("/deviations")
def list_deviations(location_id: int | None = None, time_from: datetime | None = None, limit: int = Query(default=200, le=2000), viewer: Viewer = Depends(graph_viewer),
                    session: Session = Depends(db_session)) -> list[dict]:
    C = RelationCorrelated
    q = select(C).where(C.rule_key.like("crosscam.%"))
    if time_from is not None:
        q = q.where(C.start_at >= time_from)
    cams = _camera_scope(session, location_id)
    if cams is not None:
        q = q.where(C.camera_id.in_(list(cams)))
    rows = list(session.scalars(q.order_by(C.start_at.desc()).limit(limit)))
    p = Presenter(session, viewer)
    if not p.identities:
        rows = [c for c in rows if (c.metrics or {}).get("basis") == "anonymous" or (c.metrics or {}).get("type") in ("restricted_without_entry",)]
    ents = p.g.entities({x for c in rows for x in (c.roles or {}).values()})
    p.load_names(ents)
    return [p.correlated(c, ents) for c in rows]


# ---------------------------------------------------------------------------- site view: live overlay
@router.get("/live")
def live(root_id: int | None = None, minutes: float = Query(default=15.0, gt=0, le=24 * 60), viewer: Viewer = Depends(graph_viewer), session: Session = Depends(db_session)) -> dict:
    """What is happening now in a site: per camera the active run, counts, recent events and alerts."""
    from pathscope.anomaly.models import AnomalyEvent
    from pathscope.crosscam.journey import transitions
    from pathscope.workers.supervisor import get_supervisor

    g = _graph(session)
    cams = g.cameras_in(root_id) if root_id is not None else set(g.by_camera)
    now = datetime.now(UTC)
    since = now - timedelta(minutes=minutes)
    names = {c.id: c.name for c in session.scalars(select(Camera))}
    handles = {}
    for h in get_supervisor().active():
        if not h.finished and h.spec.camera_id in cams:
            handles[h.spec.camera_id] = h
    per_camera = []
    for cid in sorted(cams):
        h = handles.get(cid)
        item = {"camera_id": cid, "name": names.get(cid, f"camera {cid}"), "node_id": g.by_camera.get(cid), "run_id": None, "state": None, "active_tracks": 0, "classes": {}, "zones": {}}
        if h is not None:
            st = h.status or {}
            classes: dict[str, int] = {}
            prev = h.latest_preview
            for t in (prev.tracks if prev is not None else []) or []:
                if t.get("state", "tracked") == "tracked":
                    c = t.get("class_name") or t.get("class") or "object"
                    classes[c] = classes.get(c, 0) + 1
            item.update({"run_id": h.run_id, "experiment_id": h.spec.experiment_id, "state": st.get("state"), "active_tracks": st.get("active_tracks", 0), "classes": classes,
                         "zones": st.get("zone_occupancy") or {}, "media_time_s": st.get("media_time_s")})
        per_camera.append(item)
    ev = list(session.scalars(select(Event).where(Event.camera_id.in_(list(cams)), Event.wall_time >= since).order_by(Event.wall_time.desc()).limit(60))) if cams else []
    events = [{"id": e.id, "run_id": e.run_id, "camera_id": e.camera_id, "event_type": e.event_type, "label": e.rule_name or e.object_name or e.event_type, "object_class": e.object_class,
               "track_id": e.track_id, "at": e.wall_time, "media_time_s": e.media_time_s} for e in ev]
    p = Presenter(session, viewer)
    C = RelationCorrelated
    day = now - timedelta(hours=24)
    devs = list(session.scalars(select(C).where(C.kind == "deviation", C.camera_id.in_(list(cams)), C.start_at >= day).order_by(C.start_at.desc()).limit(40))) if cams else []
    dents = p.g.entities({x for c in devs for x in (c.roles or {}).values()})
    p.load_names(dents)
    alerts = [{"source": "relationships", "camera_id": c.camera_id, "at": c.start_at, "label": c.label, "text": c.description, "state": c.state, "id": c.id, "run_id": c.run_id} for c in devs]
    an = list(session.scalars(select(AnomalyEvent).where(AnomalyEvent.camera_id.in_(list(cams)), AnomalyEvent.confirmed_at >= day, AnomalyEvent.status == "raised")
                              .order_by(AnomalyEvent.confirmed_at.desc()).limit(40))) if cams else []
    alerts += [{"source": "anomaly", "camera_id": a.camera_id, "at": a.confirmed_at, "label": f"Anomaly in {a.zone_name or a.zone_id}", "text": a.llm_description or a.summary,
                "state": None, "id": a.id, "run_id": a.run_id} for a in an]
    alerts.sort(key=lambda x: x["at"], reverse=True)
    moves = transitions(p, {"time_from": now - timedelta(minutes=minutes * 4), "camera_ids": cams}, limit=60) if cams else []
    present = []
    recent_tracks = list(session.scalars(select(RelationEntity).where(RelationEntity.entity_type.in_(list(E.TRACK_TYPES)), RelationEntity.camera_id.in_(list(cams)),
                                                                       RelationEntity.last_seen >= now - timedelta(seconds=30)).limit(300))) if cams else []
    lifted = p.g.identities_of({t.id for t in recent_tracks}) if p.identities else {}
    ients = p.g.entities(set(lifted.values()))
    p.load_names(ients)
    for t in recent_tracks:
        ident = ients.get(lifted.get(t.id, -1))
        present.append({"camera_id": t.camera_id, "track": p.entity(t), "identity": p.entity(ident) if ident is not None else None, "last_seen": t.last_seen})
    return {"at": now, "cameras": per_camera, "events": events, "alerts": alerts[:60], "transitions": moves, "present": present}
