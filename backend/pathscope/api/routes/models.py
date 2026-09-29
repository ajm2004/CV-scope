"""Model manager endpoints: catalog, install jobs, benchmarks, trackers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.deps import db_session, get_or_404, settings_dep
from pathscope.api.routes.system import cached_hardware
from pathscope.api.schemas import BenchmarkIn
from pathscope.config import Settings
from pathscope.db.models import Benchmark, Video
from pathscope.db.session import get_session_factory
from pathscope.hardware import build_recommendations
from pathscope.models.benchmark import get_benchmark_runner
from pathscope.models.catalog import CATALOG_BY_ID
from pathscope.models.manager import get_model_manager
from pathscope.vision.trackers import tracker_catalog, validate_tracker_settings

router = APIRouter(prefix="/models", tags=["models"])


@router.get("")
def list_models(session: Session = Depends(db_session), settings: Settings = Depends(settings_dep)) -> dict:
    manager = get_model_manager()
    items = manager.list_models()
    report = cached_hardware(settings)
    recs = build_recommendations(report, manager.installed_ids())
    tier_by_model = {t.model_id: t.tier for t in recs.tiers}
    latest_bench: dict[str, dict] = {}
    for b in session.scalars(select(Benchmark).order_by(Benchmark.created_at.desc())):
        latest_bench.setdefault(b.model_id, {"device": b.device, "results": b.results, "created_at": b.created_at})
    for it in items:
        it["recommended_tier"] = tier_by_model.get(it["id"])
        it["benchmark"] = latest_bench.get(it["id"])
    return {"models": items, "recommendations": recs.to_dict(), "trackers": tracker_catalog(settings.resolved_models_dir)}


@router.get("/jobs")
def list_jobs() -> dict:
    return {"install": get_model_manager().list_jobs(), "benchmark": get_benchmark_runner().list()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = get_model_manager().get_job(job_id)
    if job is None:
        bj = get_benchmark_runner().get(job_id)
        if bj is None:
            raise HTTPException(404, "job not found")
        return bj.to_dict()
    return job.to_dict()


@router.post("/{model_id}/install")
def install_model(model_id: str) -> dict:
    if model_id not in CATALOG_BY_ID:
        raise HTTPException(404, f"unknown model '{model_id}'")
    spec = CATALOG_BY_ID[model_id]
    manager = get_model_manager()
    from pathscope.vision.inference.runtime import installed_providers

    if not installed_providers().get(spec.provider):
        raise HTTPException(
            400,
            f"The '{spec.requires_package}' package is not installed in this environment, so {spec.name} cannot be used. See docs/installation.md.",
        )
    job = manager.install(model_id)
    return job.to_dict()


@router.delete("/{model_id}")
def delete_model(model_id: str) -> dict:
    if model_id not in CATALOG_BY_ID:
        raise HTTPException(404, f"unknown model '{model_id}'")
    removed = get_model_manager().delete(model_id)
    return {"removed": removed}


@router.post("/{model_id}/benchmark")
def benchmark_model(model_id: str, body: BenchmarkIn, session: Session = Depends(db_session)) -> dict:
    if model_id not in CATALOG_BY_ID:
        raise HTTPException(404, f"unknown model '{model_id}'")
    manager = get_model_manager()
    if CATALOG_BY_ID[model_id].task != "detection":
        raise HTTPException(400, "Only detectors can be benchmarked; appearance models are measured as part of a BoT-SORT benchmark.")
    if not manager.is_installed(CATALOG_BY_ID[model_id]):
        raise HTTPException(400, "Install the model before benchmarking it.")
    try:
        validate_tracker_settings(body.tracker_id, body.tracker_settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    video_path = None
    if body.video_id is not None:
        video = get_or_404(session, Video, body.video_id, "Video")
        video_path = video.path
    else:
        latest = session.scalar(select(Video).order_by(Video.created_at.desc()).limit(1))
        if latest is not None:
            video_path = latest.path

    def _persist(job) -> None:
        s = get_session_factory()()
        try:
            s.add(Benchmark(model_id=job.model_id, provider=job.results.get("provider", ""), device=job.results.get("device", ""), results=job.results))
            s.commit()
        finally:
            s.close()

    job = get_benchmark_runner().start(
        model_id, body.device, body.image_size, video_path, on_done=_persist,
        tracker_id=body.tracker_id, tracker_settings=body.tracker_settings,
    )
    return job.to_dict()


@router.get("/benchmarks")
def list_benchmarks(session: Session = Depends(db_session)) -> list[dict]:
    rows = session.scalars(select(Benchmark).order_by(Benchmark.created_at.desc()).limit(100))
    return [{"id": b.id, "model_id": b.model_id, "provider": b.provider, "device": b.device, "results": b.results, "created_at": b.created_at} for b in rows]
