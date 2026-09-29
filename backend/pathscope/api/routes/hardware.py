"""Hardware discovery and recommendations."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, settings_dep
from pathscope.api.routes.system import cached_hardware, refresh_hardware
from pathscope.config import Settings
from pathscope.db.models import Benchmark
from pathscope.hardware import build_recommendations
from pathscope.models.manager import get_model_manager
from pathscope.vision.inference.runtime import probe_runtimes, select_runtime

router = APIRouter(prefix="/hardware", tags=["hardware"])


@router.get("")
def hardware(refresh: bool = Query(default=False), settings: Settings = Depends(settings_dep)) -> dict:
    report = refresh_hardware(settings) if refresh else cached_hardware(settings)
    return report.to_dict()


def _recognition_modules(session: Session) -> dict[str, dict] | None:
    """Active licensed modules and their stacks for the capacity estimate (None in the core default)."""
    try:
        from pathscope.recognition.common.config import all_recognition_settings
        from pathscope.recognition.service import module_states

        values = all_recognition_settings(session)
        states = module_states(session, values)
        return {
            "face": {"active": states["face"].active, "stack": str(values.get("recognition.face.stack") or "opencv")},
            "plate": {"active": states["plate"].active, "stack": "onnx"},
        }
    except Exception:  # noqa: BLE001 - fail closed: no impact reported
        return None


@router.get("/recommendations")
def recommendations(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    report = cached_hardware(settings)
    installed = get_model_manager().installed_ids()
    benchmarked = session.scalar(select(Benchmark.id).limit(1)) is not None
    recs = build_recommendations(report, installed, benchmarked=benchmarked, recognition=_recognition_modules(session))
    return recs.to_dict()


@router.get("/recognition-impact")
def recognition_impact_(face: bool = Query(default=True), plate: bool = Query(default=True), face_stack: str = Query(default="opencv"), model_id: str | None = Query(default=None), processing_fps: float = Query(default=10.0, gt=0), settings: Settings = Depends(settings_dep)) -> dict:
    """What enabling the recognition modules would cost, whether or not they are licensed."""
    from pathscope.hardware.recommend import recognition_impact

    report = cached_hardware(settings)
    modules = {"face": {"active": face, "stack": face_stack}, "plate": {"active": plate, "stack": "onnx"}}
    return recognition_impact(report, modules, model_id, processing_fps) or {"modules": {}, "warning": None}


@router.get("/runtimes")
def runtimes(device: str = Query(default="auto"), provider: str = Query(default="auto")) -> dict:
    probe_runtimes.cache_clear()
    items = [r.to_dict() for r in probe_runtimes()]
    try:
        choice = select_runtime(provider, device).to_dict()
        error = None
    except RuntimeError as exc:
        choice = None
        error = str(exc)
    return {"runtimes": items, "auto_choice": choice, "error": error}
