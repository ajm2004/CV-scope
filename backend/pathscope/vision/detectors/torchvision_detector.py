"""torchvision provider (BSD-3-Clause): SSDLite and Faster R-CNN variants.

Weights are downloaded by torchvision into ``TORCH_HOME`` (CV-Scope points it
at the models directory) so installation state can be inspected.
"""

from __future__ import annotations

import numpy as np

from pathscope.vision.classes import TORCHVISION_COCO_CATEGORIES, canonical_class
from pathscope.vision.detectors.base import Detector, DetectorConfig, DetectorLoadError
from pathscope.vision.inference.runtime import resolve_device
from pathscope.vision.types import Detection

# model id -> (constructor name, weights enum attribute)
TORCHVISION_MODELS: dict[str, tuple[str, str]] = {
    "tv-ssdlite320": ("ssdlite320_mobilenet_v3_large", "SSDLite320_MobileNet_V3_Large_Weights"),
    "tv-fasterrcnn-mobilenet": ("fasterrcnn_mobilenet_v3_large_fpn", "FasterRCNN_MobileNet_V3_Large_FPN_Weights"),
    "tv-fasterrcnn-r50v2": ("fasterrcnn_resnet50_fpn_v2", "FasterRCNN_ResNet50_FPN_V2_Weights"),
}


class TorchvisionDetector(Detector):
    provider = "torchvision"

    def __init__(self, config: DetectorConfig) -> None:
        super().__init__(config)
        self._model = None
        self._torch = None
        self._names = [canonical_class(n) for n in TORCHVISION_COCO_CATEGORIES]

    def load(self) -> None:
        try:
            import torch
            import torchvision
            from torchvision.models import detection as tvd
        except ImportError as exc:  # pragma: no cover
            raise DetectorLoadError("torch/torchvision are not installed.") from exc
        entry = TORCHVISION_MODELS.get(self.config.model_id)
        if entry is None:
            raise DetectorLoadError(f"'{self.config.model_id}' is not a torchvision model id")
        ctor_name, weights_name = entry
        device, _reason = resolve_device(self.config.device)
        self.resolved_device = device
        try:
            weights = getattr(tvd, weights_name).DEFAULT
            ctor = getattr(tvd, ctor_name)
            model = ctor(weights=weights, box_score_thresh=self.config.confidence)
        except Exception as exc:  # noqa: BLE001
            raise DetectorLoadError(f"Could not build {ctor_name}: {exc}") from exc
        model.eval()
        model.to(device)
        self._model = model
        self._torch = torch
        self._tv_version = torchvision.__version__
        self.loaded = True

    @property
    def class_names(self) -> list[str]:
        return self._names

    def _detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        assert self._model is not None and self._torch is not None
        torch = self._torch
        rgb = frame_bgr[:, :, ::-1].copy()
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).float().div_(255.0).to(self.resolved_device)
        with torch.inference_mode():
            try:
                out = self._model([tensor])[0]
            except RuntimeError as exc:
                if self.resolved_device != "cpu" and "out of memory" in str(exc).lower():
                    self.resolved_device = "cpu"
                    self._model.to("cpu")
                    out = self._model([tensor.cpu()])[0]
                else:
                    raise
        boxes = out["boxes"].cpu().numpy()
        scores = out["scores"].cpu().numpy()
        labels = out["labels"].cpu().numpy().astype(int)
        dets: list[Detection] = []
        for (x1, y1, x2, y2), s, k in zip(boxes, scores, labels, strict=True):
            if s < self.config.confidence:
                continue
            name = self._names[k] if 0 <= k < len(self._names) else str(k)
            if name in ("n/a", "__background__"):
                continue
            dets.append(Detection(name, float(s), (float(x1), float(y1), float(x2), float(y2)), int(k)))
        return dets

    def close(self) -> None:
        self._model = None
        self.loaded = False
