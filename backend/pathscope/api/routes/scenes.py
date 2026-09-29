"""Scene configurations (versioned per camera)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404
from pathscope.api.schemas import SceneIn, SceneOut
from pathscope.db.models import Camera, Run, SceneConfig
from pathscope.domain.scene import SceneDocument, empty_scene

router = APIRouter(tags=["scenes"])


def _latest(session: Session, camera_id: int) -> SceneConfig | None:
    return session.scalar(select(SceneConfig).where(SceneConfig.camera_id == camera_id).order_by(SceneConfig.version.desc()).limit(1))


@router.get("/cameras/{camera_id}/scenes", response_model=list[SceneOut])
def list_scenes(camera_id: int, session: Session = Depends(db_session)):
    get_or_404(session, Camera, camera_id, "Camera")
    return list(session.scalars(select(SceneConfig).where(SceneConfig.camera_id == camera_id).order_by(SceneConfig.version.desc())))


@router.get("/cameras/{camera_id}/scenes/latest", response_model=SceneOut)
def latest_scene(camera_id: int, session: Session = Depends(db_session)):
    cam = get_or_404(session, Camera, camera_id, "Camera")
    latest = _latest(session, camera_id)
    if latest is None:
        doc = empty_scene(cam.width or 1920, cam.height or 1080)
        latest = SceneConfig(camera_id=camera_id, version=1, name="Scene v1", document=doc.model_dump())
        session.add(latest)
        session.commit()
        session.refresh(latest)
    return latest


@router.post("/cameras/{camera_id}/scenes", response_model=SceneOut, status_code=201)
def save_scene(camera_id: int, body: SceneIn, session: Session = Depends(db_session)):
    """Save the scene. A frozen version (already used by a run) is never
    modified: a new version is created instead."""
    get_or_404(session, Camera, camera_id, "Camera")
    latest = _latest(session, camera_id)
    doc: SceneDocument = body.document
    if latest is None or latest.frozen or body.new_version:
        version = (latest.version + 1) if latest else 1
        sc = SceneConfig(
            camera_id=camera_id,
            version=version,
            name=body.name or f"Scene v{version}",
            document=doc.model_dump(),
            created_from_id=latest.id if latest else None,
        )
        session.add(sc)
    else:
        latest.document = doc.model_dump()
        if body.name:
            latest.name = body.name
        sc = latest
    session.commit()
    session.refresh(sc)
    return sc


@router.get("/scenes/{scene_id}", response_model=SceneOut)
def get_scene(scene_id: int, session: Session = Depends(db_session)):
    return get_or_404(session, SceneConfig, scene_id, "Scene")


@router.delete("/scenes/{scene_id}", status_code=204)
def delete_scene(scene_id: int, session: Session = Depends(db_session)):
    sc = get_or_404(session, SceneConfig, scene_id, "Scene")
    used = session.scalar(select(Run.id).where(Run.scene_config_id == scene_id).limit(1))
    if used is not None:
        raise HTTPException(409, "This scene version was used by a run and is kept for reproducibility.")
    session.delete(sc)
    session.commit()


@router.post("/scenes/validate")
def validate_scene(document: SceneDocument) -> dict:
    """Structural validation plus warnings a researcher should see before running."""
    warnings: list[str] = []
    if not document.objects:
        warnings.append("The scene has no lines or zones; the run will only produce track summaries.")
    for r in document.routes:
        if r.start == r.end:
            warnings.append(f"Route '{r.name}' starts and ends at the same object.")
    starts = {r.start for r in document.routes}
    for s in starts:
        ends = {r.end for r in document.routes if r.start == s}
        if len(ends) < len([r for r in document.routes if r.start == s]):
            warnings.append("Two routes share the same start and end object; they cannot be distinguished.")
    for o in document.objects:
        if not o.name:
            warnings.append(f"Object {o.id} has no name.")
    return {"ok": True, "warnings": warnings, "objects": len(document.objects), "routes": len(document.routes)}
