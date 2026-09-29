"""Live preview of cameras outside runs: MJPEG for <img> tags, WebSocket for the Scene Builder."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from pathscope.db.models import Camera
from pathscope.db.session import get_session_factory
from pathscope.services.preview import PreviewConfig, PreviewUnavailable, get_preview_manager
from pathscope.workers.supervisor import RunSupervisor, get_supervisor

router = APIRouter(prefix="/cameras", tags=["preview"])
ws_router = APIRouter(tags=["preview"])


def _load_config(camera_id: int) -> PreviewConfig:
    session = get_session_factory()()
    try:
        cam = session.get(Camera, camera_id)
        if cam is None:
            raise HTTPException(404, f"Camera {camera_id} not found")
        if cam.source_type == "file":
            raise HTTPException(400, "Video files have no live preview; they are shown as still frames.")
        return PreviewConfig.from_camera(cam)
    finally:
        session.close()


def active_run_for(camera_id: int):
    return next((h for h in get_supervisor().active() if h.spec.camera_id == camera_id), None)


def _part(jpeg: bytes) -> bytes:
    return b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"


@router.get("/{camera_id}/preview/status")
def preview_status(camera_id: int) -> dict:
    run = active_run_for(camera_id)
    if run is not None:
        return {"state": "run", "run_id": run.run_id}
    session = get_preview_manager().get(camera_id)
    return session.status() if session is not None else {"state": "idle", "viewers": 0}


@router.get("/{camera_id}/preview.mjpg")
async def preview_mjpeg(camera_id: int):
    """Continuous MJPEG stream. Shows the run's frames while a run uses the camera."""
    await run_in_threadpool(_load_config, camera_id)  # 404 / 400 before streaming starts
    manager = get_preview_manager()

    async def frames():
        session = None
        last_seq = -1
        last_run_seq = -1
        try:
            while True:
                run = active_run_for(camera_id)
                if run is not None:
                    if session is not None:
                        manager.release(session)
                        session = None
                    if run.latest_preview is not None and run.preview_seq != last_run_seq:
                        got = await run_in_threadpool(RunSupervisor.annotated_preview, run)
                        if got is not None:
                            last_run_seq, jpeg = got
                            yield _part(jpeg)
                    await asyncio.sleep(0.04)
                    continue
                if session is None or not session.alive:
                    if session is not None:
                        manager.release(session)
                        session = None
                    try:
                        cfg = await run_in_threadpool(_load_config, camera_id)
                        session = await run_in_threadpool(manager.acquire, cfg)
                        last_seq = -1
                    except (PreviewUnavailable, HTTPException):
                        await asyncio.sleep(0.5)
                        continue
                if session.seq != last_seq and session.jpeg is not None:
                    last_seq = session.seq
                    yield _part(session.jpeg)
                await asyncio.sleep(0.02)
        finally:
            if session is not None:
                manager.release(session)

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame", headers={"Cache-Control": "no-store"})


@ws_router.websocket("/ws/cameras/{camera_id}/preview")
async def preview_ws(websocket: WebSocket, camera_id: int):
    """Messages: ``frame`` (JSON) followed by the JPEG (binary), ``status`` twice a
    second, ``run_active`` when a run takes the camera (the socket then closes),
    and ``error`` for configuration problems."""
    await websocket.accept()
    manager = get_preview_manager()
    session = None
    try:
        last_seq = -1
        last_status = 0.0
        while True:
            run = active_run_for(camera_id)
            if run is not None:
                await websocket.send_text(json.dumps({"type": "run_active", "run_id": run.run_id}))
                break
            if session is None or not session.alive:
                if session is not None:
                    manager.release(session)
                    session = None
                try:
                    cfg = await run_in_threadpool(_load_config, camera_id)
                    session = await run_in_threadpool(manager.acquire, cfg)
                    last_seq = -1
                except PreviewUnavailable:
                    await asyncio.sleep(0.3)
                    continue
                except HTTPException as exc:
                    await websocket.send_text(json.dumps({"type": "error", "message": exc.detail}))
                    break
            if session.seq != last_seq and session.jpeg is not None:
                last_seq = session.seq
                await websocket.send_text(json.dumps({
                    "type": "frame",
                    "width": session.preview_width,
                    "height": session.preview_height,
                    "source_width": session.frame_width,
                    "source_height": session.frame_height,
                    "fps": session.fps,
                }))
                await websocket.send_bytes(session.jpeg)
            now = time.time()
            if now - last_status >= 0.5:
                last_status = now
                await websocket.send_text(json.dumps({"type": "status", **session.status()}))
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.02)
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - the viewer went away
        pass
    finally:
        if session is not None:
            manager.release(session)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
