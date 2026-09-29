"""Model manager: installation state, downloads, exports and removal.

Installs run in background threads and report progress through an in-memory
job registry so the UI can poll them.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from pathscope.config import Settings, get_settings
from pathscope.logging_setup import get_logger
from pathscope.models.catalog import CATALOG, CATALOG_BY_ID, ModelSpec, get_model_spec
from pathscope.vision.inference.runtime import installed_providers

log = get_logger(__name__)


@dataclass
class InstallJob:
    id: str
    model_id: str
    status: str = "queued"  # queued | running | done | failed
    progress: float = 0.0
    message: str = ""
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    path: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ModelManager:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.models_dir = self.settings.resolved_models_dir
        self.models_dir.mkdir(parents=True, exist_ok=True)
        # torchvision / torch hub weights go under the models directory too
        os.environ.setdefault("TORCH_HOME", str(self.models_dir / "torch"))
        self._jobs: dict[str, InstallJob] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------- paths
    def model_dir(self, spec: ModelSpec) -> Path:
        return self.models_dir / spec.subdir if spec.subdir else self.models_dir

    def weights_path(self, spec: ModelSpec) -> Path | None:
        if spec.provider == "torchvision":
            return None
        return self.model_dir(spec) / spec.file_name

    def extra_paths(self, spec: ModelSpec) -> list[Path]:
        return [self.model_dir(spec) / f["file_name"] for f in spec.extra_files]

    def archive_path(self, spec: ModelSpec) -> Path | None:
        if not spec.archive_member or not spec.download_url:
            return None
        return self.models_dir / "_archives" / spec.download_url.rsplit("/", 1)[-1]

    def _torchvision_installed(self, spec: ModelSpec) -> bool:
        hub = Path(os.environ.get("TORCH_HOME", str(self.models_dir / "torch"))) / "hub" / "checkpoints"
        if not hub.exists():
            return False
        stem = {
            "tv-ssdlite320": "ssdlite320_mobilenet_v3_large",
            "tv-fasterrcnn-mobilenet": "fasterrcnn_mobilenet_v3_large_fpn",
            "tv-fasterrcnn-r50v2": "fasterrcnn_resnet50_fpn_v2",
            "appearance-resnet18": "resnet18-",
        }.get(spec.id, spec.id)
        return any(p.name.startswith(stem) for p in hub.iterdir())

    def is_installed(self, spec: ModelSpec) -> bool:
        if spec.task == "appearance":
            from pathscope.vision.trackers.appearance import cnn_weights_installed

            return cnn_weights_installed("resnet18", self.models_dir)
        if spec.provider == "torchvision":
            return self._torchvision_installed(spec)
        path = self.weights_path(spec)
        if not (path and path.exists() and path.stat().st_size > 0):
            return False
        return all(p.exists() and p.stat().st_size > 0 for p in self.extra_paths(spec))

    def installed_size(self, spec: ModelSpec) -> int | None:
        path = self.weights_path(spec)
        if path and path.exists():
            return path.stat().st_size
        return None

    def installed_ids(self) -> set[str]:
        return {m.id for m in CATALOG if self.is_installed(m)}

    # ------------------------------------------------------------- listing
    def describe(self, spec: ModelSpec) -> dict:
        providers = installed_providers()
        d = spec.to_dict()
        d["installed"] = self.is_installed(spec)
        d["installed_size_bytes"] = self.installed_size(spec)
        d["provider_available"] = bool(providers.get(spec.provider))
        d["path"] = str(self.weights_path(spec)) if self.weights_path(spec) else None
        if spec.export_from:
            base = CATALOG_BY_ID.get(spec.export_from)
            d["export_source_installed"] = bool(base and self.is_installed(base))
            d["export_requires"] = "ultralytics"
        active = self.active_job_for(spec.id)
        d["job"] = active.to_dict() if active else None
        return d

    def list_models(self) -> list[dict]:
        return [self.describe(m) for m in CATALOG]

    # ------------------------------------------------------------- jobs
    def active_job_for(self, model_id: str) -> InstallJob | None:
        with self._lock:
            for job in self._jobs.values():
                if job.model_id == model_id and job.status in ("queued", "running"):
                    return job
        return None

    def get_job(self, job_id: str) -> InstallJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda j: j.started_at, reverse=True)]

    def install(self, model_id: str) -> InstallJob:
        spec = get_model_spec(model_id)
        existing = self.active_job_for(model_id)
        if existing:
            return existing
        job = InstallJob(id=uuid.uuid4().hex[:12], model_id=model_id)
        with self._lock:
            self._jobs[job.id] = job
        th = threading.Thread(target=self._run_install, args=(spec, job), daemon=True, name=f"install-{model_id}")
        th.start()
        return job

    def _run_install(self, spec: ModelSpec, job: InstallJob) -> None:
        job.status = "running"
        try:
            if spec.provider == "torchvision":
                self._install_torchvision(spec, job)
            elif spec.export_from:
                self._install_export(spec, job)
            elif spec.download_url:
                self._download(spec, job)
            else:
                raise RuntimeError("This model has no download source.")
            job.status = "done"
            job.progress = 1.0
            job.message = "Installed"
            log.info("model installed", model_id=spec.id, path=job.path)
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            job.message = "Failed"
            log.error("model install failed", model_id=spec.id, error=str(exc))
        finally:
            job.finished_at = time.time()

    @staticmethod
    def _fetch(url: str, dest: Path, job: InstallJob, label: str, progress_range: tuple[float, float] = (0.0, 0.99)) -> None:
        """Download ``url`` to ``dest`` atomically, with progress and a guard
        against Git LFS pointer files (a hosting quirk that returns a 130-byte
        text file instead of the model)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        job.message = f"Downloading {label}"
        lo, hi = progress_range
        with httpx.stream("GET", url, follow_redirects=True, timeout=60.0) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            done = 0
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1 << 16):
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        job.progress = lo + (hi - lo) * min(1.0, done / total)
        head = tmp.read_bytes()[:64] if tmp.stat().st_size < 2048 else b""
        if head.startswith(b"version https://git-lfs"):
            tmp.unlink()
            raise RuntimeError(f"The download of {label} returned a Git LFS pointer instead of the file; the hosting URL must point at the LFS media endpoint.")
        if dest.exists():
            dest.unlink()
        tmp.rename(dest)

    def _download(self, spec: ModelSpec, job: InstallJob) -> None:
        assert spec.download_url
        dest = self.weights_path(spec)
        assert dest is not None
        n_extra = len(spec.extra_files)
        main_range = (0.0, 0.99 if not n_extra else 0.9)
        if spec.archive_member:
            self._download_archive_member(spec, job, dest, main_range)
        else:
            self._fetch(spec.download_url, dest, job, spec.file_name, main_range)
        for i, extra in enumerate(spec.extra_files):
            lo = 0.9 + 0.09 * i / n_extra
            self._fetch(extra["url"], self.model_dir(spec) / extra["file_name"], job, extra["file_name"], (lo, lo + 0.09 / n_extra))
        job.path = str(dest)

    def _download_archive_member(self, spec: ModelSpec, job: InstallJob, dest: Path, progress_range: tuple[float, float]) -> None:
        """Weights packed in a zip: keep the archive under ``_archives`` so a
        second model from the same pack does not download it again, and extract
        only the wanted member (never the rest of the pack)."""
        import zipfile

        archive = self.archive_path(spec)
        assert archive is not None and spec.download_url and spec.archive_member
        if not (archive.exists() and archive.stat().st_size > 1_000_000):
            self._fetch(spec.download_url, archive, job, archive.name, progress_range)
        job.message = f"Extracting {spec.archive_member}"
        with zipfile.ZipFile(archive) as zf:
            names = [n for n in zf.namelist() if n == spec.archive_member or n.endswith("/" + spec.archive_member)]
            if not names:
                raise RuntimeError(f"{archive.name} does not contain {spec.archive_member}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(dest.suffix + ".part")
            with zf.open(names[0]) as src, open(tmp, "wb") as fh:
                while True:
                    chunk = src.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
            if dest.exists():
                dest.unlink()
            tmp.rename(dest)

    def _install_export(self, spec: ModelSpec, job: InstallJob) -> None:
        base = get_model_spec(spec.export_from or "")
        base_path = self.weights_path(base)
        assert base_path is not None
        if not base_path.exists():
            job.message = f"Downloading source weights {base.file_name}"
            self._download(base, job)
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Exporting to ONNX requires the 'ultralytics' package.") from exc
        job.message = "Exporting to ONNX"
        job.progress = 0.5
        model = YOLO(str(base_path))
        exported = model.export(format="onnx", imgsz=spec.default_image_size, dynamic=False, simplify=True)
        out = Path(str(exported))
        dest = self.weights_path(spec)
        assert dest is not None
        if out.resolve() != dest.resolve():
            if dest.exists():
                dest.unlink()
            out.replace(dest)
        job.path = str(dest)

    def _install_torchvision(self, spec: ModelSpec, job: InstallJob) -> None:
        job.message = "Downloading torchvision weights"
        if spec.task == "appearance":
            from pathscope.vision.trackers.appearance import TorchvisionEncoder

            TorchvisionEncoder("resnet18", device="cpu", models_dir=self.models_dir)
            job.path = os.environ.get("TORCH_HOME")
            return
        from pathscope.vision.detectors.base import DetectorConfig
        from pathscope.vision.detectors.torchvision_detector import TorchvisionDetector

        det = TorchvisionDetector(DetectorConfig(spec.id, "", "torchvision", device="cpu"))
        det.load()
        det.close()
        job.path = os.environ.get("TORCH_HOME")

    def delete(self, model_id: str) -> bool:
        spec = get_model_spec(model_id)
        path = self.weights_path(spec)
        removed = False
        if path and path.exists():
            path.unlink()
            removed = True
        for extra in self.extra_paths(spec):
            if extra.exists():
                extra.unlink()
                removed = True
        return removed

    # ------------------------------------------------------------- resolve
    def resolve_for_inference(self, model_id: str) -> tuple[ModelSpec, str]:
        """Return (spec, weights path) or raise if the model is not installed."""
        spec = get_model_spec(model_id)
        if spec.provider == "torchvision":
            return spec, ""
        path = self.weights_path(spec)
        if not path or not path.exists():
            raise FileNotFoundError(
                f"Model '{spec.name}' is not installed. Install it from the Models page first."
            )
        return spec, str(path)


_manager: ModelManager | None = None


def get_model_manager() -> ModelManager:
    global _manager
    if _manager is None:
        _manager = ModelManager()
    return _manager
