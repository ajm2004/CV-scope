"""Hardware discovery.

Every probe is defensive: a missing library or an unsupported platform yields
``None``/empty values instead of an exception, so the Hardware page always
renders something truthful.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

from pathscope.vision.inference.runtime import installed_providers, probe_runtimes


@dataclass
class CpuInfo:
    model: str
    architecture: str
    physical_cores: int | None
    logical_cores: int | None
    max_frequency_mhz: float | None
    current_usage_percent: float | None
    flags: list[str] = field(default_factory=list)


@dataclass
class MemoryInfo:
    total_bytes: int
    available_bytes: int
    used_percent: float


@dataclass
class DiskInfo:
    path: str
    total_bytes: int
    free_bytes: int


@dataclass
class GpuInfo:
    index: int
    name: str
    vendor: str  # nvidia | amd | intel | apple | unknown
    vram_total_bytes: int | None
    vram_used_bytes: int | None
    driver_version: str | None
    cuda_driver_version: str | None
    compute_capability: str | None
    utilization_percent: float | None
    integrated: bool
    source: str  # nvml | torch | wmi | lspci | system_profiler


@dataclass
class AccelerationInfo:
    cuda_available: bool
    cuda_version: str | None
    cudnn_version: str | None
    rocm_available: bool
    rocm_version: str | None
    mps_available: bool
    tensorrt_available: bool
    openvino_available: bool
    onnxruntime_providers: list[str]


@dataclass
class HardwareReport:
    probed_at: float
    os: str
    os_version: str
    python_version: str
    hostname: str
    cpu: CpuInfo
    memory: MemoryInfo
    disk: DiskInfo
    gpus: list[GpuInfo]
    acceleration: AccelerationInfo
    runtimes: list[dict]
    providers: dict[str, bool]
    library_versions: dict[str, str | None]

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def best_gpu(self) -> GpuInfo | None:
        discrete = [g for g in self.gpus if not g.integrated and g.vram_total_bytes]
        if discrete:
            return max(discrete, key=lambda g: g.vram_total_bytes or 0)
        return self.gpus[0] if self.gpus else None


# ----------------------------------------------------------------------------
def _probe_cpu() -> CpuInfo:
    model = platform.processor() or ""
    flags: list[str] = []
    freq = None
    try:
        import cpuinfo  # py-cpuinfo

        info = cpuinfo.get_cpu_info()
        model = info.get("brand_raw") or model
        flags = [f for f in info.get("flags", []) if f in ("avx", "avx2", "avx512f", "fma", "sse4_2", "neon")]
    except Exception:  # noqa: BLE001
        pass
    try:
        f = psutil.cpu_freq()
        freq = float(f.max) if f and f.max else (float(f.current) if f else None)
    except Exception:  # noqa: BLE001
        freq = None
    try:
        usage = psutil.cpu_percent(interval=0.2)
    except Exception:  # noqa: BLE001
        usage = None
    return CpuInfo(
        model=model.strip() or "Unknown CPU",
        architecture=platform.machine(),
        physical_cores=psutil.cpu_count(logical=False),
        logical_cores=psutil.cpu_count(logical=True),
        max_frequency_mhz=freq,
        current_usage_percent=usage,
        flags=flags,
    )


def _probe_memory() -> MemoryInfo:
    vm = psutil.virtual_memory()
    return MemoryInfo(total_bytes=int(vm.total), available_bytes=int(vm.available), used_percent=float(vm.percent))


def _probe_disk(path: Path) -> DiskInfo:
    try:
        usage = shutil.disk_usage(path)
        return DiskInfo(path=str(path), total_bytes=int(usage.total), free_bytes=int(usage.free))
    except Exception:  # noqa: BLE001
        return DiskInfo(path=str(path), total_bytes=0, free_bytes=0)


def _probe_nvidia() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    try:
        import pynvml

        pynvml.nvmlInit()
    except Exception:  # noqa: BLE001
        return gpus
    try:
        driver = pynvml.nvmlSystemGetDriverVersion()
        driver = driver.decode() if isinstance(driver, bytes) else str(driver)
        try:
            cuda_drv = pynvml.nvmlSystemGetCudaDriverVersion_v2()
            cuda_drv_s = f"{cuda_drv // 1000}.{(cuda_drv % 1000) // 10}"
        except Exception:  # noqa: BLE001
            cuda_drv_s = None
        count = pynvml.nvmlDeviceGetCount()
        for i in range(count):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            name = name.decode() if isinstance(name, bytes) else str(name)
            mem = pynvml.nvmlDeviceGetMemoryInfo(h)
            try:
                util = float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
            except Exception:  # noqa: BLE001
                util = None
            try:
                major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(h)
                cc = f"{major}.{minor}"
            except Exception:  # noqa: BLE001
                cc = None
            gpus.append(
                GpuInfo(
                    index=i,
                    name=name,
                    vendor="nvidia",
                    vram_total_bytes=int(mem.total),
                    vram_used_bytes=int(mem.used),
                    driver_version=driver,
                    cuda_driver_version=cuda_drv_s,
                    compute_capability=cc,
                    utilization_percent=util,
                    integrated=False,
                    source="nvml",
                )
            )
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            pynvml.nvmlShutdown()
        except Exception:  # noqa: BLE001
            pass
    return gpus


def _probe_torch_gpus() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    try:
        import torch

        if torch.cuda.is_available():
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                vendor = "amd" if getattr(torch.version, "hip", None) else "nvidia"
                gpus.append(
                    GpuInfo(
                        index=i,
                        name=props.name,
                        vendor=vendor,
                        vram_total_bytes=int(props.total_memory),
                        vram_used_bytes=None,
                        driver_version=None,
                        cuda_driver_version=None,
                        compute_capability=f"{props.major}.{props.minor}",
                        utilization_percent=None,
                        integrated=False,
                        source="torch",
                    )
                )
    except Exception:  # noqa: BLE001
        pass
    return gpus


def _vendor_from_name(name: str) -> str:
    n = name.lower()
    if "nvidia" in n or "geforce" in n or "quadro" in n or "rtx" in n or "tesla" in n:
        return "nvidia"
    if "amd" in n or "radeon" in n:
        return "amd"
    if "intel" in n or "iris" in n or "uhd" in n or "arc" in n:
        return "intel"
    if "apple" in n:
        return "apple"
    return "unknown"


def _is_integrated(name: str, vendor: str) -> bool:
    n = name.lower()
    if vendor == "intel" and "arc" not in n:
        return True
    if vendor == "amd" and any(k in n for k in ("vega", "graphics", "radeon(tm)")) and "rx" not in n:
        return True
    if vendor == "apple":
        return True
    return False


def _probe_os_adapters() -> list[GpuInfo]:
    """Adapters the OS knows about (covers integrated GPUs and non-NVIDIA cards)."""
    gpus: list[GpuInfo] = []
    system = platform.system()
    try:
        if system == "Windows":
            cmd = [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM,DriverVersion | ConvertTo-Json",
            ]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=15).stdout.strip()
            if out:
                import json

                data = json.loads(out)
                if isinstance(data, dict):
                    data = [data]
                for i, item in enumerate(data):
                    name = str(item.get("Name") or "Unknown adapter")
                    vendor = _vendor_from_name(name)
                    ram = item.get("AdapterRAM")
                    gpus.append(
                        GpuInfo(
                            index=i, name=name, vendor=vendor,
                            vram_total_bytes=int(ram) if ram and int(ram) > 0 else None,
                            vram_used_bytes=None, driver_version=item.get("DriverVersion"),
                            cuda_driver_version=None, compute_capability=None,
                            utilization_percent=None, integrated=_is_integrated(name, vendor), source="wmi",
                        )
                    )
        elif system == "Linux" and shutil.which("lspci"):
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout
            i = 0
            for line in out.splitlines():
                if "VGA" in line or "3D controller" in line or "Display controller" in line:
                    name = line.split(":", 2)[-1].strip()
                    vendor = _vendor_from_name(name)
                    gpus.append(
                        GpuInfo(
                            index=i, name=name, vendor=vendor, vram_total_bytes=None, vram_used_bytes=None,
                            driver_version=None, cuda_driver_version=None, compute_capability=None,
                            utilization_percent=None, integrated=_is_integrated(name, vendor), source="lspci",
                        )
                    )
                    i += 1
        elif system == "Darwin":
            out = subprocess.run(
                ["system_profiler", "SPDisplaysDataType"], capture_output=True, text=True, timeout=15
            ).stdout
            i = 0
            for line in out.splitlines():
                s = line.strip()
                if s.startswith("Chipset Model:"):
                    name = s.split(":", 1)[1].strip()
                    gpus.append(
                        GpuInfo(
                            index=i, name=name, vendor=_vendor_from_name(name), vram_total_bytes=None,
                            vram_used_bytes=None, driver_version=None, cuda_driver_version=None,
                            compute_capability=None, utilization_percent=None,
                            integrated="apple" in name.lower(), source="system_profiler",
                        )
                    )
                    i += 1
    except Exception:  # noqa: BLE001
        pass
    return gpus


def _merge_gpus(primary: list[GpuInfo], *others: list[GpuInfo]) -> list[GpuInfo]:
    result = list(primary)
    seen = {g.name.lower() for g in result}
    for group in others:
        for g in group:
            key = g.name.lower()
            if any(key in s or s in key for s in seen):
                continue
            seen.add(key)
            g.index = len(result)
            result.append(g)
    return result


def _probe_acceleration() -> AccelerationInfo:
    cuda_available = False
    cuda_version = None
    cudnn_version = None
    rocm_available = False
    rocm_version = None
    mps_available = False
    try:
        import torch

        cuda_available = bool(torch.cuda.is_available())
        cuda_version = getattr(torch.version, "cuda", None)
        rocm_version = getattr(torch.version, "hip", None)
        rocm_available = bool(rocm_version) and cuda_available
        if cuda_available and torch.backends.cudnn.is_available():
            v = torch.backends.cudnn.version()
            cudnn_version = str(v) if v else None
        try:
            mps_available = bool(torch.backends.mps.is_available())
        except Exception:  # noqa: BLE001
            mps_available = False
    except Exception:  # noqa: BLE001
        pass
    runtimes = {r.id: r for r in probe_runtimes()}
    ort_providers: list[str] = []
    try:
        import onnxruntime as ort

        ort_providers = list(ort.get_available_providers())
    except Exception:  # noqa: BLE001
        pass
    return AccelerationInfo(
        cuda_available=cuda_available,
        cuda_version=cuda_version,
        cudnn_version=cudnn_version,
        rocm_available=rocm_available,
        rocm_version=rocm_version,
        mps_available=mps_available,
        tensorrt_available=runtimes["tensorrt"].available or runtimes["ort-tensorrt"].available,
        openvino_available=runtimes["openvino"].available,
        onnxruntime_providers=ort_providers,
    )


def _library_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ("torch", "torchvision", "ultralytics", "onnxruntime", "cv2", "numpy", "tensorrt", "openvino"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", None)
        except Exception:  # noqa: BLE001
            out[name] = None
    return out


def _os_name() -> str:
    system, release = platform.system(), platform.release()
    if system == "Windows":
        # platform.release() reports "10" for Windows 11; the build number tells them apart
        try:
            build = int(platform.version().split(".")[2])
            if build >= 22000:
                release = "11"
        except (IndexError, ValueError):
            pass
    return f"{system} {release}"


def probe_hardware(data_dir: Path | None = None) -> HardwareReport:
    data_dir = data_dir or Path(os.getcwd())
    nvml = _probe_nvidia()
    torch_gpus = _probe_torch_gpus()
    os_gpus = _probe_os_adapters()
    gpus = _merge_gpus(nvml, torch_gpus, os_gpus)
    # Fill compute capability from torch when NVML lacked it
    for g in gpus:
        if g.compute_capability is None:
            for t in torch_gpus:
                if t.name.lower() in g.name.lower() or g.name.lower() in t.name.lower():
                    g.compute_capability = t.compute_capability
    return HardwareReport(
        probed_at=time.time(),
        os=_os_name(),
        os_version=platform.version(),
        python_version=sys.version.split()[0],
        hostname=platform.node(),
        cpu=_probe_cpu(),
        memory=_probe_memory(),
        disk=_probe_disk(data_dir),
        gpus=gpus,
        acceleration=_probe_acceleration(),
        runtimes=[r.to_dict() for r in probe_runtimes()],
        providers=installed_providers(),
        library_versions=_library_versions(),
    )


def live_utilization() -> dict:
    """Cheap, frequently polled load numbers for the performance monitor."""
    out: dict = {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": psutil.virtual_memory().percent,
        "gpus": [],
    }
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            for i in range(pynvml.nvmlDeviceGetCount()):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                mem = pynvml.nvmlDeviceGetMemoryInfo(h)
                util = pynvml.nvmlDeviceGetUtilizationRates(h)
                out["gpus"].append(
                    {
                        "index": i,
                        "utilization_percent": float(util.gpu),
                        "vram_used_bytes": int(mem.used),
                        "vram_total_bytes": int(mem.total),
                    }
                )
        finally:
            pynvml.nvmlShutdown()
    except Exception:  # noqa: BLE001
        pass
    return out
