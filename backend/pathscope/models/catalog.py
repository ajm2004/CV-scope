"""Static catalog of supported detection models.

Numbers marked ``reference_`` are the values published by the upstream
projects for the COCO validation set and reference hardware. They are shown
for relative comparison only; CV-Scope never claims local FPS until the user
runs a benchmark on their own machine.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from pathscope.vision.classes import COCO_CLASSES

COCO_TRACKABLE = ["person", "bicycle", "car", "motorcycle", "bus", "truck", "train", "boat", "dog", "cat", "horse"]


@dataclass
class ModelSpec:
    id: str
    name: str
    family: str  # yolo11 | yolov8 | rtdetr | torchvision | yolo11-onnx
    provider: str  # ultralytics | onnxruntime | torchvision
    task: str = "detection"
    classes: list[str] = field(default_factory=lambda: list(COCO_CLASSES))
    trackable_classes: list[str] = field(default_factory=lambda: list(COCO_TRACKABLE))
    file_name: str = ""  # weight file name inside the models directory
    download_url: str | None = None
    size_mb: float | None = None
    parameters_m: float | None = None
    # Approximate requirements (order-of-magnitude guidance, not measurements)
    min_vram_gb: float | None = None
    min_ram_gb: float = 4.0
    compute_class: str = "low"  # low | medium | high | very-high
    cpu_suitability: str = "good"  # good | fair | poor
    gpu_suitability: str = "good"
    # 1..5 ordinal, relative within the catalog
    relative_accuracy: int = 3
    relative_speed: int = 3
    reference_map: float | None = None  # COCO val mAP50-95 as published upstream
    reference_note: str = ""
    runtimes: list[str] = field(default_factory=list)
    default_image_size: int = 640
    license: str = ""
    license_note: str = ""
    source_url: str = ""
    requires_package: str = ""  # python package that must be importable
    export_from: str | None = None  # model id whose weights can be exported to produce this one
    notes: str = ""
    # ---- recognition models (licensed modules) and packaging details
    subdir: str = ""  # folder inside the models directory ("" = the models directory itself)
    archive_member: str | None = None  # the download is a zip; only this member is extracted
    extra_files: list[dict] = field(default_factory=list)  # [{"url": ..., "file_name": ...}] downloaded next to the weights
    module: str | None = None  # "face" | "plate" for recognition models, else None
    model_version: str = ""  # recorded with every recognition event
    meta: dict = field(default_factory=dict)  # model-specific facts (embedding dim, thresholds, OCR layout)

    def to_dict(self) -> dict:
        return asdict(self)


_ULTRA_ASSETS = "https://github.com/ultralytics/assets/releases/download/v8.3.0/"
_AGPL = "AGPL-3.0"
_AGPL_NOTE = (
    "Ultralytics weights and code are AGPL-3.0. Fine for research and internal use; "
    "distributing a derived product requires AGPL compliance or an Ultralytics licence."
)
_ULTRA_RT = ["torch-cuda", "torch-mps", "torch-cpu"]


def _yolo11(letter: str, size_mb: float, params: float, mmap: float, vram: float, acc: int, spd: int, compute: str, cpu: str) -> ModelSpec:
    return ModelSpec(
        id=f"yolo11{letter}",
        name=f"YOLO11{letter}",
        family="yolo11",
        provider="ultralytics",
        file_name=f"yolo11{letter}.pt",
        download_url=f"{_ULTRA_ASSETS}yolo11{letter}.pt",
        size_mb=size_mb,
        parameters_m=params,
        min_vram_gb=vram,
        compute_class=compute,
        cpu_suitability=cpu,
        gpu_suitability="good",
        relative_accuracy=acc,
        relative_speed=spd,
        reference_map=mmap,
        reference_note="COCO val2017 mAP50-95 published by Ultralytics",
        runtimes=_ULTRA_RT,
        license=_AGPL,
        license_note=_AGPL_NOTE,
        source_url="https://docs.ultralytics.com/models/yolo11/",
        requires_package="ultralytics",
    )


def _yolov8(letter: str, size_mb: float, params: float, mmap: float, vram: float, acc: int, spd: int, compute: str, cpu: str) -> ModelSpec:
    spec = _yolo11(letter, size_mb, params, mmap, vram, acc, spd, compute, cpu)
    spec.id = f"yolov8{letter}"
    spec.name = f"YOLOv8{letter}"
    spec.family = "yolov8"
    spec.file_name = f"yolov8{letter}.pt"
    spec.download_url = f"{_ULTRA_ASSETS}yolov8{letter}.pt"
    spec.source_url = "https://docs.ultralytics.com/models/yolov8/"
    spec.notes = "Previous generation; kept for reproducing older studies."
    return spec


def _onnx_export(base: ModelSpec, acc: int, spd: int, cpu: str) -> ModelSpec:
    return ModelSpec(
        id=f"{base.id}-onnx",
        name=f"{base.name} (ONNX)",
        family=f"{base.family}-onnx",
        provider="onnxruntime",
        file_name=base.file_name.replace(".pt", ".onnx"),
        download_url=None,
        size_mb=(base.size_mb or 0) * 2 if base.size_mb else None,
        parameters_m=base.parameters_m,
        min_vram_gb=base.min_vram_gb,
        compute_class=base.compute_class,
        cpu_suitability=cpu,
        gpu_suitability="good",
        relative_accuracy=acc,
        relative_speed=spd,
        reference_map=base.reference_map,
        reference_note=base.reference_note,
        runtimes=["ort-tensorrt", "ort-cuda", "ort-cpu"],
        license=base.license,
        license_note=base.license_note + " The exported ONNX graph keeps the weights' licence.",
        source_url=base.source_url,
        requires_package="onnxruntime",
        export_from=base.id,
        notes="Produced locally by exporting the PyTorch weights; runs without PyTorch.",
    )


def _torchvision(model_id: str, name: str, weights_enum: str, size_mb: float, params: float, mmap: float, vram: float, acc: int, spd: int, compute: str, cpu: str, notes: str = "") -> ModelSpec:
    return ModelSpec(
        id=model_id,
        name=name,
        family="torchvision",
        provider="torchvision",
        file_name="",
        download_url=None,
        size_mb=size_mb,
        parameters_m=params,
        min_vram_gb=vram,
        compute_class=compute,
        cpu_suitability=cpu,
        gpu_suitability="good",
        relative_accuracy=acc,
        relative_speed=spd,
        reference_map=mmap,
        reference_note="COCO val2017 box mAP published by torchvision",
        runtimes=_ULTRA_RT,
        default_image_size=640,
        license="BSD-3-Clause",
        license_note="torchvision code and weights are BSD-3-Clause (permissive).",
        source_url="https://pytorch.org/vision/stable/models.html#object-detection",
        requires_package="torchvision",
        notes=notes or f"Weights enum: {weights_enum}",
    )


def build_catalog() -> list[ModelSpec]:
    y11n = _yolo11("n", 5.6, 2.6, 39.5, 1.0, 2, 5, "low", "good")
    y11s = _yolo11("s", 19.2, 9.4, 47.0, 2.0, 3, 4, "medium", "fair")
    y11m = _yolo11("m", 40.5, 20.1, 51.5, 4.0, 4, 3, "high", "poor")
    y11l = _yolo11("l", 51.2, 25.3, 53.4, 6.0, 4, 2, "high", "poor")
    y11x = _yolo11("x", 114.4, 56.9, 54.7, 8.0, 5, 1, "very-high", "poor")
    catalog: list[ModelSpec] = [
        y11n, y11s, y11m, y11l, y11x,
        _yolov8("n", 6.5, 3.2, 37.3, 1.0, 2, 5, "low", "good"),
        _yolov8("s", 22.5, 11.2, 44.9, 2.0, 3, 4, "medium", "fair"),
        _yolov8("m", 52.0, 25.9, 50.2, 4.0, 4, 3, "high", "poor"),
        ModelSpec(
            id="rtdetr-l",
            name="RT-DETR-L",
            family="rtdetr",
            provider="ultralytics",
            file_name="rtdetr-l.pt",
            download_url=f"{_ULTRA_ASSETS}rtdetr-l.pt",
            size_mb=63.0,
            parameters_m=32.0,
            min_vram_gb=6.0,
            compute_class="high",
            cpu_suitability="poor",
            gpu_suitability="good",
            relative_accuracy=4,
            relative_speed=2,
            reference_map=53.0,
            reference_note="COCO val2017 mAP50-95 published by Ultralytics",
            runtimes=_ULTRA_RT,
            default_image_size=640,
            license=_AGPL,
            license_note="Ultralytics implementation of RT-DETR (AGPL-3.0). The original Baidu RT-DETR is Apache-2.0.",
            source_url="https://docs.ultralytics.com/models/rtdetr/",
            requires_package="ultralytics",
            notes="Transformer detector, no NMS. Strong on crowded scenes; needs a GPU for real time.",
        ),
        ModelSpec(
            id="rtdetr-x",
            name="RT-DETR-X",
            family="rtdetr",
            provider="ultralytics",
            file_name="rtdetr-x.pt",
            download_url=f"{_ULTRA_ASSETS}rtdetr-x.pt",
            size_mb=129.0,
            parameters_m=67.0,
            min_vram_gb=8.0,
            compute_class="very-high",
            cpu_suitability="poor",
            gpu_suitability="good",
            relative_accuracy=5,
            relative_speed=1,
            reference_map=54.8,
            reference_note="COCO val2017 mAP50-95 published by Ultralytics",
            runtimes=_ULTRA_RT,
            license=_AGPL,
            license_note="Ultralytics implementation of RT-DETR (AGPL-3.0).",
            source_url="https://docs.ultralytics.com/models/rtdetr/",
            requires_package="ultralytics",
            notes="Highest accuracy in the catalog; suited to offline processing of recorded footage.",
        ),
        _onnx_export(y11n, 2, 5, "good"),
        _onnx_export(y11s, 3, 4, "fair"),
        _onnx_export(y11m, 4, 3, "poor"),
        _torchvision(
            "tv-ssdlite320", "SSDLite320 MobileNetV3", "SSDLite320_MobileNet_V3_Large_Weights.COCO_V1",
            13.4, 3.4, 21.3, 1.0, 1, 5, "low", "good",
            "Fast permissively licensed detector; lower accuracy on small or distant objects.",
        ),
        _torchvision(
            "tv-fasterrcnn-mobilenet", "Faster R-CNN MobileNetV3 FPN", "FasterRCNN_MobileNet_V3_Large_FPN_Weights.COCO_V1",
            74.2, 19.4, 32.8, 2.0, 2, 3, "medium", "fair",
            "Permissively licensed two-stage detector with a light backbone.",
        ),
        _torchvision(
            "tv-fasterrcnn-r50v2", "Faster R-CNN ResNet50 FPN v2", "FasterRCNN_ResNet50_FPN_V2_Weights.COCO_V1",
            167.1, 43.7, 46.7, 4.0, 4, 1, "very-high", "poor",
            "Accurate permissively licensed detector; slow, best for offline analysis on a GPU.",
        ),
        ModelSpec(
            id="appearance-resnet18",
            name="ResNet-18 appearance features",
            family="appearance",
            provider="torchvision",
            task="appearance",
            classes=[],
            trackable_classes=[],
            size_mb=44.7,
            parameters_m=11.7,
            min_vram_gb=0.5,
            min_ram_gb=2.0,
            compute_class="low",
            cpu_suitability="fair",
            gpu_suitability="good",
            relative_accuracy=0,
            relative_speed=0,
            runtimes=_ULTRA_RT,
            default_image_size=256,
            license="BSD-3-Clause",
            license_note=(
                "torchvision code is BSD-3-Clause; the weights are ImageNet-pretrained "
                "(see the torchvision documentation for dataset terms)."
            ),
            source_url="https://pytorch.org/vision/stable/models/generated/torchvision.models.resnet18.html",
            requires_package="torchvision",
            notes=(
                "Used by the BoT-SORT tracker when 'Deep features' appearance matching is selected. "
                "General-purpose image features, not a person re-identification model. Appearance "
                "summaries are kept in memory during a run and never stored."
            ),
        ),
    ]
    # Face and plate models of the licensed recognition modules (downloadable
    # like any other model; usable only with a valid licence).
    from pathscope.recognition.catalog import recognition_models

    catalog.extend(recognition_models())
    return catalog


CATALOG: list[ModelSpec] = build_catalog()
CATALOG_BY_ID: dict[str, ModelSpec] = {m.id: m for m in CATALOG}


def get_model_spec(model_id: str) -> ModelSpec:
    try:
        return CATALOG_BY_ID[model_id]
    except KeyError as exc:
        raise KeyError(f"unknown model '{model_id}'") from exc
