"""Runs: start/stop/pause, status, live WebSocket and MJPEG preview."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import RunOut, StartRunIn
from pathscope.db.models import Experiment, Recording, Run
from pathscope.db.session import get_session_factory
from pathscope.services.run_launcher import LaunchError, start_run
from pathscope.workers.supervisor import RunSupervisor, get_supervisor

router = APIRouter(tags=["runs"])
# WebSocket routes live outside the /api prefix (see main.py)
ws_router = APIRouter(tags=["runs"])


def _run_out(r: Run) -> RunOut:
    o = RunOut.model_validate(r)
    h = get_supervisor().get(r.id)
    if h is not None and not h.finished:
        o.live = h.status
    return o


@router.post("/experiments/{experiment_id}/start", response_model=RunOut, status_code=201)
def start(experiment_id: int, body: StartRunIn | None = None, session: Session = Depends(db_session)):
    body = body or StartRunIn()
    try:
        run = start_run(session, experiment_id, body.scene_config_id, body.realtime, body.loop)
    except LaunchError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_out(run)


@router.get("/runs", response_model=list[RunOut])
def list_runs(experiment_id: int | None = Query(default=None), camera_id: int | None = Query(default=None), active: bool = Query(default=False), limit: int = Query(default=100, le=1000), session: Session = Depends(db_session)):
    q = select(Run).order_by(Run.id.desc()).limit(limit)
    if experiment_id is not None:
        q = q.where(Run.experiment_id == experiment_id)
    if camera_id is not None:
        q = q.where(Run.camera_id == camera_id)
    if active:
        ids = [h.run_id for h in get_supervisor().active()]
        q = q.where(Run.id.in_(ids)) if ids else q.where(Run.id < 0)
    return [_run_out(r) for r in session.scalars(q)]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(db_session)):
    return _run_out(get_or_404(session, Run, run_id, "Run"))


@router.get("/runs/{run_id}/status")
def run_status(run_id: int, session: Session = Depends(db_session)) -> dict:
    run = get_or_404(session, Run, run_id, "Run")
    h = get_supervisor().get(run_id)
    live = h.status if h else None
    return {"run_id": run_id, "status": run.status, "live": live, "finished": (h.finished if h else True), "recent_events": list(h.recent_events)[-50:] if h else []}


def _control(run_id: int, kind: str, session: Session) -> dict:
    run = get_or_404(session, Run, run_id, "Run")
    sup = get_supervisor()
    if kind == "stop":
        ok = sup.stop(run_id)
        if not ok:
            raise HTTPException(409, "This run is not active.")
        exp = session.get(Experiment, run.experiment_id)
        if exp is not None and exp.status == "running":
            exp.status = "draft"
            session.commit()
        session.refresh(run)
        return {"ok": True, "status": run.status}
    ok = sup.send(run_id, kind)
    if not ok:
        raise HTTPException(409, "This run is not active.")
    return {"ok": True}


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: int, session: Session = Depends(db_session)) -> dict:
    return _control(run_id, "stop", session)


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: int, session: Session = Depends(db_session)) -> dict:
    return _control(run_id, "pause", session)


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: int, session: Session = Depends(db_session)) -> dict:
    return _control(run_id, "resume", session)


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(run_id: int, session: Session = Depends(db_session)):
    run = get_or_404(session, Run, run_id, "Run")
    h = get_supervisor().get(run_id)
    if h is not None and not h.finished:
        raise HTTPException(409, "Stop the run before deleting it.")
    from pathscope.storage.recordings import delete_files

    paths = list(session.scalars(select(Recording.path).where(Recording.run_id == run_id)))
    session.delete(run)
    session.commit()
    delete_files(paths)
    from pathscope.anomaly.service import delete_run_evidence

    delete_run_evidence(run_id)  # the anomaly rows went with the run
    get_supervisor().forget(run_id)


@router.get("/runs/{run_id}/stream.mjpg")
async def mjpeg(run_id: int, rtoken: str | None = Query(default=None)):
    """The annotated live picture. With a valid recognition token the labels
    also carry the recognized person or plate; without one they never do."""
    h = get_supervisor().get(run_id)
    if h is None:
        raise HTTPException(404, "run is not active")
    identities = _recognition_viewer(rtoken)

    async def gen():
        last = -1
        while not h.finished:
            if h.preview_seq != last and h.latest_preview is not None:
                got = await run_in_threadpool(RunSupervisor.annotated_preview, h, identities)
                if got is not None:
                    last, jpeg = got
                    yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.03)

    return StreamingResponse(gen(), media_type="multipart/x-mixed-replace; boundary=frame")


def _recognition_viewer(token: str | None) -> bool:
    """Whether a recognition access token allows identity overlays on the live stream."""
    if not token:
        return False
    from pathscope.recognition.common.access import authenticate

    Session = get_session_factory()
    s = Session()
    try:
        return authenticate(s, token) is not None
    except Exception:  # noqa: BLE001
        return False
    finally:
        s.close()


def strip_recognition(tracks: list[dict]) -> list[dict]:
    """Identity and plate overlays are only for authenticated recognition viewers."""
    if not any("recognition" in t for t in tracks):
        return tracks
    return [{k: v for k, v in t.items() if k != "recognition"} for t in tracks]


@ws_router.websocket("/ws/runs/{run_id}")
async def live_ws(websocket: WebSocket, run_id: int):
    """Stream previews (JSON meta + binary JPEG), status and events."""
    await websocket.accept()
    sup = get_supervisor()
    h = sup.get(run_id)
    show_recognition = _recognition_viewer(websocket.query_params.get("rtoken"))
    if h is None:
        # Not active: report the stored state once and close
        Session = get_session_factory()
        s = Session()
        try:
            run = s.get(Run, run_id)
            await websocket.send_text(json.dumps({"type": "status", "run_id": run_id, "status": run.status if run else "unknown", "finished": True, "live": run.stats if run else None}, default=str))
        finally:
            s.close()
        await websocket.close()
        return
    last_preview = -1
    last_event_seq = h.event_seq
    last_status_sent = 0.0
    try:
        while True:
            now = time.time()
            if h.preview_seq != last_preview and h.latest_preview is not None:
                last_preview = h.preview_seq
                p = h.latest_preview
                meta = {
                    "type": "frame",
                    "frame_index": p.frame_index,
                    "media_time_s": round(p.media_time_s, 3),
                    "width": p.width,
                    "height": p.height,
                    "source_width": p.source_width,
                    "source_height": p.source_height,
                    "tracks": p.tracks if show_recognition else strip_recognition(p.tracks),
                    "interactions": p.interactions,
                    "events": p.events,
                    "processed": p.processed,
                }
                await websocket.send_text(json.dumps(meta))
                await websocket.send_bytes(p.jpeg)
            if h.event_seq != last_event_seq:
                new = [e for e in list(h.recent_events) if e["seq"] > last_event_seq]
                last_event_seq = h.event_seq
                if new:
                    await websocket.send_text(json.dumps({"type": "events", "events": new}, default=str))
            if now - last_status_sent >= 0.5:
                last_status_sent = now
                await websocket.send_text(json.dumps({"type": "status", "run_id": run_id, "finished": h.finished, "live": h.status}, default=str))
                if h.finished:
                    await asyncio.sleep(0.2)
                    break
            try:
                msg = await asyncio.wait_for(websocket.receive_text(), timeout=0.03)
                try:
                    cmd = json.loads(msg)
                    if cmd.get("type") in ("pause", "resume", "stop", "seek", "set_preview"):
                        sup.send(run_id, cmd["type"], cmd.get("payload") or {})
                except (ValueError, KeyError):
                    pass
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001 - client went away
        return
    try:
        await websocket.close()
    except Exception:  # noqa: BLE001
        pass
