"""Local benchmark of a detector + tracker on this machine.

Measures preprocessing, detector inference and tracker time per frame, the
resulting pipeline FPS, and CPU / RAM / VRAM usage. Runs on a video file when
one is available, otherwise on synthetic frames (timing only, no detections).
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field

import numpy as np
import psutil

from pathscope.logging_setup import get_logger
from pathscope.models.catalog import get_model_spec
from pathscope.models.manager import get_model_manager
from pathscope.vision.detectors import DetectorConfig, create_detector
from pathscope.vision.inference.runtime import resolve_device
from pathscope.vision.trackers import create_tracker

log = get_logger(__name__)


@dataclass
class BenchmarkJob:
    id: str
    model_id: str
    device: str
    image_size: int
    status: str = "queued"
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    results: dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _vram_used_mb() -> float | None:
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return pynvml.nvmlDeviceGetMemoryInfo(h).used / (1024**2)
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001
        return None


def run_benchmark(
    model_id: str,
    device: str = "auto",
    image_size: int | None = None,
    video_path: str | None = None,
    max_frames: int = 120,
    max_seconds: float = 25.0,
    progress_cb=None,
    tracker_id: str = "bytetrack",
    tracker_settings: dict | None = None,
) -> dict:
    spec = get_model_spec(model_id)
    if spec.task != "detection":
        raise ValueError(f"{spec.name} is not a detector and cannot be benchmarked on its own")
    manager = get_model_manager()
    spec, weights = manager.resolve_for_inference(model_id)
    size = int(image_size or spec.default_image_size)
    resolved_device, device_reason = resolve_device(device)
    if spec.provider == "onnxruntime":
        resolved_device = "cuda" if resolved_device.startswith("cuda") else "cpu"

    cfg = DetectorConfig(
        model_id=spec.id,
        weights_path=weights,
        provider=spec.provider,
        device=resolved_device,
        image_size=size,
        confidence=0.25,
        iou=0.5,
        half=resolved_device.startswith("cuda"),
        extra={"family": spec.family},
    )
    detector = create_detector(cfg)
    tracker = create_tracker(tracker_id or "bytetrack", tracker_settings or {}, device=resolved_device, models_dir=str(manager.models_dir))

    # ---- frames
    frames: list[np.ndarray] = []
    source_w = source_h = 0
    synthetic = False
    if video_path:
        from pathscope.vision.sources.file_source import FileSource

        src = FileSource(video_path)
        info = src.open()
        source_w, source_h = info.width, info.height
        while len(frames) < max_frames:
            p = src.read()
            if p is None:
                break
            frames.append(p.frame)
        src.close()
    if not frames:
        synthetic = True
        source_w, source_h = 1280, 720
        rng = np.random.default_rng(0)
        base = rng.integers(0, 255, size=(source_h, source_w, 3), dtype=np.uint8)
        frames = [np.roll(base, i * 3, axis=1) for i in range(min(max_frames, 60))]

    proc = psutil.Process()
    vram_before = _vram_used_mb()
    t_load0 = time.perf_counter()
    detector.load()
    load_ms = (time.perf_counter() - t_load0) * 1000.0
    detector.warmup(source_w, source_h, iterations=2)
    vram_after_load = _vram_used_mb()

    pre_ms: list[float] = []
    det_ms: list[float] = []
    trk_ms: list[float] = []
    total_ms: list[float] = []
    cpu_samples: list[float] = []
    proc.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None)
    n_dets = 0
    t_start = time.perf_counter()
    for i, frame in enumerate(frames):
        if time.perf_counter() - t_start > max_seconds:
            break
        t0 = time.perf_counter()
        dets = detector.detect(frame)
        t1 = time.perf_counter()
        tracker.update(dets, i, i / 25.0, frame=frame)
        t2 = time.perf_counter()
        n_dets += len(dets)
        pre_ms.append(detector.last_preprocess_ms)
        det_ms.append(detector.last_inference_ms)
        trk_ms.append((t2 - t1) * 1000.0)
        total_ms.append((t2 - t0) * 1000.0)
        if i % 10 == 0:
            cpu_samples.append(psutil.cpu_percent(interval=None))
            if progress_cb:
                progress_cb(i / max(len(frames), 1))
    elapsed = time.perf_counter() - t_start
    vram_peak = _vram_used_mb()
    rss_mb = proc.memory_info().rss / (1024**2)

    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {"mean": None, "median": None, "p95": None}
        arr = np.array(xs)
        return {
            "mean": round(float(arr.mean()), 2),
            "median": round(float(np.median(arr)), 2),
            "p95": round(float(np.percentile(arr, 95)), 2),
        }

    n = len(total_ms)
    results = {
        "model_id": spec.id,
        "model_name": spec.name,
        "provider": spec.provider,
        "device": detector.resolved_device,
        "device_reason": device_reason,
        "execution_providers": getattr(detector, "execution_providers", None),
        "source": "synthetic frames (timing only; no objects to detect)" if synthetic else video_path,
        "source_resolution": [source_w, source_h],
        "inference_resolution": size,
        "frames": n,
        "detections_total": n_dets,
        "load_ms": round(load_ms, 1),
        "preprocess_ms": _stats(pre_ms),
        "detector_ms": _stats(det_ms),
        "tracker_ms": _stats(trk_ms),
        "tracker_id": tracker.id,
        "tracker": tracker.describe(),
        "tracker_stats": tracker.stats().to_dict(),
        "pipeline_ms": _stats(total_ms),
        "pipeline_fps": round(n / elapsed, 1) if elapsed > 0 and n else None,
        "cpu_percent_mean": round(float(np.mean(cpu_samples)), 1) if cpu_samples else None,
        "process_rss_mb": round(rss_mb, 1),
        "vram_used_mb_before": round(vram_before, 1) if vram_before is not None else None,
        "vram_used_mb_after_load": round(vram_after_load, 1) if vram_after_load is not None else None,
        "vram_used_mb_peak": round(vram_peak, 1) if vram_peak is not None else None,
        "measured_at": time.time(),
        "note": "Pipeline FPS excludes video decoding and drawing; real runs are bounded by the source frame rate.",
    }
    detector.close()
    tracker.close()
    return results


class BenchmarkRunner:
    def __init__(self) -> None:
        self._jobs: dict[str, BenchmarkJob] = {}
        self._lock = threading.Lock()

    def start(self, model_id: str, device: str, image_size: int | None, video_path: str | None, on_done=None, tracker_id: str = "bytetrack", tracker_settings: dict | None = None) -> BenchmarkJob:
        job = BenchmarkJob(id=uuid.uuid4().hex[:12], model_id=model_id, device=device, image_size=image_size or 0)
        with self._lock:
            self._jobs[job.id] = job

        def _run():
            job.status = "running"
            job.message = "Loading model"
            try:
                res = run_benchmark(
                    model_id, device, image_size, video_path,
                    progress_cb=lambda p: setattr(job, "progress", p),
                    tracker_id=tracker_id, tracker_settings=tracker_settings,
                )
                job.results = res
                job.image_size = res["inference_resolution"]
                job.status = "done"
                job.progress = 1.0
                job.message = "Done"
                if on_done:
                    on_done(job)
            except Exception as exc:  # noqa: BLE001
                job.status = "failed"
                job.error = str(exc)
                job.message = "Failed"
                log.error("benchmark failed", model_id=model_id, error=str(exc))
            finally:
                job.finished_at = time.time()

        threading.Thread(target=_run, daemon=True, name=f"bench-{model_id}").start()
        return job

    def get(self, job_id: str) -> BenchmarkJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)]


_runner: BenchmarkRunner | None = None


def get_benchmark_runner() -> BenchmarkRunner:
    global _runner
    if _runner is None:
        _runner = BenchmarkRunner()
    return _runner
