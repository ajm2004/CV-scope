"""Appearance encoders used by BoT-SORT.

An encoder turns the image inside each detection box into a short
L2-normalised vector. BoT-SORT compares a track's vector with the vectors of
nearby detections so the same anonymous id survives short occlusions and close
crossings.

Privacy: the vectors exist only in the tracker's memory while a track is alive.
They are never written to disk, never sent to the browser, never compared
across runs or cameras, and they are discarded when the track ends.

Three encoders are available:

* ``histogram``: HSV colour histograms of the upper and lower part of the box.
  No model and no download; runs on the CPU in well under a millisecond.
* ``cnn``: a general-purpose ImageNet CNN (torchvision ResNet-18, BSD-3-Clause
  code) used as a feature extractor. This is not a person re-identification
  model; it gives generic appearance features, which is enough for short-term
  association. GPU recommended.
* ``onnx:<file>``: a re-identification model supplied by the user as an ONNX
  file in ``<models>/reid/``. CV-Scope does not ship ReID weights because the
  public ones are trained on research-only datasets (Market-1501, MSMT17).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path

import cv2
import numpy as np

Box = tuple[float, float, float, float]

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

# torchvision backbones usable by the ``cnn`` encoder: name -> (builder, weights enum, feature dim)
CNN_BACKBONES = {
    "resnet18": ("resnet18", "ResNet18_Weights", 512),
}
# Checkpoint file-name prefixes written by torchvision into <TORCH_HOME>/hub/checkpoints
CNN_CHECKPOINT_PREFIX = {"resnet18": "resnet18-"}


class AppearanceError(RuntimeError):
    pass


def crop_box(frame: np.ndarray, box: Box, min_size: int = 4) -> np.ndarray | None:
    h, w = frame.shape[:2]
    x1 = int(max(0.0, min(w - 1.0, np.floor(box[0]))))
    y1 = int(max(0.0, min(h - 1.0, np.floor(box[1]))))
    x2 = int(max(0.0, min(float(w), np.ceil(box[2]))))
    y2 = int(max(0.0, min(float(h), np.ceil(box[3]))))
    if x2 - x1 < min_size or y2 - y1 < min_size:
        return None
    return frame[y1:y2, x1:x2]


def l2_normalize(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    if not np.isfinite(n) or n < 1e-12:
        return None
    return (v / n).astype(np.float32)


class AppearanceEncoder(ABC):
    id: str = "base"
    label: str = ""
    # Minimum appearance similarity (0..1) used when the user leaves the setting empty.
    default_min_similarity: float = 0.8

    @abstractmethod
    def encode(self, frame_bgr: np.ndarray, boxes: list[Box]) -> list[np.ndarray | None]:
        """One L2-normalised vector per box (``None`` when the box is unusable)."""

    def describe(self) -> dict:
        return {"id": self.id, "label": self.label, "default_min_similarity": self.default_min_similarity}

    def close(self) -> None:  # pragma: no cover - resource cleanup
        pass


class ColorHistogramEncoder(AppearanceEncoder):
    """Joint HSV histograms of the upper and lower part of the box.

    The box is trimmed horizontally to reduce background, split into two
    stripes (roughly upper and lower body for people), and each stripe gets an
    H x S x V histogram. Hue is binned softly and circularly: each pixel's hue
    is shared between the two nearest hue bins, so red (both 0 and 179) and
    colours near a bin edge are not split arbitrarily. Histograms are
    square-rooted (Hellinger) before the final L2 normalisation, so the cosine
    similarity behaves like the Bhattacharyya coefficient.
    """

    id = "histogram"
    label = "Colour histogram"
    # Calibrated on the two sample clips (730 same-object and 364 nearby
    # other-object comparisons): at 0.92 it keeps 83% of same-object
    # comparisons and accepted none of the nearby other objects.
    default_min_similarity = 0.92

    def __init__(self, bins: tuple[int, int, int] = (16, 3, 3), size: tuple[int, int] = (48, 96), soft_hue: bool = True) -> None:
        self.bins = bins
        self.size = size  # (width, height) the crop is resized to
        self.soft_hue = soft_hue
        self._stripes = ((0.10, 0.50), (0.50, 0.95))
        self._x_trim = (0.15, 0.85)

    def _hist(self, region: np.ndarray) -> np.ndarray | None:
        nh, ns, nv = self.bins
        px = region.reshape(-1, 3).astype(np.float32)
        if px.shape[0] == 0:
            return None
        s_bin = np.minimum((px[:, 1] * ns / 256.0).astype(np.int32), ns - 1)
        v_bin = np.minimum((px[:, 2] * nv / 256.0).astype(np.int32), nv - 1)
        sv = s_bin * nv + v_bin
        if self.soft_hue:
            pos = px[:, 0] * nh / 180.0 - 0.5  # bin centres at half-bin offsets
            lo = np.floor(pos)
            frac = pos - lo
            h0 = lo.astype(np.int32) % nh
            h1 = (h0 + 1) % nh
            size = nh * ns * nv
            hist = np.bincount(h0 * ns * nv + sv, weights=1.0 - frac, minlength=size)
            hist += np.bincount(h1 * ns * nv + sv, weights=frac, minlength=size)
        else:
            h_bin = np.minimum((px[:, 0] * nh / 180.0).astype(np.int32), nh - 1)
            hist = np.bincount(h_bin * ns * nv + sv, minlength=nh * ns * nv).astype(np.float64)
        total = float(hist.sum())
        if total <= 0:
            return None
        return np.sqrt(hist / total)

    def _one(self, crop: np.ndarray) -> np.ndarray | None:
        small = cv2.resize(crop, self.size, interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        w, h = self.size
        x1, x2 = int(w * self._x_trim[0]), int(w * self._x_trim[1])
        parts = []
        for y0, y1 in self._stripes:
            hist = self._hist(hsv[int(h * y0) : int(h * y1), x1:x2])
            if hist is None:
                return None
            parts.append(hist)
        return l2_normalize(np.concatenate(parts))

    def encode(self, frame_bgr: np.ndarray, boxes: list[Box]) -> list[np.ndarray | None]:
        out: list[np.ndarray | None] = []
        for b in boxes:
            c = crop_box(frame_bgr, b)
            out.append(self._one(c) if c is not None else None)
        return out

    def describe(self) -> dict:
        return {**super().describe(), "bins": list(self.bins), "soft_hue": self.soft_hue}


def torchvision_checkpoint_dir(models_dir: str | Path | None = None) -> Path:
    """Where torchvision weights live: ``<models>/torch/hub/checkpoints`` (same as the detectors)."""
    if models_dir:
        return Path(models_dir) / "torch" / "hub" / "checkpoints"
    home = os.environ.get("TORCH_HOME")
    return Path(home) / "hub" / "checkpoints" if home else Path.home() / ".cache" / "torch" / "hub" / "checkpoints"


def cnn_weights_installed(backbone: str = "resnet18", models_dir: str | Path | None = None) -> bool:
    ckpt = torchvision_checkpoint_dir(models_dir)
    prefix = CNN_CHECKPOINT_PREFIX.get(backbone, backbone)
    return ckpt.exists() and any(p.name.startswith(prefix) for p in ckpt.iterdir())


def cnn_available() -> tuple[bool, str]:
    try:
        import torch  # noqa: F401
        import torchvision  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "PyTorch and torchvision are not installed."
    return True, ""


class TorchvisionEncoder(AppearanceEncoder):
    """Generic ImageNet CNN features (global average pooled) of each box."""

    id = "cnn"
    label = "Deep features (ResNet-18)"
    # Calibrated on the sample clips: keeps 86% of same-object comparisons and
    # rejects 99.5% of comparisons with other nearby objects (256x128 input).
    default_min_similarity = 0.925

    def __init__(self, backbone: str = "resnet18", device: str = "cpu", input_size: tuple[int, int] = (256, 128), models_dir: str | Path | None = None) -> None:
        if backbone not in CNN_BACKBONES:
            raise AppearanceError(f"unknown CNN backbone '{backbone}'")
        ok, reason = cnn_available()
        if not ok:
            raise AppearanceError(reason)
        import torch
        from torchvision.models import get_model, get_model_weights

        builder, _weights_name, dim = CNN_BACKBONES[backbone]
        try:
            weights = get_model_weights(builder).DEFAULT
            net = get_model(builder, weights=None)
            ckpt = torchvision_checkpoint_dir(models_dir)
            ckpt.mkdir(parents=True, exist_ok=True)
            state = torch.hub.load_state_dict_from_url(weights.url, model_dir=str(ckpt), map_location="cpu", progress=False)
            net.load_state_dict(state)
        except Exception as exc:  # noqa: BLE001 - download or construction failure
            raise AppearanceError(f"could not load {builder} weights: {exc}") from exc
        body = torch.nn.Sequential(*list(net.children())[:-1])  # drop the classifier
        from pathscope.vision.inference.runtime import resolve_device

        self.device, _ = resolve_device(device)
        self.model = body.eval().to(self.device)
        self.backbone = backbone
        self.dim = dim
        self.input_size = input_size  # (height, width)
        self._torch = torch
        self._mean = torch.tensor(IMAGENET_MEAN, device=self.device).view(1, 3, 1, 1)
        self._std = torch.tensor(IMAGENET_STD, device=self.device).view(1, 3, 1, 1)

    def encode(self, frame_bgr: np.ndarray, boxes: list[Box]) -> list[np.ndarray | None]:
        out: list[np.ndarray | None] = [None] * len(boxes)
        crops = [crop_box(frame_bgr, b) for b in boxes]
        valid = [i for i, c in enumerate(crops) if c is not None]
        if not valid:
            return out
        h, w = self.input_size
        batch = np.stack([cv2.resize(crops[i], (w, h), interpolation=cv2.INTER_LINEAR) for i in valid])
        torch = self._torch
        t = torch.from_numpy(np.ascontiguousarray(batch[..., ::-1])).to(self.device)
        t = t.permute(0, 3, 1, 2).float().div_(255.0)
        t = (t - self._mean) / self._std
        with torch.inference_mode():
            f = self.model(t).flatten(1)
            f = torch.nn.functional.normalize(f, dim=1).float().cpu().numpy()
        for j, i in enumerate(valid):
            out[i] = f[j]
        return out

    def describe(self) -> dict:
        return {**super().describe(), "backbone": self.backbone, "device": self.device, "input_size": list(self.input_size)}


def reid_dir(models_dir: str | Path | None) -> Path | None:
    return Path(models_dir) / "reid" if models_dir else None


def list_onnx_reid_models(models_dir: str | Path | None) -> list[str]:
    d = reid_dir(models_dir)
    if d is None or not d.exists():
        return []
    return sorted(p.name for p in d.glob("*.onnx"))


class OnnxReidEncoder(AppearanceEncoder):
    """A re-identification model supplied as ONNX (NCHW RGB input, ImageNet normalisation)."""

    id = "onnx"
    # BoT-SORT reference value for dedicated ReID models (cosine distance / 2 <= 0.25).
    default_min_similarity = 0.75

    def __init__(self, path: str | Path, device: str = "cpu") -> None:
        try:
            import onnxruntime as ort
        except ImportError as exc:  # pragma: no cover - environment specific
            raise AppearanceError("onnxruntime is not installed.") from exc
        path = Path(path)
        if not path.exists():
            raise AppearanceError(f"ONNX re-identification model not found: {path}")
        available = ort.get_available_providers()
        providers = ["CPUExecutionProvider"]
        if str(device).startswith("cuda") and "CUDAExecutionProvider" in available:
            providers.insert(0, "CUDAExecutionProvider")
        try:
            self.session = ort.InferenceSession(str(path), providers=providers)
        except Exception as exc:  # noqa: BLE001
            raise AppearanceError(f"could not load ONNX model {path.name}: {exc}") from exc
        inp = self.session.get_inputs()[0]
        shape = list(inp.shape)
        if len(shape) != 4:
            raise AppearanceError(f"{path.name}: expected a 4-D image input, got shape {shape}")
        self.input_name = inp.name
        self.batch = shape[0] if isinstance(shape[0], int) and shape[0] > 0 else None
        self.h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 256
        self.w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 128
        self.path = path
        self.label = f"ONNX model {path.name}"
        self.execution_providers = list(self.session.get_providers())

    def _run(self, blob: np.ndarray) -> np.ndarray:
        out = self.session.run(None, {self.input_name: blob})[0]
        return np.asarray(out, dtype=np.float32).reshape(blob.shape[0], -1)

    def encode(self, frame_bgr: np.ndarray, boxes: list[Box]) -> list[np.ndarray | None]:
        out: list[np.ndarray | None] = [None] * len(boxes)
        crops = [crop_box(frame_bgr, b) for b in boxes]
        valid = [i for i, c in enumerate(crops) if c is not None]
        if not valid:
            return out
        imgs = np.stack([cv2.resize(crops[i], (self.w, self.h), interpolation=cv2.INTER_LINEAR) for i in valid])
        blob = (imgs[..., ::-1].astype(np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
        blob = np.ascontiguousarray(blob.transpose(0, 3, 1, 2))
        if self.batch is None:
            feats = self._run(blob)
        else:
            chunks = []
            for k in range(0, blob.shape[0], self.batch):
                part = blob[k : k + self.batch]
                n = part.shape[0]
                if n < self.batch:  # pad a fixed-batch model
                    part = np.concatenate([part, np.zeros((self.batch - n, *part.shape[1:]), dtype=np.float32)])
                chunks.append(self._run(part)[:n])
            feats = np.concatenate(chunks)
        for j, i in enumerate(valid):
            out[i] = l2_normalize(feats[j])
        return out

    def describe(self) -> dict:
        return {**super().describe(), "file": self.path.name, "input_size": [self.h, self.w], "execution_providers": self.execution_providers}


def create_encoder(spec: str | None, device: str = "cpu", models_dir: str | Path | None = None) -> AppearanceEncoder | None:
    """Build the encoder named by the BoT-SORT ``appearance`` setting."""
    spec = (spec or "none").strip()
    if spec in ("", "none", "off"):
        return None
    if spec == "histogram":
        return ColorHistogramEncoder()
    if spec in ("cnn", "cnn:resnet18"):
        return TorchvisionEncoder("resnet18", device=device, models_dir=models_dir)
    if spec.startswith("onnx:"):
        name = spec.split(":", 1)[1]
        d = reid_dir(models_dir)
        if d is None:
            raise AppearanceError("no models directory configured for ONNX re-identification models")
        if Path(name).name != name:
            raise AppearanceError("the ONNX model must be a file name inside the models/reid folder")
        return OnnxReidEncoder(d / name, device=device)
    raise AppearanceError(f"unknown appearance method '{spec}'")
