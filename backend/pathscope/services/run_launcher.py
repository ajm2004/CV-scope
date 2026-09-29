"""Resolve an experiment into a worker specification and start it.

This is where presets (AUTO / FAST / BALANCED / ACCURATE / CUSTOM), the
hardware recommendation and the installed-model state come together.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.api.routes.system import cached_hardware
from pathscope.config import get_settings
from pathscope.db.models import Camera, Experiment, Run, SceneConfig, Video
from pathscope.domain.recording import recording_settings
from pathscope.domain.scene import SceneDocument, ZoneObject
from pathscope.hardware import build_recommendations
from pathscope.models.catalog import CATALOG_BY_ID
from pathscope.models.manager import get_model_manager
from pathscope.services.preview import get_preview_manager
from pathscope.settings_store import get_setting
from pathscope.vision.inference.runtime import installed_providers, resolve_device
from pathscope.vision.trackers import validate_tracker_settings
from pathscope.vision.trackers.appearance import (
    cnn_weights_installed,
    list_onnx_reid_models,
    reid_dir,
)
from pathscope.workers.messages import WorkerSpec
from pathscope.workers.supervisor import get_supervisor


class LaunchError(RuntimeError):
    pass


@dataclass
class ResolvedInference:
    model_id: str
    provider: str
    family: str
    weights_path: str
    device: str
    image_size: int
    confidence: float
    iou: float
    half: bool
    preset: str
    reason: str


def resolve_inference(session: Session, experiment: Experiment, camera: Camera | None = None) -> ResolvedInference:
    inf = experiment.inference or {}
    preset = (inf.get("preset") or get_setting(session, "default_preset", "auto") or "auto").lower()
    settings = get_settings()
    hw = cached_hardware(settings)
    manager = get_model_manager()
    installed = manager.installed_ids()
    recs = build_recommendations(hw, installed)
    providers = installed_providers()

    # ---- model
    model_id = (experiment.model_id or "").strip()
    if not model_id or model_id == "auto":
        model_id = (get_setting(session, "default_model_id", "") or "").strip()
    tier = None
    fallback_note = ""
    if not model_id or model_id == "auto":
        wanted = {"auto": recs.default_tier, "fast": "fast", "balanced": "balanced", "accurate": "accurate", "custom": recs.default_tier}.get(preset, recs.default_tier)
        tier = next((t for t in recs.tiers if t.tier == wanted), recs.tiers[0])
        model_id = tier.model_id
        # Prefer an installed model of the same tier family when the recommended one is missing
        if model_id not in installed:
            alt = next((t for t in recs.tiers if t.model_id in installed and t.available), None)
            if alt is not None:
                wanted_spec = CATALOG_BY_ID.get(model_id)
                fallback_note = (
                    f"; the {preset.upper()} preset wants {wanted_spec.name if wanted_spec else model_id}, "
                    "which is not installed (install it on the Models page)"
                )
                tier = alt
                model_id = alt.model_id
    spec = CATALOG_BY_ID.get(model_id)
    if spec is None:
        raise LaunchError(f"Unknown model '{model_id}'.")
    if spec.task != "detection":
        raise LaunchError(f"{spec.name} is not an object detector; choose a detector for the experiment.")
    if not providers.get(spec.provider):
        raise LaunchError(f"{spec.name} needs the '{spec.requires_package}' package, which is not installed.")
    try:
        _spec, weights = manager.resolve_for_inference(model_id)
    except FileNotFoundError as exc:
        raise LaunchError(str(exc)) from exc

    # ---- device
    requested_device = inf.get("device") or get_setting(session, "default_device", "auto") or "auto"
    device, reason = resolve_device(requested_device)
    if spec.provider == "onnxruntime":
        device = "cuda" if device.startswith("cuda") else "cpu"

    # ---- size / thresholds
    image_size = inf.get("image_size") or (camera.inference_size if camera is not None else None)
    if not image_size:
        image_size = tier.image_size if tier else spec.default_image_size
        if preset == "accurate" and not tier:
            image_size = max(image_size, 832)
    confidence = float(inf.get("confidence", 0.25))
    iou = float(inf.get("iou", 0.5))
    if preset == "accurate" and "confidence" not in inf:
        confidence = 0.2
    half = inf.get("half")
    if half is None:
        half = device.startswith("cuda")
    return ResolvedInference(
        model_id=model_id,
        provider=spec.provider,
        family=spec.family,
        weights_path=weights,
        device=device,
        image_size=int(image_size),
        confidence=confidence,
        iou=iou,
        half=bool(half),
        preset=preset,
        reason=f"{spec.name} on {device} ({reason}); preset {preset}{fallback_note}",
    )


def check_tracker(tracker_id: str, tracker_settings: dict, models_dir) -> dict:
    """Validate tracker settings and the models they need; returns resolved settings."""
    try:
        resolved = validate_tracker_settings(tracker_id or "bytetrack", tracker_settings or {})
    except ValueError as exc:
        raise LaunchError(f"Tracker settings: {exc}") from exc
    appearance = resolved.get("appearance", "none") if tracker_id == "botsort" else "none"
    if appearance == "cnn" and not cnn_weights_installed("resnet18", models_dir):
        raise LaunchError(
            "BoT-SORT deep appearance features need the 'ResNet-18 appearance features' model. "
            "Install it on the Models page, or choose the colour histogram."
        )
    if appearance.startswith("onnx:"):
        name = appearance.split(":", 1)[1]
        if name not in list_onnx_reid_models(models_dir):
            raise LaunchError(f"Re-identification model '{name}' was not found in {reid_dir(models_dir)}.")
    return resolved


def recognition_for_run(session: Session, experiment: Experiment, camera: Camera) -> dict | None:
    """The licensed recognition modules' payload for this run, or None.

    The core only calls the recognition facade; the facade fails closed
    (no licence, no module). A rule that needs a licensed module whose models
    are missing stops the launch with a clear message."""
    from pathscope.recognition.service import RecognitionNotReady, build_run_payload

    try:
        return build_run_payload(session, experiment, camera)
    except RecognitionNotReady as exc:
        raise LaunchError(str(exc)) from exc


def payload_summary(payload: dict | None) -> dict:
    from pathscope.recognition.service import payload_summary as _summary

    return _summary(payload)


def anomaly_for_run(experiment: Experiment, doc: SceneDocument) -> tuple[dict | None, list[str]]:
    """The Anomaly Assistant's run configuration: settings plus the polygons of the
    watched zones and ignore regions of the scene version this run uses."""
    from pathscope.anomaly.config import FRAME_ZONE_ID, anomaly_settings

    settings = anomaly_settings(experiment.anomaly)
    if not settings.active:
        return None, []
    zones: dict[str, list[list[float]]] = {}
    warnings: list[str] = []
    for z in settings.zones:
        if not z.enabled or z.id == FRAME_ZONE_ID:
            continue
        obj = doc.object_by_id(z.id)
        if not isinstance(obj, ZoneObject) or obj.type == "ignore":
            warnings.append(f"Anomaly zone '{z.name or z.id}' is not a zone of this scene version and is not watched.")
            continue
        zones[z.id] = [[p.x, p.y] for p in obj.points]
        if not z.name:
            z.name = obj.name or z.id
    watched = [z for z in settings.zones if z.enabled and (z.id == FRAME_ZONE_ID or z.id in zones)]
    if not watched:
        raise LaunchError("The Anomaly Assistant is on but none of its zones exists in this scene. Choose zones again on the experiment page, or turn it off.")
    ignore = [[[p.x, p.y] for p in o.points] for o in doc.ignore_regions()]
    return {"settings": settings.model_dump(), "zones": zones, "ignore": ignore}, warnings


def relations_for_run(session: Session, experiment: Experiment, run: Run, doc: SceneDocument, scene_version: int | None) -> tuple[dict | None, list[str]]:
    """The relationship engine's run payload (None when off for the experiment)."""
    from pathscope.relationships.service import get_relationship_service

    return get_relationship_service().prepare_run(session, experiment, run, doc, scene_version)


def scene_for_run(session: Session, experiment: Experiment, camera: Camera, scene_config_id: int | None = None) -> SceneConfig:
    """The scene version a new run uses: an explicit choice, else the version the
    experiment pins, else the camera's latest scene. An experiment left on
    "Latest" therefore follows scene edits; every run records its own version."""
    scene_id = scene_config_id or experiment.scene_config_id
    scene = session.get(SceneConfig, scene_id) if scene_id else None
    if scene is None:
        scene = session.scalar(select(SceneConfig).where(SceneConfig.camera_id == camera.id).order_by(SceneConfig.version.desc()).limit(1))
    if scene is None:
        raise LaunchError("Draw a scene for this camera before starting the experiment.")
    if scene.camera_id != camera.id:
        raise LaunchError("The selected scene belongs to a different camera.")
    return scene


def start_run(session: Session, experiment_id: int, scene_config_id: int | None = None, realtime: bool | None = None, loop: bool = False) -> Run:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None:
        raise LaunchError("Experiment not found.")
    if experiment.camera_id is None:
        raise LaunchError("Assign a camera to the experiment before starting it.")
    camera = session.get(Camera, experiment.camera_id)
    if camera is None:
        raise LaunchError("The camera assigned to this experiment no longer exists.")
    sup = get_supervisor()
    for h in sup.active():
        if h.spec.camera_id == camera.id:
            raise LaunchError(f"Camera '{camera.name}' already has an active run (run {h.run_id}). Stop it first.")

    # ---- scene version: the experiment's pin, else the camera's latest. The run
    # records the version it used; the experiment's choice is left as it is.
    scene = scene_for_run(session, experiment, camera, scene_config_id)
    doc = SceneDocument.model_validate(scene.document)
    scene.frozen = True  # never modified after being used by a run

    # ---- source
    if camera.source_type == "file":
        if camera.video_id is not None:
            video = session.get(Video, camera.video_id)
            if video is None:
                raise LaunchError("The camera references a video that no longer exists.")
            uri = video.path
        else:
            uri = camera.source_uri
        if not uri:
            raise LaunchError("No video file is assigned to this camera.")
    else:
        uri = camera.source_uri
        if camera.source_type in ("rtsp", "http") and not uri:
            raise LaunchError("The camera has no stream address.")

    settings = get_settings()
    check_tracker(experiment.tracker_id or "bytetrack", dict(experiment.tracker_settings or {}), settings.resolved_models_dir)
    inf = resolve_inference(session, experiment, camera)
    inference_cfg = experiment.inference or {}
    processing_fps = inference_cfg.get("processing_fps") or camera.processing_fps
    recognition_payload = recognition_for_run(session, experiment, camera)
    # Video recording applies to live cameras; an uploaded video is its own record
    recording = recording_settings(experiment.recording)
    record = recording.enabled and camera.source_type != "file"
    anomaly, anomaly_warnings = anomaly_for_run(experiment, doc)

    run = Run(
        experiment_id=experiment.id,
        camera_id=camera.id,
        scene_config_id=scene.id,
        status="queued",
        snapshot={
            "resolution": inf.reason, "scene_version": scene.version, "object_classes": experiment.object_classes, "source_type": camera.source_type,
            "recognition": payload_summary(recognition_payload),
            "recording": recording.model_dump() if record else {"mode": "off"},
            "anomaly": {
                "zones": [{"id": z["id"], "name": z["name"], "sensitivity": z["sensitivity"], "validation": z["validation"]} for z in anomaly["settings"]["zones"] if z["enabled"]],
                "warnings": anomaly_warnings,
            } if anomaly else {"enabled": False},
        },
    )
    session.add(run)
    session.flush()
    # Relationship engine: the rule versions this run uses and its live analysis
    relations, relation_warnings = relations_for_run(session, experiment, run, doc, scene.version)
    if relations is not None:
        run.snapshot = {**run.snapshot, "relations": {"analysis_id": relations["analysis_id"], "rules": [{"key": r["key"], "version": r["version"], "name": r["definition"].get("name", "")} for r in relations["rules"]], "warnings": relation_warnings}}
    experiment.status = "running"
    session.commit()
    session.refresh(run)

    spec = WorkerSpec(
        run_id=run.id,
        camera_id=camera.id,
        experiment_id=experiment.id,
        source_type=camera.source_type,
        source_uri=uri,
        scene=doc.model_dump(),
        rules=list(experiment.rules or []),
        tracked_classes=list(experiment.object_classes or []),
        model_id=inf.model_id,
        weights_path=inf.weights_path,
        provider=inf.provider,
        family=inf.family,
        device=inf.device,
        image_size=inf.image_size,
        confidence=inf.confidence,
        iou=inf.iou,
        half=inf.half,
        tracker_id=experiment.tracker_id or "bytetrack",
        tracker_settings=dict(experiment.tracker_settings or {}),
        rotation=camera.rotation,
        crop=camera.crop,
        processing_fps=processing_fps,
        frame_skip=int(inference_cfg.get("frame_skip", 0) or 0),
        source_width=camera.width if camera.source_type == "usb" else None,
        source_height=camera.height if camera.source_type == "usb" else None,
        source_fps=camera.requested_fps if camera.source_type == "usb" else None,
        reconnect=dict(camera.reconnect or {}),
        rtsp_transport=str(get_setting(session, "rtsp_transport", "tcp") or "tcp"),
        realtime=bool(inference_cfg.get("realtime", False) if realtime is None else realtime),
        loop=loop,
        recorded_at=camera.recorded_at.timestamp() if camera.source_type == "file" and camera.recorded_at is not None else None,
        store_trajectories=bool(get_setting(session, "store_trajectories", settings.store_trajectories)),
        webhooks_enabled=bool(get_setting(session, "webhooks_enabled", True)),
        preview_fps=float(get_setting(session, "preview_fps", settings.preview_fps)),
        preview_max_width=int(get_setting(session, "preview_max_width", settings.preview_max_width)),
        preview_jpeg_quality=settings.preview_jpeg_quality,
        log_level=str(get_setting(session, "log_level", settings.log_level) or settings.log_level),
        log_format=settings.log_format,
        models_dir=str(settings.resolved_models_dir),
        recording=recording.model_dump() if record else None,
        recordings_dir=str(settings.recordings_dir / f"run-{run.id}") if record else "",
        recognition=recognition_payload,
        anomaly=anomaly,
        anomaly_dir=str(settings.resolved_data_dir / "anomalies" / f"run-{run.id}") if anomaly else "",
        relations=relations,
    )
    # A camera can be opened by one process at a time: give up the live preview
    # before the run's worker opens the device.
    previews = get_preview_manager()
    try:
        with previews.handing_over(camera.id, camera.source_type, uri):
            sup.start(spec)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = str(exc)
        experiment.status = "draft"
        session.commit()
        raise LaunchError(f"Could not start the worker: {exc}") from exc
    return run
