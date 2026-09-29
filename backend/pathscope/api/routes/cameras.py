"""Cameras: configuration, connection tests, snapshots, device discovery."""

from __future__ import annotations

import time

import cv2
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404, settings_dep
from pathscope.api.schemas import CameraIn, CameraOut, CameraUpdate, ConnectionTestIn
from pathscope.config import Settings
from pathscope.db.models import Camera, Project, SceneConfig, Video
from pathscope.services.preview import (
    PreviewConfig,
    PreviewUnavailable,
    device_key,
    get_preview_manager,
)
from pathscope.settings_store import get_setting
from pathscope.vision.preprocessing import PreprocessConfig, apply_preprocess, encode_jpeg
from pathscope.vision.sources import (
    SOURCE_TYPES,
    SourceError,
    create_source,
    enumerate_usb_cameras,
    test_network_stream,
)
from pathscope.vision.sources.file_source import read_frame_at
from pathscope.workers.supervisor import get_supervisor

router = APIRouter(prefix="/cameras", tags=["cameras"])


def _out(session: Session, cam: Camera) -> CameraOut:
    o = CameraOut.model_validate(cam)
    latest = session.scalar(select(SceneConfig).where(SceneConfig.camera_id == cam.id).order_by(SceneConfig.version.desc()).limit(1))
    if latest is not None:
        o.latest_scene_id = latest.id
        o.latest_scene_version = latest.version
    for h in get_supervisor().active():
        if h.spec.camera_id == cam.id:
            o.active_run_id = h.run_id
            break
    return o


def _active_run(camera_id: int):
    return next((h for h in get_supervisor().active() if h.spec.camera_id == camera_id), None)


def _live_session(cam: Camera, min_live_s: float = 0.0):
    """Open (or join) the camera's preview and wait for a frame. Caller must release."""
    manager = get_preview_manager()
    try:
        session = manager.acquire(PreviewConfig.from_camera(cam))
    except PreviewUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    if not session.wait_for_frame(12.0, min_live_s=min_live_s):
        error = session.error or "The camera did not deliver a frame."
        manager.release(session)
        raise HTTPException(400, error)
    return session


def _resolve_uri(session: Session, cam: Camera) -> str:
    if cam.source_type == "file":
        if cam.video_id is not None:
            video = session.get(Video, cam.video_id)
            if video is None:
                raise HTTPException(400, "The camera references a video that no longer exists.")
            return video.path
        if not cam.source_uri:
            raise HTTPException(400, "No video file is assigned to this camera.")
        return cam.source_uri
    return cam.source_uri


@router.get("/source-types")
def source_types() -> list[dict]:
    return SOURCE_TYPES


@router.get("/devices")
def devices(session: Session = Depends(db_session)) -> dict:
    n = int(get_setting(session, "usb_probe_count", 6))
    known: dict[int, dict] = {}
    for s in get_preview_manager().sessions():
        kind, idx = s.cfg.device
        if kind == "usb" and idx.isdigit():
            known[int(idx)] = {"width": s.source_width, "height": s.source_height, "fps": s.source_fps, "backend": s.backend, "in_use": "live preview"}
    for h in get_supervisor().active():
        kind, idx = device_key(h.spec.source_type, h.spec.source_uri)
        if kind == "usb" and idx.isdigit():
            src = (h.status or {}).get("source") or {}
            known[int(idx)] = {"width": src.get("width") or 0, "height": src.get("height") or 0, "fps": src.get("fps") or 0.0, "backend": src.get("backend", ""), "in_use": f"run {h.run_id}"}
    return {"usb": enumerate_usb_cameras(n, known=known)}


@router.post("/test-connection")
def test_connection(body: ConnectionTestIn, session: Session = Depends(db_session)) -> dict:
    if body.source_type in ("rtsp", "http"):
        return test_network_stream(body.source_uri, transport=str(get_setting(session, "rtsp_transport", "tcp") or "tcp"))
    if body.source_type == "usb":
        held = get_preview_manager().holding("usb", body.source_uri)
        if held is not None and held.state == "live":
            return {"ok": True, "stage": "done", "message": "Camera is delivering frames (live preview is open).", "width": held.source_width, "height": held.source_height, "fps": held.source_fps}
        run = next((h for h in get_supervisor().active() if device_key(h.spec.source_type, h.spec.source_uri) == device_key("usb", body.source_uri)), None)
        if run is not None:
            return {"ok": True, "stage": "done", "message": f"Camera is in use by run {run.run_id}."}
        try:
            src = create_source("usb", body.source_uri or "0")
            info = src.open()
            src.close()
            return {"ok": True, "stage": "done", "message": "Camera opened and delivered a frame.", "width": info.width, "height": info.height, "fps": info.fps}
        except SourceError as exc:
            return {"ok": False, "stage": "open", "message": str(exc)}
    if body.source_type == "file":
        try:
            from pathscope.vision.sources.file_source import probe_video_file

            info = probe_video_file(body.source_uri)
            return {"ok": True, "stage": "done", "message": "Video file opened.", **info.to_dict()}
        except SourceError as exc:
            return {"ok": False, "stage": "open", "message": str(exc)}
    raise HTTPException(400, "unknown source type")


@router.get("", response_model=list[CameraOut])
def list_cameras(project_id: int | None = Query(default=None), session: Session = Depends(db_session)):
    q = select(Camera).order_by(Camera.name)
    if project_id is not None:
        q = q.where(Camera.project_id == project_id)
    return [_out(session, c) for c in session.scalars(q)]


@router.post("", response_model=CameraOut, status_code=201)
def create_camera(body: CameraIn, session: Session = Depends(db_session)):
    get_or_404(session, Project, body.project_id, "Project")
    if body.rotation not in (0, 90, 180, 270):
        raise HTTPException(400, "rotation must be 0, 90, 180 or 270")
    cam = Camera(**body.model_dump())
    if cam.source_type == "file" and cam.video_id is not None:
        video = get_or_404(session, Video, cam.video_id, "Video")
        cam.width, cam.height, cam.requested_fps = video.width, video.height, video.fps
    session.add(cam)
    session.commit()
    session.refresh(cam)
    return _out(session, cam)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, session: Session = Depends(db_session)):
    return _out(session, get_or_404(session, Camera, camera_id, "Camera"))


@router.put("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraUpdate, session: Session = Depends(db_session)):
    cam = get_or_404(session, Camera, camera_id, "Camera")
    data = body.model_dump(exclude_unset=True)
    if "rotation" in data and data["rotation"] not in (0, 90, 180, 270):
        raise HTTPException(400, "rotation must be 0, 90, 180 or 270")
    if data.get("project_id") is None:
        data.pop("project_id", None)
    else:
        get_or_404(session, Project, data["project_id"], "Project")
    for k, v in data.items():
        setattr(cam, k, v)
    if cam.source_type == "file" and cam.video_id is not None:
        video = session.get(Video, cam.video_id)
        if video is not None:
            cam.width, cam.height, cam.requested_fps = video.width, video.height, video.fps
    session.commit()
    session.refresh(cam)
    get_preview_manager().stop_camera(cam.id)  # viewers reconnect with the new settings
    return _out(session, cam)


@router.delete("/{camera_id}", status_code=204)
def delete_camera(camera_id: int, session: Session = Depends(db_session)):
    cam = get_or_404(session, Camera, camera_id, "Camera")
    for h in get_supervisor().active():
        if h.spec.camera_id == cam.id:
            raise HTTPException(409, "Stop the running experiment on this camera first.")
    get_preview_manager().stop_camera(cam.id)
    session.delete(cam)
    session.commit()


@router.get("/{camera_id}/frame-info")
def frame_info(camera_id: int, session: Session = Depends(db_session)) -> dict:
    cam = get_or_404(session, Camera, camera_id, "Camera")
    uri = _resolve_uri(session, cam)
    pre = PreprocessConfig(rotation=cam.rotation, crop=cam.crop)
    if cam.source_type == "file":
        from pathscope.vision.sources.file_source import probe_video_file

        try:
            info = probe_video_file(uri)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc
        w, h = pre.output_size(info.width, info.height)
        return {"width": w, "height": h, "source_width": info.width, "source_height": info.height, "fps": info.fps, "duration_s": info.duration_s, "frame_count": info.frame_count, "is_live": False}
    run = _active_run(cam.id)
    if run is not None:  # the run's worker owns the camera; never open it a second time
        src = (run.status or {}).get("source") or {}
        if not src.get("width"):
            raise HTTPException(409, "The camera is starting for a run; try again in a moment.")
        w, h = pre.output_size(int(src["width"]), int(src["height"]))
        return {"width": w, "height": h, "source_width": src["width"], "source_height": src["height"], "fps": src.get("fps"), "duration_s": None, "frame_count": None, "is_live": True}
    live = _live_session(cam)
    try:
        return {"width": live.frame_width, "height": live.frame_height, "source_width": live.source_width, "source_height": live.source_height, "fps": live.source_fps, "duration_s": None, "frame_count": None, "is_live": True}
    finally:
        get_preview_manager().release(live)


@router.get("/{camera_id}/snapshot")
def snapshot(camera_id: int, t: float = Query(default=0.0, ge=0.0), session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)):
    """A single preprocessed frame (rotation/crop applied) as JPEG."""
    cam = get_or_404(session, Camera, camera_id, "Camera")
    uri = _resolve_uri(session, cam)
    pre = PreprocessConfig(rotation=cam.rotation, crop=cam.crop)
    if cam.source_type != "file":
        run = _active_run(cam.id)
        if run is not None:  # the run's worker owns the camera
            p = run.latest_preview
            if p is None:
                raise HTTPException(409, "The camera is starting for a run; try again in a moment.")
            return Response(content=p.jpeg, media_type="image/jpeg", headers={"X-Frame-Width": str(p.source_width), "X-Frame-Height": str(p.source_height), "X-Media-Time": str(p.media_time_s), "Cache-Control": "no-store"})
        # Webcams need a moment for auto-exposure; the first frames are often dark.
        live = _live_session(cam, min_live_s=0.6 if cam.source_type == "usb" else 0.0)
        try:
            jpeg, fw, fh = live.jpeg, live.frame_width, live.frame_height
        finally:
            get_preview_manager().release(live)
        return Response(content=jpeg, media_type="image/jpeg", headers={"X-Frame-Width": str(fw), "X-Frame-Height": str(fh), "X-Media-Time": str(time.time()), "Cache-Control": "no-store"})
    try:
        frame, info = read_frame_at(uri, t)
        media_t = t
    except SourceError as exc:
        raise HTTPException(400, str(exc)) from exc
    if frame is None:
        raise HTTPException(400, "Could not read a frame from this source.")
    frame = apply_preprocess(frame, pre)
    h, w = frame.shape[:2]
    max_w = 1920
    if w > max_w:
        frame = cv2.resize(frame, (max_w, int(h * max_w / w)), interpolation=cv2.INTER_AREA)
    jpeg = encode_jpeg(frame, 85)
    return Response(content=jpeg, media_type="image/jpeg", headers={"X-Frame-Width": str(w), "X-Frame-Height": str(h), "X-Media-Time": str(media_t), "Cache-Control": "no-store"})
