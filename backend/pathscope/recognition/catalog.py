"""Recognition models for the Hardware and Model Manager.

All models run locally; weights are downloaded on demand into
``<models>/recognition``. Licences are recorded honestly: the OpenCV Zoo and
fast-plate-ocr / open-image-models files are permissive (MIT / Apache-2.0),
while the InsightFace model pack is for non-commercial research use only.
"""

from __future__ import annotations

_OPENCV_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
_INSIGHTFACE_PACK = "https://github.com/deepinsight/insightface/releases/download/model-zoo/buffalo_l.zip"
_OIM = "https://github.com/ankandrew/open-image-models/releases/download/assets/"
_FPO = "https://github.com/ankandrew/fast-plate-ocr/releases/download/arg-plates/"
_ORT_RT = ["ort-tensorrt", "ort-cuda", "ort-cpu"]
_INSIGHTFACE_LICENSE = "Non-commercial research (InsightFace model pack)"
_INSIGHTFACE_NOTE = (
    "InsightFace code is MIT, but its pretrained model packs (buffalo_l) are provided for "
    "non-commercial research purposes only. Do not deploy commercially without your own licence "
    "from the authors. Only the detector and embedding files are extracted; the pack's gender/age "
    "model is never installed."
)

PLATE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_"


def recognition_models() -> list:
    from pathscope.models.catalog import ModelSpec

    def spec(**kw) -> ModelSpec:
        base = dict(classes=[], trackable_classes=[], subdir="recognition", relative_accuracy=0, relative_speed=0)
        base.update(kw)
        return ModelSpec(**base)

    yunet = spec(
        id="face-det-yunet", name="YuNet face detector (2023mar)", family="yunet", provider="opencv", task="face_detection",
        file_name="face_detection_yunet_2023mar.onnx", download_url=_OPENCV_ZOO + "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        size_mb=0.22, parameters_m=0.08, min_vram_gb=None, min_ram_gb=1.0, compute_class="low", cpu_suitability="good", gpu_suitability="fair",
        relative_accuracy=3, relative_speed=5, reference_note="WIDER Face accuracy: see the OpenCV Zoo model card.",
        runtimes=["opencv-dnn-cpu"], default_image_size=320, license="MIT",
        license_note="The OpenCV Zoo YuNet files are MIT licensed and may be used in commercial products.",
        source_url="https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet", requires_package="opencv",
        module="face", model_version="yunet-2023mar",
        notes="Default face detector. Finds faces from about 10x10 px and returns the five landmarks used for alignment. About 15 ms per 768x432 frame on a CPU; much less on the head crops CV-Scope uses.",
    )
    sface = spec(
        id="face-emb-sface", name="SFace face embeddings (2021dec)", family="sface", provider="opencv", task="face_embedding",
        file_name="face_recognition_sface_2021dec.onnx", download_url=_OPENCV_ZOO + "face_recognition_sface/face_recognition_sface_2021dec.onnx",
        size_mb=36.9, parameters_m=9.6, min_vram_gb=None, min_ram_gb=1.0, compute_class="low", cpu_suitability="good", gpu_suitability="fair",
        relative_accuracy=3, relative_speed=4, reference_note="LFW accuracy: see the OpenCV Zoo model card.",
        runtimes=["opencv-dnn-cpu"], default_image_size=112, license="Apache-2.0",
        license_note="The OpenCV Zoo SFace files are Apache-2.0 licensed and may be used in commercial products.",
        source_url="https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface", requires_package="opencv",
        module="face", model_version="sface-2021dec", meta={"embedding_dim": 128, "match_threshold": 0.46, "possible_threshold": 0.363},
        notes="Default embedding model: 128-d embeddings from a 112x112 aligned crop. OpenCV documents a verification threshold of 0.363 (cosine); CV-Scope reports Recognized from 0.46 by default.",
    )
    scrfd = spec(
        id="face-det-scrfd-10g", name="SCRFD-10G face detector (InsightFace)", family="scrfd", provider="onnxruntime", task="face_detection",
        file_name="det_10g.onnx", download_url=_INSIGHTFACE_PACK, archive_member="det_10g.onnx",
        size_mb=16.1, parameters_m=4.2, min_vram_gb=1.0, min_ram_gb=2.0, compute_class="medium", cpu_suitability="fair", gpu_suitability="good",
        relative_accuracy=5, relative_speed=3, reference_note="WIDER Face hard-set AP: see the SCRFD paper (Guo et al., 2021).",
        runtimes=_ORT_RT, default_image_size=640, license=_INSIGHTFACE_LICENSE, license_note=_INSIGHTFACE_NOTE,
        source_url="https://github.com/deepinsight/insightface/tree/master/detection/scrfd", requires_package="onnxruntime",
        module="face", model_version="scrfd-10g-kps", meta={"archive_size_mb": 275},
        notes="Stronger detector for small, blurred and non-frontal faces. Downloaded as part of the 275 MB buffalo_l pack; research use only.",
    )
    arcface = spec(
        id="face-emb-arcface-r50", name="ArcFace ResNet-50 embeddings (InsightFace, WebFace600K)", family="arcface", provider="onnxruntime", task="face_embedding",
        file_name="w600k_r50.onnx", download_url=_INSIGHTFACE_PACK, archive_member="w600k_r50.onnx",
        size_mb=166.3, parameters_m=43.6, min_vram_gb=2.0, min_ram_gb=3.0, compute_class="high", cpu_suitability="poor", gpu_suitability="good",
        relative_accuracy=5, relative_speed=2, reference_note="IJB-C / LFW figures: see the InsightFace model zoo.",
        runtimes=_ORT_RT, default_image_size=112, license=_INSIGHTFACE_LICENSE, license_note=_INSIGHTFACE_NOTE,
        source_url="https://github.com/deepinsight/insightface/tree/master/model_zoo", requires_package="onnxruntime",
        module="face", model_version="arcface-r50-w600k", meta={"embedding_dim": 512, "match_threshold": 0.45, "possible_threshold": 0.32, "archive_size_mb": 275},
        notes="512-d embeddings; more robust than SFace on low-quality CCTV footage. GPU recommended. Research use only.",
    )

    def plate_det(size: int, variant: str, size_mb: float, params: float, compute: str, cpu: str, acc: int, spd: int, notes: str) -> ModelSpec:
        return spec(
            id=f"plate-det-yolov9{variant}-{size}", name=f"YOLOv9-{variant} licence plate detector ({size} px)", family="yolov9-plate", provider="onnxruntime", task="plate_detection",
            file_name=f"yolo-v9-{variant}-{size}-license-plates-end2end.onnx", download_url=f"{_OIM}yolo-v9-{variant}-{size}-license-plates-end2end.onnx",
            size_mb=size_mb, parameters_m=params, min_vram_gb=0.5 if compute == "low" else 1.0, min_ram_gb=1.0, compute_class=compute, cpu_suitability=cpu, gpu_suitability="good",
            relative_accuracy=acc, relative_speed=spd, reference_note="Trained by the open-image-models project on public plate datasets; see its model card.",
            runtimes=_ORT_RT, default_image_size=size, license="MIT", license_note="open-image-models weights and code are MIT licensed.",
            source_url="https://github.com/ankandrew/open-image-models", requires_package="onnxruntime",
            module="plate", model_version=f"yolov9-{variant}-{size}-plates", notes=notes,
        )

    det384 = plate_det(384, "t", 7.4, 2.0, "low", "good", 3, 5, "Default plate detector. End-to-end export (NMS included). About 8 ms per vehicle crop on a CPU.")
    det640 = plate_det(640, "t", 7.5, 2.0, "medium", "fair", 4, 4, "Higher input resolution for small, distant plates.")
    det608 = plate_det(608, "s", 27.3, 7.2, "medium", "fair", 5, 3, "Larger backbone; best accuracy on difficult footage, GPU recommended.")

    def ocr(model_id: str, name: str, stem: str, size_mb: float, params: float, slots: int, region_head: bool, acc: int, spd: int, notes: str) -> ModelSpec:
        cfg_name = f"{stem}_plate_config.yaml"
        return spec(
            id=model_id, name=name, family="cct-plate-ocr", provider="onnxruntime", task="plate_ocr",
            file_name=f"{stem}.onnx", download_url=f"{_FPO}{stem}.onnx",
            extra_files=[{"url": f"{_FPO}{cfg_name}", "file_name": cfg_name}],
            size_mb=size_mb, parameters_m=params, min_vram_gb=None, min_ram_gb=1.0, compute_class="low", cpu_suitability="good", gpu_suitability="good",
            relative_accuracy=acc, relative_speed=spd, reference_note="Validation accuracy: see the fast-plate-ocr model zoo.",
            runtimes=_ORT_RT, default_image_size=128, license="MIT", license_note="fast-plate-ocr weights and code are MIT licensed.",
            source_url="https://github.com/ankandrew/fast-plate-ocr", requires_package="onnxruntime",
            module="plate", model_version=stem.replace("_", "-"),
            meta={"ocr_config_file": cfg_name, "max_plate_slots": slots, "alphabet": PLATE_ALPHABET, "pad_char": "_", "img_height": 64, "img_width": 128, "image_color_mode": "rgb", "keep_aspect_ratio": False, "has_region_head": region_head},
            notes=notes,
        )

    ocr_s_v2 = ocr("plate-ocr-cct-s-v2", "CCT-S v2 global plate OCR (with region head)", "cct_s_v2_global", 5.0, 1.3, 10, True, 4, 4,
                   "Default OCR. Compact Convolutional Transformer trained on plates from 65 countries; also predicts the plate's region. Up to 10 characters, per-character confidence.")
    ocr_xs_v1 = ocr("plate-ocr-cct-xs-v1", "CCT-XS v1 global plate OCR", "cct_xs_v1_global", 2.0, 0.5, 9, False, 3, 5,
                    "Smallest OCR model, up to 9 characters. Faster but less accurate than CCT-S v2.")
    return [yunet, sface, scrfd, arcface, det384, det640, det608, ocr_s_v2, ocr_xs_v1]


RECOGNITION_TASKS = ("face_detection", "face_embedding", "plate_detection", "plate_ocr")
