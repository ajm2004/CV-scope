"""Set up a local vision model without leaving CV-Scope: Ollama and its models.

* status: is Ollama installed, running, which models are downloaded and which
  are loaded in GPU memory right now
* install (Windows): download the official installer from ollama.com, check
  its Authenticode signature (signed by Ollama), run it silently for the
  current user (no administrator rights), then wait for the server
* start: run ``ollama serve`` in the background when it is installed but not running
* pull / delete: through Ollama's own HTTP API, with download progress

Downloads and installs run as background jobs; the page polls ``jobs()``.
Linux and macOS get the official install command to run themselves.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from pathscope.logging_setup import get_logger

log = get_logger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434"
INSTALLER_URL = "https://ollama.com/download/OllamaSetup.exe"
INSTALL_COMMANDS = {
    "Linux": "curl -fsSL https://ollama.com/install.sh | sh",
    "Darwin": "brew install ollama   (or download the app from https://ollama.com/download)",
}
MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,119}$")


def ollama_root(base_url: str | None) -> str:
    """The Ollama server behind an OpenAI-compatible base URL (".../v1" removed)."""
    url = (base_url or "").strip().rstrip("/") or OLLAMA_URL
    return url[:-3] if url.endswith("/v1") else url


def find_ollama() -> str | None:
    exe = shutil.which("ollama")
    if exe:
        return exe
    if platform.system() == "Windows":
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return str(candidate)
    for candidate in ("/usr/local/bin/ollama", "/usr/bin/ollama", "/Applications/Ollama.app/Contents/Resources/ollama"):
        if Path(candidate).is_file():
            return candidate
    return None


@dataclass
class Job:
    id: str
    kind: str  # install | pull
    target: str
    status: str = "running"  # running | done | failed
    message: str = ""
    completed: int = 0
    total: int = 0
    error: str | None = None
    started: float = field(default_factory=time.time)
    ended: float | None = None

    @property
    def progress(self) -> float | None:
        return round(self.completed / self.total, 4) if self.total else None

    def to_dict(self) -> dict:
        return {**asdict(self), "progress": self.progress}


class LocalModels:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ status
    def status(self, root: str) -> dict:
        exe = find_ollama()
        out: dict = {
            "platform": platform.system(), "url": root, "installed": exe is not None, "executable": exe, "running": False, "version": None,
            "models": [], "loaded": [], "can_install": platform.system() == "Windows",
            "install_command": INSTALL_COMMANDS.get(platform.system()), "models_folder": str(Path.home() / ".ollama" / "models"),
        }
        try:
            with httpx.Client(timeout=3.0) as c:
                out["version"] = c.get(f"{root}/api/version").json().get("version")
                out["running"] = True
                out["models"] = [
                    {"name": m.get("name"), "size": m.get("size"), "modified_at": m.get("modified_at"), "parameter_size": (m.get("details") or {}).get("parameter_size"), "quantization": (m.get("details") or {}).get("quantization_level"), "families": (m.get("details") or {}).get("families")}
                    for m in c.get(f"{root}/api/tags").json().get("models") or []
                ]
                out["loaded"] = [{"name": m.get("name"), "size": m.get("size"), "size_vram": m.get("size_vram"), "expires_at": m.get("expires_at")} for m in c.get(f"{root}/api/ps").json().get("models") or []]
        except (httpx.HTTPError, ValueError):
            pass
        return out

    def jobs(self) -> list[dict]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda j: j.started, reverse=True)
            # forget finished jobs after ten minutes
            for j in [j for j in jobs if j.ended and time.time() - j.ended > 600]:
                self._jobs.pop(j.id, None)
            return [j.to_dict() for j in jobs if j.id in self._jobs]

    def _job(self, kind: str, target: str) -> Job:
        with self._lock:
            for j in self._jobs.values():
                if j.kind == kind and j.target == target and j.status == "running":
                    return j
            job = Job(uuid.uuid4().hex[:12], kind, target)
            self._jobs[job.id] = job
            return job

    # ------------------------------------------------------------ server
    def start(self, root: str) -> dict:
        if self.status(root)["running"]:
            return {"started": False, "message": "Ollama is already running."}
        exe = find_ollama()
        if exe is None:
            raise RuntimeError("Ollama is not installed.")
        flags = 0
        if platform.system() == "Windows":
            flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([exe, "serve"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=platform.system() != "Windows")
        if not self._wait_running(root, 30.0):
            raise RuntimeError("Ollama was started but does not answer yet. Try again in a moment.")
        return {"started": True, "message": "Ollama is running."}

    @staticmethod
    def _wait_running(root: str, timeout_s: float) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                httpx.get(f"{root}/api/version", timeout=2.0).raise_for_status()
                return True
            except httpx.HTTPError:
                time.sleep(1.0)
        return False

    # ------------------------------------------------------------ install (Windows)
    def install(self, root: str, download_dir: Path) -> Job:
        if platform.system() != "Windows":
            raise RuntimeError(f"Install Ollama with: {INSTALL_COMMANDS.get(platform.system(), 'see https://ollama.com/download')}")
        job = self._job("install", "ollama")
        if job.message == "":
            threading.Thread(target=self._install, args=(job, root, Path(download_dir)), daemon=True, name="ollama-install").start()
        return job

    def _install(self, job: Job, root: str, download_dir: Path) -> None:
        try:
            download_dir.mkdir(parents=True, exist_ok=True)
            setup = download_dir / "OllamaSetup.exe"
            job.message = "Downloading the Ollama installer from ollama.com"
            with httpx.stream("GET", INSTALLER_URL, follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as r:
                r.raise_for_status()
                if not str(r.url).startswith("https://"):
                    raise RuntimeError(f"the download was redirected to an insecure address: {r.url}")
                job.total = int(r.headers.get("content-length") or 0)
                with open(setup, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
                        job.completed += len(chunk)
            job.message = "Checking the installer's signature"
            signer = _authenticode_signer(setup)
            if "ollama" not in signer.lower():
                raise RuntimeError(f"the installer is not signed by Ollama ({signer or 'no valid signature'}); it was not run")
            job.message = "Installing Ollama for this user (no administrator rights needed)"
            subprocess.run([str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"], check=True, timeout=900, creationflags=subprocess.CREATE_NO_WINDOW)
            job.message = "Waiting for the Ollama server"
            if not self._wait_running(root, 45.0):
                self.start(root)
            job.message = "Ollama is installed and running"
            job.status = "done"
            try:
                setup.unlink()
            except OSError:
                pass
        except Exception as exc:  # noqa: BLE001 - reported to the page
            job.status, job.error = "failed", str(exc)[:500]
            log.warning("ollama install failed", error=str(exc)[:300])
        finally:
            job.ended = time.time()

    # ------------------------------------------------------------ models
    def pull(self, root: str, model: str) -> Job:
        if not MODEL_NAME.match(model or ""):
            raise ValueError("That is not a valid model name (for example qwen2.5vl:3b).")
        job = self._job("pull", model)
        if job.message == "":
            job.message = "Starting the download"
            threading.Thread(target=self._pull, args=(job, root, model), daemon=True, name=f"ollama-pull-{model}").start()
        return job

    @staticmethod
    def _pull(job: Job, root: str, model: str) -> None:
        import json

        layers: dict[str, tuple[int, int]] = {}
        try:
            with httpx.stream("POST", f"{root}/api/pull", json={"model": model, "stream": True}, timeout=httpx.Timeout(30.0, read=600.0)) as r:
                if r.status_code >= 400:
                    raise RuntimeError(f"Ollama answered HTTP {r.status_code}: {r.read().decode(errors='replace')[:200]}")
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        raise RuntimeError(msg["error"])
                    status = msg.get("status", "")
                    if msg.get("digest") and msg.get("total"):
                        layers[msg["digest"]] = (int(msg.get("completed") or 0), int(msg["total"]))
                        job.completed = sum(c for c, _ in layers.values())
                        job.total = sum(t for _, t in layers.values())
                    job.message = "Downloading" if status.startswith("pulling") and msg.get("digest") else status.capitalize()
                    if status == "success":
                        job.status, job.message = "done", "Downloaded"
            if job.status != "done":
                raise RuntimeError("the download ended without success")
        except httpx.ConnectError:
            job.status, job.error = "failed", "Ollama is not running. Start it first."
        except Exception as exc:  # noqa: BLE001
            job.status, job.error = "failed", str(exc)[:500]
        finally:
            job.ended = time.time()

    @staticmethod
    def delete(root: str, model: str) -> None:
        if not MODEL_NAME.match(model or ""):
            raise ValueError("invalid model name")
        r = httpx.request("DELETE", f"{root}/api/delete", json={"model": model}, timeout=30.0)
        if r.status_code >= 400:
            raise RuntimeError(f"Ollama answered HTTP {r.status_code}: {r.text[:200]}")

    @staticmethod
    def unload(root: str, model: str) -> None:
        """Free the GPU memory now (keep_alive 0)."""
        httpx.post(f"{root}/api/generate", json={"model": model, "keep_alive": 0}, timeout=30.0)


def _authenticode_signer(path: Path) -> str:
    """Subject of a valid Authenticode signature, or "" (Windows)."""
    script = f"$s = Get-AuthenticodeSignature -LiteralPath '{str(path).replace(chr(39), chr(39) * 2)}'; if ($s.Status -eq 'Valid') {{ $s.SignerCertificate.Subject }}"
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


_local: LocalModels | None = None


def get_local_models() -> LocalModels:
    global _local
    if _local is None:
        _local = LocalModels()
    return _local
