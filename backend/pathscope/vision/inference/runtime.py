"""Inference runtime discovery and selection.

Providers are probed lazily and defensively: a missing library simply marks
that runtime as unavailable. The selector maps a preset plus the hardware
probe to a concrete (provider, device) pair and records the fallback chain so
the UI can explain what was chosen and why.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from functools import lru_cache


@dataclass
class RuntimeInfo:
    id: str  # torch-cuda | torch-mps | torch-cpu | ort-tensorrt | ort-cuda | ort-cpu | openvino
    label: str
    available: bool
    provider: str  # detector provider family able to use it: ultralytics/torchvision/onnxruntime
    device: str  # cuda | mps | cpu
    version: str | None = None
    detail: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class RuntimeChoice:
    provider: str
    device: str
    runtime_id: str
    reason: str
    fallback_chain: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _try_import(name: str):
    try:
        return importlib.import_module(name)
    except Exception:  # noqa: BLE001 - any import failure means unavailable
        return None


@lru_cache(maxsize=1)
def probe_runtimes() -> list[RuntimeInfo]:
    out: list[RuntimeInfo] = []

    torch = _try_import("torch")
    if torch is not None:
        tv = getattr(torch, "__version__", None)
        cuda_ok = False
        cuda_detail = ""
        try:
            cuda_ok = bool(torch.cuda.is_available())
            if cuda_ok:
                cuda_detail = f"CUDA {torch.version.cuda}, {torch.cuda.get_device_name(0)}"
            elif getattr(torch.version, "cuda", None):
                cuda_detail = f"PyTorch built for CUDA {torch.version.cuda} but no usable GPU"
            else:
                cuda_detail = "CPU-only PyTorch build"
        except Exception as exc:  # noqa: BLE001
            cuda_detail = f"CUDA probe failed: {exc}"
        out.append(RuntimeInfo("torch-cuda", "PyTorch CUDA", cuda_ok, "ultralytics", "cuda", tv, cuda_detail))
        hip = getattr(torch.version, "hip", None)
        out.append(
            RuntimeInfo(
                "torch-rocm", "PyTorch ROCm", bool(hip) and cuda_ok, "ultralytics", "cuda", tv,
                f"ROCm {hip}" if hip else "not a ROCm build",
            )
        )
        mps_ok = False
        try:
            mps_ok = bool(torch.backends.mps.is_available())
        except Exception:  # noqa: BLE001
            mps_ok = False
        out.append(RuntimeInfo("torch-mps", "PyTorch Metal (MPS)", mps_ok, "ultralytics", "mps", tv))
        out.append(RuntimeInfo("torch-cpu", "PyTorch CPU", True, "ultralytics", "cpu", tv))
    else:
        for rid, label in (("torch-cuda", "PyTorch CUDA"), ("torch-mps", "PyTorch Metal (MPS)"), ("torch-cpu", "PyTorch CPU")):
            out.append(RuntimeInfo(rid, label, False, "ultralytics", "cpu", None, "PyTorch not installed"))

    ort = _try_import("onnxruntime")
    if ort is not None:
        try:
            providers = list(ort.get_available_providers())
        except Exception:  # noqa: BLE001
            providers = []
        ov = getattr(ort, "__version__", None)
        out.append(
            RuntimeInfo(
                "ort-tensorrt", "ONNX Runtime TensorRT", "TensorrtExecutionProvider" in providers,
                "onnxruntime", "cuda", ov, ", ".join(providers),
            )
        )
        out.append(
            RuntimeInfo(
                "ort-cuda", "ONNX Runtime CUDA", "CUDAExecutionProvider" in providers,
                "onnxruntime", "cuda", ov, ", ".join(providers),
            )
        )
        out.append(
            RuntimeInfo(
                "ort-coreml", "ONNX Runtime CoreML", "CoreMLExecutionProvider" in providers,
                "onnxruntime", "cpu", ov,
            )
        )
        out.append(RuntimeInfo("ort-cpu", "ONNX Runtime CPU", "CPUExecutionProvider" in providers, "onnxruntime", "cpu", ov))
    else:
        for rid, label in (("ort-tensorrt", "ONNX Runtime TensorRT"), ("ort-cuda", "ONNX Runtime CUDA"), ("ort-cpu", "ONNX Runtime CPU")):
            out.append(RuntimeInfo(rid, label, False, "onnxruntime", "cpu", None, "onnxruntime not installed"))

    trt = _try_import("tensorrt")
    out.append(
        RuntimeInfo(
            "tensorrt", "TensorRT (native engine export)", trt is not None, "ultralytics", "cuda",
            getattr(trt, "__version__", None) if trt else None,
            "" if trt else "tensorrt package not installed",
        )
    )
    ov = _try_import("openvino")
    out.append(
        RuntimeInfo(
            "openvino", "OpenVINO", ov is not None, "ultralytics", "cpu",
            getattr(ov, "__version__", None) if ov else None,
            "" if ov else "openvino package not installed",
        )
    )
    return out


def runtime_available(runtime_id: str) -> bool:
    return any(r.id == runtime_id and r.available for r in probe_runtimes())


def installed_providers() -> dict[str, bool]:
    return {
        "ultralytics": _try_import("ultralytics") is not None,
        "torchvision": _try_import("torchvision") is not None,
        "onnxruntime": _try_import("onnxruntime") is not None,
        # OpenCV DNN (face models of the recognition modules); always present with the core
        "opencv": _try_import("cv2") is not None,
    }


def resolve_device(requested: str = "auto") -> tuple[str, str]:
    """Return (device, reason) for PyTorch-based providers."""
    requested = (requested or "auto").lower()
    runtimes = {r.id: r for r in probe_runtimes()}
    if requested.startswith("cuda"):
        if runtimes.get("torch-cuda") and runtimes["torch-cuda"].available:
            return requested, "CUDA requested and available"
        return "cpu", "CUDA requested but not available; using CPU"
    if requested == "mps":
        if runtimes.get("torch-mps") and runtimes["torch-mps"].available:
            return "mps", "Apple MPS requested and available"
        return "cpu", "MPS requested but not available; using CPU"
    if requested == "cpu":
        return "cpu", "CPU requested"
    if runtimes.get("torch-cuda") and runtimes["torch-cuda"].available:
        return "cuda:0", "NVIDIA GPU with CUDA detected"
    if runtimes.get("torch-mps") and runtimes["torch-mps"].available:
        return "mps", "Apple GPU (MPS) detected"
    return "cpu", "No GPU acceleration available; using CPU"


def select_runtime(provider_pref: str, requested_device: str = "auto") -> RuntimeChoice:
    """Pick a concrete provider/device with a recorded fallback chain."""
    chain: list[str] = []
    providers = installed_providers()
    runtimes = {r.id: r for r in probe_runtimes()}
    pref = provider_pref or "auto"

    def torch_choice(provider: str) -> RuntimeChoice | None:
        if not providers.get(provider):
            chain.append(f"{provider}: package not installed")
            return None
        device, reason = resolve_device(requested_device)
        rid = "torch-cuda" if device.startswith("cuda") else ("torch-mps" if device == "mps" else "torch-cpu")
        return RuntimeChoice(provider, device, rid, reason, chain.copy())

    def ort_choice() -> RuntimeChoice | None:
        if not providers.get("onnxruntime"):
            chain.append("onnxruntime: package not installed")
            return None
        want_gpu = requested_device in ("auto",) or requested_device.startswith("cuda")
        if want_gpu and runtimes["ort-tensorrt"].available:
            return RuntimeChoice("onnxruntime", "cuda", "ort-tensorrt", "TensorRT execution provider available", chain.copy())
        if want_gpu and runtimes["ort-cuda"].available:
            return RuntimeChoice("onnxruntime", "cuda", "ort-cuda", "CUDA execution provider available", chain.copy())
        if want_gpu:
            chain.append("onnxruntime: no GPU execution provider, using CPU")
        return RuntimeChoice("onnxruntime", "cpu", "ort-cpu", "ONNX Runtime CPU", chain.copy())

    order: list[str]
    if pref == "auto":
        order = ["ultralytics", "torchvision", "onnxruntime"]
    else:
        order = [pref]
    for p in order:
        choice = torch_choice(p) if p in ("ultralytics", "torchvision") else ort_choice()
        if choice is not None:
            return choice
    raise RuntimeError("No inference provider is installed. Install ultralytics, torchvision or onnxruntime.")
