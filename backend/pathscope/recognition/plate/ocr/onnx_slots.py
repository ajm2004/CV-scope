"""Slot-classification plate OCR through ONNX Runtime (fast-plate-ocr models).

The model classifies each of ``max_plate_slots`` character positions over the
alphabet, so every character comes with its own confidence. Padding
positions are dropped. Models with a region head also return the plate's
country / region and its confidence. The input layout (NHWC or NCHW, uint8 or
float) is read from the ONNX graph so compatible exports can be swapped in.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from pathscope.recognition.common.onnx import create_session
from pathscope.recognition.common.types import PlateRead
from pathscope.recognition.plate.ocr.base import PlateOcr, PlateOcrConfig

_INTERP = {"linear": cv2.INTER_LINEAR, "cubic": cv2.INTER_CUBIC, "nearest": cv2.INTER_NEAREST, "area": cv2.INTER_AREA, "lanczos4": cv2.INTER_LANCZOS4}


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max(axis=-1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=-1, keepdims=True)


class OnnxSlotOcr(PlateOcr):
    id = "slot-ocr-onnx"

    def __init__(self, model_path: str | Path, config: PlateOcrConfig, device: str = "auto", model_version: str = "") -> None:
        if not Path(model_path).exists():
            raise FileNotFoundError(f"plate OCR model not found: {model_path}")
        self.model_path = str(model_path)
        self.model_version = model_version or Path(model_path).stem
        self.config = config
        self._session, self.resolved_device = create_session(model_path, device)
        inp = self._session.get_inputs()[0]
        self._input_name = inp.name
        shape = list(inp.shape)
        self._nhwc = len(shape) == 4 and isinstance(shape[3], int) and shape[3] in (1, 3)
        self._channels = int(shape[3]) if self._nhwc else (int(shape[1]) if len(shape) == 4 and isinstance(shape[1], int) else (1 if config.image_color_mode == "grayscale" else 3))
        self._dtype = np.uint8 if "uint8" in inp.type else np.float32
        n_alpha = len(config.alphabet)
        plate_size = config.max_plate_slots * n_alpha
        self._plate_output = None
        self._region_output = None
        for o in self._session.get_outputs():
            dims = [d for d in o.shape[1:] if isinstance(d, int)]
            size = int(np.prod(dims)) if dims else 0
            if size == plate_size or (len(o.shape) == 3 and o.shape[1] == config.max_plate_slots):
                self._plate_output = o.name
            elif config.plate_regions and size == len(config.plate_regions):
                self._region_output = o.name
        if self._plate_output is None:
            self._plate_output = self._session.get_outputs()[0].name
        self._fetch = [self._plate_output] + ([self._region_output] if self._region_output else [])

    # ------------------------------------------------------------- preprocessing
    def preprocess(self, crop_bgr: np.ndarray) -> np.ndarray:
        cfg = self.config
        if self._channels == 1:
            img = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        else:
            img = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        interp = _INTERP.get(cfg.interpolation, cv2.INTER_LINEAR)
        if cfg.keep_aspect_ratio:
            h, w = img.shape[:2]
            r = min(cfg.img_height / h, cfg.img_width / w)
            nh, nw = max(1, int(round(h * r))), max(1, int(round(w * r)))
            resized = cv2.resize(img, (nw, nh), interpolation=interp)
            pad = cfg.padding_color[0] if self._channels == 1 else cfg.padding_color
            canvas = np.full((cfg.img_height, cfg.img_width) + (() if self._channels == 1 else (3,)), pad, dtype=np.uint8)
            top, left = (cfg.img_height - nh) // 2, (cfg.img_width - nw) // 2
            canvas[top : top + nh, left : left + nw] = resized
            img = canvas
        else:
            img = cv2.resize(img, (cfg.img_width, cfg.img_height), interpolation=interp)
        if img.ndim == 2:
            img = img[..., None]
        x = img.astype(self._dtype)
        if self._dtype == np.float32:
            x = x / 255.0
        if not self._nhwc:
            x = x.transpose(2, 0, 1)
        return np.ascontiguousarray(x[None])

    # ------------------------------------------------------------- reading
    def read(self, crop_bgr: np.ndarray) -> PlateRead | None:
        return self.read_batch([crop_bgr])[0]

    def read_batch(self, crops: list[np.ndarray]) -> list[PlateRead | None]:
        if not crops:
            return []
        batch = np.concatenate([self.preprocess(c) for c in crops], axis=0)
        outs = self._session.run(self._fetch, {self._input_name: batch})
        cfg = self.config
        plate = np.asarray(outs[0]).reshape(len(crops), cfg.max_plate_slots, len(cfg.alphabet))
        if plate.min() < 0.0 or plate.max() > 1.0001:
            plate = _softmax(plate)
        regions = None
        if len(outs) > 1:
            regions = np.asarray(outs[1]).reshape(len(crops), -1)
            if regions.min() < 0.0 or regions.max() > 1.0001:
                regions = _softmax(regions)
        reads: list[PlateRead | None] = []
        for b in range(len(crops)):
            idx = plate[b].argmax(axis=-1)
            probs = plate[b].max(axis=-1)
            chars: list[str] = []
            confs: list[float] = []
            for i, p in zip(idx, probs, strict=False):
                ch = cfg.alphabet[int(i)]
                if ch == cfg.pad_char:
                    continue
                chars.append(ch)
                confs.append(float(p))
            region = None
            region_conf = None
            if regions is not None and cfg.plate_regions:
                ri = int(regions[b].argmax())
                if ri < len(cfg.plate_regions):
                    region = cfg.plate_regions[ri]
                    region_conf = float(regions[b][ri])
            reads.append(PlateRead(chars, confs, region, region_conf) if chars else None)
        return reads

    def close(self) -> None:
        self._session = None
