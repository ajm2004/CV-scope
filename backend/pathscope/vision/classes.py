"""Mapping between detector label sets and CV-Scope canonical class names."""

from __future__ import annotations

# COCO 80-class order used by YOLO / RT-DETR checkpoints trained on COCO.
COCO_CLASSES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat",
    "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack",
    "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball",
    "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket",
    "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
    "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book",
    "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

# torchvision COCO category ids (91 slots with "N/A" gaps).
TORCHVISION_COCO_CATEGORIES = [
    "__background__", "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
    "truck", "boat", "traffic light", "fire hydrant", "N/A", "stop sign", "parking meter",
    "bench", "bird", "cat", "dog", "horse", "sheep", "cow", "elephant", "bear", "zebra",
    "giraffe", "N/A", "backpack", "umbrella", "N/A", "N/A", "handbag", "tie", "suitcase",
    "frisbee", "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove",
    "skateboard", "surfboard", "tennis racket", "bottle", "N/A", "wine glass", "cup", "fork",
    "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange", "broccoli", "carrot",
    "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "N/A",
    "dining table", "N/A", "N/A", "toilet", "N/A", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "N/A",
    "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
]

# Detector label -> canonical name (identity for COCO, aliases for other sets)
_ALIASES = {
    "pedestrian": "person",
    "people": "person",
    "motorbike": "motorcycle",
    "bike": "bicycle",
    "lorry": "truck",
    "van": "car",
}


def canonical_class(label: str) -> str:
    label = label.strip().lower()
    return _ALIASES.get(label, label)


def class_ids_for(names: list[str], label_set: list[str]) -> list[int]:
    """Indices in ``label_set`` whose canonical name is in ``names``."""
    wanted = {canonical_class(n) for n in names}
    return [i for i, lbl in enumerate(label_set) if canonical_class(lbl) in wanted]
