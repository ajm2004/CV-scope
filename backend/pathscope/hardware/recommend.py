"""Hardware-aware model and runtime recommendations.

The tiers are derived from the probe (GPU memory, CPU cores, RAM) and from the
catalog's approximate requirements. Every recommendation carries its reasons
and is flagged ``estimated`` until a local benchmark exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pathscope.hardware.probe import HardwareReport
from pathscope.models.catalog import CATALOG_BY_ID, ModelSpec
from pathscope.vision.inference.runtime import installed_providers, probe_runtimes

GB = 1024**3


@dataclass
class ModelRecommendation:
    tier: str  # fast | balanced | accurate | cpu
    title: str
    model_id: str
    model_name: str
    provider: str
    device: str
    image_size: int
    reasons: list[str]
    estimated: bool = True
    installed: bool = False
    available: bool = True  # False when the provider package is missing
    unavailable_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationSet:
    workload_class: str
    workload_summary: str
    default_tier: str
    runtime_id: str
    runtime_label: str
    runtime_reason: str
    fallback_chain: list[str]
    tiers: list[ModelRecommendation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    benchmarked: bool = False
    # Effect of the licensed recognition modules on camera capacity (None when none is active)
    recognition: dict | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# Cost of the recognition modules per processed frame, in the same units as
# the detectors (yolo11n at 640 px = 1). They include the per-track attempt
# budget of the default settings (a few face or plate attempts per second).
RECOGNITION_UNITS: dict[str, dict[str, float]] = {
    "face": {"opencv": 0.9, "insightface": 3.0, "stub": 0.0},
    "plate": {"onnx": 1.0, "stub": 0.0},
}
# Components of each module, for the recommendation text
RECOGNITION_COMPONENTS: dict[str, list[str]] = {
    "face": ["Person detector", "Tracker", "Face detector", "Face quality", "Face embedding model", "Matcher"],
    "plate": ["Vehicle detector", "Tracker", "Plate detector", "Plate OCR", "Temporal consensus"],
}


def recognition_units(module: str, stack: str | None) -> float:
    table = RECOGNITION_UNITS.get(module, {})
    return table.get(stack or "", max(table.values()) if table else 0.0)


def _capacities(hw: HardwareReport) -> tuple[float, float, bool]:
    gpu = hw.best_gpu
    cuda = hw.acceleration.cuda_available
    if cuda and gpu and (gpu.vram_total_bytes or 0) >= 10 * GB:
        gpu_capacity = 900.0
    elif cuda and gpu and (gpu.vram_total_bytes or 0) >= 6 * GB:
        gpu_capacity = 500.0
    elif cuda:
        gpu_capacity = 250.0
    else:
        gpu_capacity = 0.0
    cores = hw.cpu.physical_cores or hw.cpu.logical_cores or 2
    return gpu_capacity, 6.0 * cores, cuda


def recognition_impact(hw: HardwareReport, modules: dict[str, dict], detector_model_id: str | None = None, processing_fps: float = 10.0) -> dict | None:
    """How enabling recognition changes the estimated number of camera streams.

    ``modules``: {"face": {"active": bool, "stack": "opencv"}, "plate": {"active": bool, "stack": "onnx"}}.
    Face recognition with the OpenCV stack always runs on the CPU; the ONNX
    stacks use the GPU when ONNX Runtime has a CUDA provider."""
    active = {m: cfg for m, cfg in modules.items() if cfg.get("active")}
    if not active:
        return None
    gpu_capacity, cpu_capacity, cuda = _capacities(hw)
    runtimes = {r.id: r for r in probe_runtimes()}
    ort_gpu = runtimes.get("ort-cuda") is not None and runtimes["ort-cuda"].available
    spec = CATALOG_BY_ID.get(detector_model_id or "")
    det_units = _COST_UNITS.get(spec.compute_class if spec else "medium", 2.2)
    det_gpu = det_units if cuda else 0.0
    det_cpu = det_units if not cuda else 0.25 * det_units  # pre/post-processing share
    rec_gpu = rec_cpu = 0.0
    components: list[str] = []
    per_module: dict[str, dict] = {}
    for module, cfg in active.items():
        stack = cfg.get("stack") or ("opencv" if module == "face" else "onnx")
        units = recognition_units(module, stack)
        on_gpu = (module == "face" and stack == "insightface" and ort_gpu) or (module == "plate" and stack == "onnx" and ort_gpu)
        if on_gpu:
            rec_gpu += units
            rec_cpu += 0.2 * units
        else:
            rec_cpu += units
        components.extend(c for c in RECOGNITION_COMPONENTS.get(module, []) if c not in components)
        per_module[module] = {"stack": stack, "units_per_frame": units, "device": "gpu" if on_gpu else "cpu"}

    def cams(gpu_per: float, cpu_per: float) -> float:
        per_cam_gpu = gpu_per * processing_fps
        per_cam_cpu = cpu_per * processing_fps
        limits = []
        if per_cam_gpu > 0:
            limits.append(gpu_capacity / per_cam_gpu if gpu_capacity else 0.0)
        if per_cam_cpu > 0:
            limits.append(cpu_capacity / per_cam_cpu)
        return min(limits) if limits else 0.0

    without = cams(det_gpu, det_cpu)
    with_rec = cams(det_gpu + rec_gpu, det_cpu + rec_cpu)
    reduction = (1.0 - with_rec / without) * 100.0 if without > 0 else 0.0
    names = " and ".join("face recognition" if m == "face" else "plate recognition" for m in active)
    warning = None
    if with_rec < 1.0:
        warning = f"Enabling {names} leaves less than one real-time stream at {processing_fps:g} processed frames per second on this machine; lower the processing FPS or use a smaller detector."
    elif reduction >= 30.0:
        warning = f"Enabling {names} reduces the estimated camera capacity from about {int(without)} to {int(with_rec)} streams at {processing_fps:g} processed frames per second ({reduction:.0f}% less)."
    return {
        "modules": per_module,
        "components": components,
        "detector_model_id": spec.id if spec else None,
        "processing_fps": processing_fps,
        "camera_capacity_without": round(without, 1),
        "camera_capacity_with": round(with_rec, 1),
        "reduction_percent": round(max(0.0, reduction), 1),
        "warning": warning,
        "basis": "estimate",
        "note": "Rough estimate from the hardware class; run the recognition benchmark on the Models page for measured timings.",
    }


def _pick(model_ids: list[str], providers: dict[str, bool]) -> ModelSpec:
    """First catalog entry whose provider package is installed, else the first."""
    for mid in model_ids:
        spec = CATALOG_BY_ID[mid]
        if providers.get(spec.provider):
            return spec
    return CATALOG_BY_ID[model_ids[0]]


def build_recommendations(
    hw: HardwareReport, installed_model_ids: set[str] | None = None, benchmarked: bool = False, recognition: dict[str, dict] | None = None
) -> RecommendationSet:
    installed_model_ids = installed_model_ids or set()
    providers = installed_providers()
    runtimes = {r.id: r for r in probe_runtimes()}
    gpu = hw.best_gpu
    vram_gb = (gpu.vram_total_bytes or 0) / GB if gpu else 0.0
    cores = hw.cpu.physical_cores or hw.cpu.logical_cores or 2
    ram_gb = hw.memory.total_bytes / GB
    warnings: list[str] = []

    cuda = hw.acceleration.cuda_available
    mps = hw.acceleration.mps_available
    torch_ok = any(r.id.startswith("torch-") and r.available for r in runtimes.values())

    # ---- runtime selection
    fallback: list[str] = []
    if cuda and providers.get("ultralytics"):
        runtime_id, runtime_label = "torch-cuda", "PyTorch CUDA"
        runtime_reason = f"NVIDIA GPU with CUDA detected ({gpu.name if gpu else 'GPU'})."
        if runtimes["ort-tensorrt"].available:
            fallback = ["ort-tensorrt (available for exported ONNX models)", "torch-cpu"]
        else:
            fallback = ["ort-cuda" if runtimes["ort-cuda"].available else "ort-cpu", "torch-cpu"]
        device = "cuda:0"
    elif cuda and providers.get("torchvision"):
        runtime_id, runtime_label = "torch-cuda", "PyTorch CUDA"
        runtime_reason = "CUDA available; Ultralytics is not installed so torchvision detectors are used."
        fallback = ["torch-cpu"]
        device = "cuda:0"
    elif mps and torch_ok:
        runtime_id, runtime_label = "torch-mps", "PyTorch Metal (MPS)"
        runtime_reason = "Apple GPU detected."
        fallback = ["torch-cpu"]
        device = "mps"
    elif runtimes["ort-cuda"].available:
        runtime_id, runtime_label = "ort-cuda", "ONNX Runtime CUDA"
        runtime_reason = "ONNX Runtime CUDA execution provider is available."
        fallback = ["ort-cpu"]
        device = "cuda"
    elif torch_ok:
        runtime_id, runtime_label = "torch-cpu", "PyTorch CPU"
        runtime_reason = "No GPU acceleration detected; running on the CPU."
        fallback = ["ort-cpu"] if runtimes["ort-cpu"].available else []
        device = "cpu"
    elif runtimes["ort-cpu"].available:
        runtime_id, runtime_label = "ort-cpu", "ONNX Runtime CPU"
        runtime_reason = "PyTorch is not installed; ONNX Runtime on the CPU is available."
        fallback = []
        device = "cpu"
    else:
        runtime_id, runtime_label = "none", "No inference runtime"
        runtime_reason = "Neither PyTorch nor ONNX Runtime is installed."
        fallback = []
        device = "cpu"
        warnings.append("Install PyTorch (with torchvision or ultralytics) or onnxruntime to run detection.")

    if cuda and not providers.get("ultralytics") and not providers.get("torchvision"):
        warnings.append("CUDA is available but no PyTorch detector provider is installed.")
    if gpu and gpu.vendor == "nvidia" and not cuda and torch_ok:
        warnings.append(
            "An NVIDIA GPU is present but the installed PyTorch build cannot use CUDA. "
            "Install a CUDA build of PyTorch to enable GPU inference."
        )
    if ram_gb < 8:
        warnings.append("Less than 8 GB of RAM: keep to nano/small models and one camera.")

    # ---- workload class
    if cuda and vram_gb >= 10:
        workload = "gpu-high"
        summary = "Real-time 1080p person/vehicle detection on several streams, or large models on recorded footage."
    elif cuda and vram_gb >= 6:
        workload = "gpu-medium"
        summary = "Real-time 1080p detection on one or two streams with medium models."
    elif cuda or mps:
        workload = "gpu-low"
        summary = "Real-time detection at reduced resolution with small models."
    elif cores >= 8:
        workload = "cpu-strong"
        summary = "CPU inference with nano/small models at reduced frame rates."
    else:
        workload = "cpu-basic"
        summary = "CPU inference with the nano model, low processing FPS and reduced resolution."

    # ---- tiers
    def rec(tier: str, title: str, ids: list[str], size: int, reasons: list[str], dev: str) -> ModelRecommendation:
        spec = _pick(ids, providers)
        available = bool(providers.get(spec.provider))
        return ModelRecommendation(
            tier=tier,
            title=title,
            model_id=spec.id,
            model_name=spec.name,
            provider=spec.provider,
            device=dev,
            image_size=size,
            reasons=reasons,
            installed=spec.id in installed_model_ids,
            available=available,
            unavailable_reason="" if available else f"Install the '{spec.requires_package}' package to use this model.",
        )

    tiers: list[ModelRecommendation] = []
    gpu_desc = f"{gpu.name} with {vram_gb:.0f} GB VRAM" if gpu and vram_gb else "GPU"
    if workload == "gpu-high":
        tiers = [
            rec("balanced", "Balanced", ["yolo11m", "tv-fasterrcnn-mobilenet"], 640,
                [f"{gpu_desc} detected.", "Suitable for real-time 1080p person/vehicle detection."], device),
            rec("fast", "Fast", ["yolo11s", "tv-ssdlite320"], 640,
                ["Recommended for multiple simultaneous camera streams."], device),
            rec("accurate", "High accuracy", ["yolo11l", "tv-fasterrcnn-r50v2"], 832,
                ["Suitable for recorded footage or lower FPS.", "Highest quality on small/distant objects."], device),
            rec("cpu", "CPU mode", ["yolo11n", "tv-ssdlite320"], 640,
                ["Fallback when the GPU is unavailable or reserved."], "cpu"),
        ]
        default_tier = "balanced"
    elif workload == "gpu-medium":
        tiers = [
            rec("balanced", "Balanced", ["yolo11s", "tv-fasterrcnn-mobilenet"], 640,
                [f"{gpu_desc} detected.", "Real-time 1080p on one or two streams."], device),
            rec("fast", "Fast", ["yolo11n", "tv-ssdlite320"], 640,
                ["Recommended for several streams or high frame rates."], device),
            rec("accurate", "High accuracy", ["yolo11m", "tv-fasterrcnn-r50v2"], 640,
                ["Suitable for recorded footage or lower FPS."], device),
            rec("cpu", "CPU mode", ["yolo11n", "tv-ssdlite320"], 640,
                ["Fallback when the GPU is unavailable."], "cpu"),
        ]
        default_tier = "balanced"
    elif workload == "gpu-low":
        tiers = [
            rec("balanced", "Balanced", ["yolo11n", "tv-ssdlite320"], 640,
                [f"{gpu_desc} detected with limited memory." if gpu else "GPU with limited memory.", "Nano model keeps VRAM use low."], device),
            rec("fast", "Fast", ["yolo11n", "tv-ssdlite320"], 480,
                ["Reduced inference resolution for higher frame rates."], device),
            rec("accurate", "High accuracy", ["yolo11s", "tv-fasterrcnn-mobilenet"], 640,
                ["Use for recorded footage; may not reach real time."], device),
            rec("cpu", "CPU mode", ["yolo11n", "tv-ssdlite320"], 640, ["Fallback without the GPU."], "cpu"),
        ]
        default_tier = "balanced"
    else:
        strong = workload == "cpu-strong"
        tiers = [
            rec("cpu", "CPU mode", ["yolo11n", "tv-ssdlite320", "yolo11n-onnx"], 640,
                [f"No GPU acceleration; {cores} CPU cores available.", "Nano model recommended; expect a few frames per second at 640 px."], "cpu"),
            rec("fast", "Fast", ["yolo11n", "tv-ssdlite320", "yolo11n-onnx"], 416,
                ["Reduced resolution for higher frame rates on the CPU."], "cpu"),
            rec("balanced", "Balanced", ["yolo11s" if strong else "yolo11n", "tv-ssdlite320"], 640,
                ["Small model is workable on a strong CPU at low FPS." if strong else "Nano model at full resolution."], "cpu"),
            rec("accurate", "High accuracy", ["yolo11s", "tv-fasterrcnn-mobilenet"], 640,
                ["Use only for offline processing of recorded footage on the CPU."], "cpu"),
        ]
        default_tier = "cpu"

    impact = None
    if recognition:
        default_model = next((t.model_id for t in tiers if t.tier == default_tier), tiers[0].model_id if tiers else None)
        impact = recognition_impact(hw, recognition, default_model)
        if impact and impact.get("warning"):
            warnings.append(impact["warning"])
    return RecommendationSet(
        workload_class=workload,
        workload_summary=summary,
        default_tier=default_tier,
        runtime_id=runtime_id,
        runtime_label=runtime_label,
        runtime_reason=runtime_reason,
        fallback_chain=fallback,
        tiers=tiers,
        warnings=warnings,
        benchmarked=benchmarked,
        recognition=impact,
    )


# Very rough compute cost units per (model, 640px) frame relative to yolo11n on the same device
_COST_UNITS = {
    "low": 1.0,
    "medium": 2.2,
    "high": 4.5,
    "very-high": 9.0,
}


def estimate_load(
    hw: HardwareReport,
    streams: list[dict],
    benchmarks: dict[str, float] | None = None,
) -> dict:
    """Estimate relative GPU/CPU load for a set of configured streams.

    ``streams`` items: {model_id, image_size, processing_fps, device,
    recognition: {"face": "opencv", "plate": "onnx"} (optional, licensed modules)}.
    ``benchmarks``: optional measured ms-per-frame keyed by "model_id@device@size".
    Returns an estimate with a clear label of its basis.
    """
    gpu_capacity, cpu_capacity, _cuda = _capacities(hw)
    runtimes = {r.id: r for r in probe_runtimes()}
    ort_gpu = runtimes.get("ort-cuda") is not None and runtimes["ort-cuda"].available

    gpu_load = 0.0
    cpu_load = 0.0
    basis = "estimate"
    for s in streams:
        spec = CATALOG_BY_ID.get(s.get("model_id", ""))
        units = _COST_UNITS.get(spec.compute_class if spec else "low", 1.0)
        size = float(s.get("image_size") or 640)
        units *= (size / 640.0) ** 2
        fps = float(s.get("processing_fps") or 10.0)
        # licensed recognition modules add their own cost on top of the detector
        for module, stack in (s.get("recognition") or {}).items():
            rec = recognition_units(module, stack)
            on_gpu = ort_gpu and ((module == "face" and stack == "insightface") or (module == "plate" and stack != "stub"))
            if on_gpu and gpu_capacity:
                gpu_load += rec * fps / gpu_capacity * 100.0
            else:
                cpu_load += rec * fps / cpu_capacity * 100.0
        key = f"{s.get('model_id')}@{s.get('device')}@{int(size)}"
        if benchmarks and key in benchmarks:
            basis = "benchmark"
            ms = benchmarks[key]
            share = fps * ms / 1000.0  # fraction of one second of compute per second
            if str(s.get("device", "cpu")).startswith("cuda"):
                gpu_load += share * 100.0
            else:
                cpu_load += share * 100.0
            continue
        if str(s.get("device", "cpu")).startswith("cuda") and gpu_capacity:
            gpu_load += units * fps / gpu_capacity * 100.0
        else:
            cpu_load += units * fps / cpu_capacity * 100.0

    suggestions: list[str] = []
    if gpu_load > 80 or cpu_load > 80:
        suggestions = [
            "Reduce processing FPS",
            "Use a smaller detector",
            "Lower the inference resolution",
        ]
        if len(hw.gpus) > 1:
            suggestions.append("Use a secondary GPU")
    return {
        "basis": basis,
        "gpu_percent": round(min(gpu_load, 999.0), 1),
        "cpu_percent": round(min(cpu_load, 999.0), 1),
        "warning": (
            "Current configuration exceeds the estimated compute available."
            if gpu_load > 100 or cpu_load > 100
            else ("Adding another stream may exceed available compute." if gpu_load > 80 or cpu_load > 80 else None)
        ),
        "suggestions": suggestions,
    }
