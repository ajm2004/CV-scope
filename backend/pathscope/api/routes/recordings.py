"""Video recorded from live cameras: list, play (HTTP range requests), download, delete."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import RecordingOut
from pathscope.db.models import Recording, Run
from pathscope.storage.recordings import PLAYABLE, delete_recordings, inside_recordings

router = APIRouter(tags=["recordings"])


def recording_out(r: Recording) -> RecordingOut:
    return RecordingOut(
        id=r.id, run_id=r.run_id, experiment_id=r.experiment_id, camera_id=r.camera_id, kind=r.kind, mime=r.mime, codec=r.codec,
        width=r.width, height=r.height, fps=r.fps, frames=r.frames, media_start_s=r.media_start_s, media_end_s=r.media_end_s,
        duration_s=max(0.0, r.media_end_s - r.media_start_s), started_at=r.started_at, ended_at=r.ended_at, size_bytes=r.size_bytes,
        overlay=r.overlay, triggers=r.triggers or [], trigger_count=r.trigger_count, playable=r.mime in PLAYABLE,
        url=f"/api/recordings/{r.id}/file",
    )


@router.get("/runs/{run_id}/recordings", response_model=list[RecordingOut])
def run_recordings(run_id: int, session: Session = Depends(db_session)):
    get_or_404(session, Run, run_id, "Run")
    rows = session.scalars(select(Recording).where(Recording.run_id == run_id).order_by(Recording.media_start_s))
    return [recording_out(r) for r in rows]


@router.get("/recordings", response_model=list[RecordingOut])
def list_recordings(
    experiment_id: int | None = Query(default=None),
    camera_id: int | None = Query(default=None),
    limit: int = Query(default=200, le=2000),
    session: Session = Depends(db_session),
):
    q = select(Recording).order_by(Recording.started_at.desc()).limit(limit)
    if experiment_id is not None:
        q = q.where(Recording.experiment_id == experiment_id)
    if camera_id is not None:
        q = q.where(Recording.camera_id == camera_id)
    return [recording_out(r) for r in session.scalars(q)]


@router.get("/recordings/{recording_id}", response_model=RecordingOut)
def get_recording(recording_id: int, session: Session = Depends(db_session)):
    return recording_out(get_or_404(session, Recording, recording_id, "Recording"))


@router.get("/recordings/{recording_id}/file")
def recording_file(recording_id: int, download: bool = Query(default=False), session: Session = Depends(db_session)):
    """The video file; range requests let the browser player seek."""
    r = get_or_404(session, Recording, recording_id, "Recording")
    path = Path(r.path)
    if not inside_recordings(path) or not path.is_file():
        raise HTTPException(404, "The video file is missing. It may have been deleted from the data folder.")
    name = f"cvscope-run{r.run_id}-{r.kind}-{r.started_at:%Y%m%d-%H%M%S}{path.suffix}"
    return FileResponse(path, media_type=r.mime, filename=name if download else None, content_disposition_type="attachment" if download else "inline")


@router.delete("/recordings/{recording_id}", status_code=204)
def delete_recording(recording_id: int, session: Session = Depends(db_session)):
    delete_recordings(session, [get_or_404(session, Recording, recording_id, "Recording")])


@router.delete("/runs/{run_id}/recordings", status_code=204)
def delete_run_recordings(run_id: int, session: Session = Depends(db_session)):
    get_or_404(session, Run, run_id, "Run")
    delete_recordings(session, list(session.scalars(select(Recording).where(Recording.run_id == run_id))))
