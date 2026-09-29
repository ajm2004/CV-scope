"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pathscope import __version__
from pathscope.api.router import api_router
from pathscope.api.routes.preview import ws_router as preview_ws_router
from pathscope.api.routes.runs import ws_router
from pathscope.config import REPO_ROOT, get_settings
from pathscope.db.migrate import upgrade_database
from pathscope.logging_setup import configure_logging, get_logger
from pathscope.recognition.api.live import ws_router as recognition_ws_router
from pathscope.services.preview import get_preview_manager
from pathscope.workers.supervisor import get_supervisor

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    settings.ensure_directories()
    upgrade_database()
    log.info("pathscope started", version=__version__, data_dir=str(settings.resolved_data_dir), database=settings.resolved_database_url.split("@")[-1])
    try:
        # Retention sweeps of the licensed recognition modules (no-op without their data)
        from pathscope.recognition.events.retention import start_maintenance, stop_maintenance

        start_maintenance()
    except Exception as exc:  # noqa: BLE001 - the core keeps running without them
        log.warning("recognition maintenance not started", error=str(exc))
        stop_maintenance = None  # type: ignore[assignment]
    from pathscope.storage import recordings as recording_store

    recording_store.start_maintenance()  # video retention and unfinished files
    from pathscope.anomaly import service as anomaly_service

    anomaly_service.start_maintenance()  # evidence retention; model calls interrupted by a restart
    from pathscope.relationships import service as relationship_service

    relationship_service.start_maintenance()  # relationship retention; analyses interrupted by a restart
    yield
    relationship_service.stop_maintenance()
    from pathscope.crosscam.service import get_crosscam_service

    get_crosscam_service().stop()
    anomaly_service.stop_maintenance()
    recording_store.stop_maintenance()
    if stop_maintenance is not None:
        stop_maintenance()
    get_preview_manager().stop_all()
    get_supervisor().stop_all()
    log.info("pathscope stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="CV-Scope API",
        version=__version__,
        description="Configurable computer-vision monitoring and research platform for fixed cameras.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Frame-Width", "X-Frame-Height", "X-Media-Time", "Content-Disposition"],
    )
    app.include_router(api_router)
    app.include_router(ws_router)
    app.include_router(preview_ws_router)
    app.include_router(recognition_ws_router)  # guided live enrollment (licensed module)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):  # pragma: no cover - safety net
        log.error("unhandled error", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=500, content={"detail": f"{type(exc).__name__}: {exc}"})

    # Serve the built frontend when present (single-process deployment)
    dist = REPO_ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        dist_root = dist.resolve()

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            # Only files inside the built frontend: an encoded "../" must never
            # reach the data directory, the database or keys next to the repository
            candidate = (dist_root / full_path).resolve()
            if full_path and candidate.is_relative_to(dist_root) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist_root / "index.html")

    return app


app = create_app()
_ = Path
