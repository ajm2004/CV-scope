"""ONNX Runtime session creation shared by the recognition stacks."""

from __future__ import annotations

from pathlib import Path


class OnnxUnavailable(RuntimeError):
    pass


def create_session(model_path: str | Path, device: str = "auto"):
    """Return (session, resolved_device). CUDA / TensorRT execution providers
    are used when requested (or ``auto``) and available; otherwise the CPU."""
    try:
        import onnxruntime as ort
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise OnnxUnavailable("The 'onnxruntime' package is not installed. Install the onnx-cpu or onnx-gpu extra.") from exc
    available = ort.get_available_providers()
    dev = (device or "auto").lower()
    wanted: list = []
    if dev.startswith("cuda") or dev == "auto":
        if "TensorrtExecutionProvider" in available:
            wanted.append(("TensorrtExecutionProvider", {"trt_fp16_enable": True}))
        if "CUDAExecutionProvider" in available:
            wanted.append("CUDAExecutionProvider")
    if dev in ("auto", "mps") and "CoreMLExecutionProvider" in available:
        wanted.append("CoreMLExecutionProvider")
    wanted.append("CPUExecutionProvider")
    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    so.log_severity_level = 3
    try:
        session = ort.InferenceSession(str(model_path), so, providers=wanted)
    except Exception as exc:  # noqa: BLE001
        raise OnnxUnavailable(f"Could not load ONNX model '{model_path}': {exc}") from exc
    used = list(session.get_providers())
    resolved = "cuda" if any("CUDA" in p or "Tensorrt" in p for p in used) else "cpu"
    return session, resolved
