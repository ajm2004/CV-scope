"""Uploaded and registered video files."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404, settings_dep
from pathscope.api.schemas import VideoOut
from pathscope.config import REPO_ROOT, Settings
from pathscope.db.models import Camera, Video
from pathscope.vision.sources import SourceError
from pathscope.vision.sources.file_source import probe_video_file

router = APIRouter(prefix="/videos", tags=["videos"])

ALLOWED = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm", ".mpg", ".mpeg", ".ts", ".wmv"}
SAMPLES_DIR = REPO_ROOT / "samples" / "videos"


def _safe_name(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base or "video.mp4"


def _register(session: Session, path: Path, filename: str) -> Video:
    try:
        info = probe_video_file(str(path))
    except SourceError as exc:
        raise HTTPException(400, f"The file could not be opened as a video: {exc}") from exc
    v = Video(
        filename=filename,
        path=str(path),
        size_bytes=path.stat().st_size,
        duration_s=info.duration_s,
        fps=info.fps,
        width=info.width,
        height=info.height,
        frame_count=info.frame_count,
    )
    session.add(v)
    session.commit()
    session.refresh(v)
    return v


@router.get("", response_model=list[VideoOut])
def list_videos(session: Session = Depends(db_session)):
    return list(session.scalars(select(Video).order_by(Video.created_at.desc())))


@router.post("", response_model=VideoOut, status_code=201)
async def upload_video(file: UploadFile, session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)):
    name = _safe_name(file.filename or "video.mp4")
    if Path(name).suffix.lower() not in ALLOWED:
        raise HTTPException(400, f"Unsupported file type '{Path(name).suffix}'. Allowed: {', '.join(sorted(ALLOWED))}")
    dest = settings.videos_dir / f"{int(time.time())}_{name}"
    with open(dest, "wb") as fh:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
    try:
        return _register(session, dest, name)
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise


@router.post("/register", response_model=VideoOut, status_code=201)
def register_local(path: str = Query(description="Absolute path of a video file on this computer"), session: Session = Depends(db_session)):
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise HTTPException(400, f"File not found: {p}")
    return _register(session, p.resolve(), p.name)


@router.get("/samples")
def sample_videos(session: Session = Depends(db_session)) -> list[dict]:
    """Sample clips downloaded by scripts/download_samples.py (the Windows
    installer's "Sample videos" option), with the id of the video already
    registered for each file, so the first-run wizard can offer them."""
    if not SAMPLES_DIR.is_dir():
        return []
    registered = {v.path: v.id for v in session.scalars(select(Video))}
    samples = []
    for p in sorted(SAMPLES_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in ALLOWED and p.stat().st_size > 0:
            path = str(p.resolve())
            samples.append({"name": p.name, "path": path, "size_bytes": p.stat().st_size, "video_id": registered.get(path)})
    return samples


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: int, session: Session = Depends(db_session)):
    return get_or_404(session, Video, video_id, "Video")


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, delete_file: bool = Query(default=True), session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)):
    v = get_or_404(session, Video, video_id, "Video")
    cams = list(session.scalars(select(Camera).where(Camera.video_id == v.id)))
    for c in cams:
        c.video_id = None
    p = Path(v.path)
    session.delete(v)
    session.commit()
    if delete_file and p.exists() and settings.videos_dir in p.parents:
        p.unlink(missing_ok=True)


@router.get("/{video_id}/file")
def video_file(video_id: int, request: Request, session: Session = Depends(db_session)):
    """Serve the file with HTTP range support for the review player."""
    v = get_or_404(session, Video, video_id, "Video")
    p = Path(v.path)
    if not p.exists():
        raise HTTPException(404, "video file is missing on disk")
    size = p.stat().st_size
    media_type = {"mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "mkv": "video/x-matroska"}.get(p.suffix.lower().lstrip("."), "application/octet-stream")
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(p, media_type=media_type, headers={"Accept-Ranges": "bytes"})
    m = re.match(r"bytes=(\d*)-(\d*)", range_header)
    if not m:
        raise HTTPException(416, "invalid range")
    start = int(m.group(1)) if m.group(1) else 0
    end = int(m.group(2)) if m.group(2) else size - 1
    end = min(end, size - 1)
    if start > end:
        raise HTTPException(416, "invalid range")
    length = end - start + 1

    def _iter():
        with open(p, "rb") as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(1 << 20, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {"Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(length)}
    return StreamingResponse(_iter(), status_code=206, media_type=media_type, headers=headers)


@router.post("/{video_id}/copy-to-data", response_model=VideoOut)
def copy_to_data(video_id: int, session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)):
    """Copy a registered external file into the data directory."""
    v = get_or_404(session, Video, video_id, "Video")
    src = Path(v.path)
    if settings.videos_dir in src.parents:
        return v
    dest = settings.videos_dir / f"{int(time.time())}_{_safe_name(src.name)}"
    shutil.copy2(src, dest)
    v.path = str(dest)
    session.commit()
    session.refresh(v)
    return v
