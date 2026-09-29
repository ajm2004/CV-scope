"""Tracker registry: catalog shown in the UI, factory and settings validation."""

from __future__ import annotations

from pathlib import Path

from pathscope.vision.trackers.appearance import (
    ColorHistogramEncoder,
    TorchvisionEncoder,
    cnn_available,
    cnn_weights_installed,
    list_onnx_reid_models,
    reid_dir,
)
from pathscope.vision.trackers.base import Tracker, TrackerStats, TrackerUpdate
from pathscope.vision.trackers.botsort import BoTSORT, BoTSORTSettings
from pathscope.vision.trackers.bytetrack import ByteTrack, ByteTrackSettings

_LICENSE = "MIT (algorithm reference implementation); CV-Scope implementation Apache-2.0"

_COMMON_SETTINGS = [
    {"key": "track_buffer", "label": "Frames to keep searching for a lost object", "type": "int", "default": 30, "min": 1, "max": 600,
     "help": "Counted in processed frames. Longer keeps ids through longer occlusions but risks joining two different objects."},
    {"key": "min_hits", "label": "Frames before a new object is reported", "type": "int", "default": 2, "min": 1, "max": 10},
]


def tracker_catalog(models_dir: str | Path | None = None) -> list[dict]:
    """Tracker descriptions and user-facing settings (options depend on what is installed)."""
    cnn_ok, cnn_reason = cnn_available()
    cnn_installed = cnn_ok and cnn_weights_installed("resnet18", models_dir)
    onnx_models = list_onnx_reid_models(models_dir)
    folder = reid_dir(models_dir)
    appearance_help = (
        "Helps when people cross or walk close together. The colour histogram fails for uniforms or "
        "same-coloured vehicles. Appearance summaries stay in memory while an object is tracked and are "
        f"never stored. Custom ONNX re-identification models go in {folder or 'the models/reid folder'}."
    )
    appearance_options = [
        {"value": "none", "label": "Off", "available": True},
        {"value": "histogram", "label": "Colour histogram (fast, no model)", "available": True},
        {
            "value": "cnn",
            "label": "Deep features, ResNet-18 (GPU recommended)",
            "available": cnn_installed,
            "reason": cnn_reason if not cnn_ok else ("" if cnn_installed else "Install 'ResNet-18 appearance features' on the Models page first."),
        },
        *({"value": f"onnx:{name}", "label": f"Custom re-identification model: {name}", "available": True} for name in onnx_models),
    ]
    return [
        {
            "id": "bytetrack",
            "name": "ByteTrack",
            "description": (
                "Two-stage IoU association with a Kalman motion model. Fast, robust default for "
                "people and vehicles; keeps ids through short occlusions."
            ),
            "license": _LICENSE,
            "source": "https://github.com/ifzhang/ByteTrack",
            "available": True,
            "settings": [
                {"key": "track_thresh", "label": "Detection confidence to start or continue a track", "type": "float", "default": 0.5, "min": 0.05, "max": 0.95},
                {"key": "match_thresh", "label": "Maximum match cost, 1 − IoU (higher accepts looser matches)", "type": "float", "default": 0.8, "min": 0.1, "max": 0.99},
                *_COMMON_SETTINGS,
            ],
        },
        {
            "id": "botsort",
            "name": "BoT-SORT",
            "description": (
                "ByteTrack association plus camera-motion compensation and a Kalman filter on box "
                "width and height, with optional appearance matching. Choose it when the camera can "
                "shake or pan, or when people often cross or walk close together. Slower than ByteTrack."
            ),
            "license": _LICENSE,
            "source": "https://github.com/NirAharon/BoT-SORT",
            "available": True,
            "settings": [
                {"key": "gmc_method", "label": "Compensate for camera movement", "type": "enum", "default": "sparseOptFlow",
                 "options": [
                     {"value": "sparseOptFlow", "label": "Optical flow (recommended)", "available": True},
                     {"value": "orb", "label": "ORB feature matching", "available": True},
                     {"value": "ecc", "label": "Image alignment, ECC (slow)", "available": True},
                     {"value": "none", "label": "Off (the camera never moves)", "available": True},
                 ],
                 "help": "Estimates how the whole image moved between frames (shake, wind, a bumped mount) and moves predicted positions with it."},
                {"key": "appearance", "label": "Use appearance to keep identities through occlusions", "type": "enum", "default": "none",
                 "options": appearance_options,
                 "help": appearance_help},
                {"key": "appearance_thresh", "label": "Minimum appearance similarity", "type": "float", "default": None, "nullable": True, "min": 0.0, "max": 1.0,
                 "help": f"Empty uses the calibrated value: colour histogram {ColorHistogramEncoder.default_min_similarity}, ResNet-18 {TorchvisionEncoder.default_min_similarity}, custom models 0.75."},
                {"key": "track_thresh", "label": "Detection confidence to continue a track", "type": "float", "default": 0.5, "min": 0.05, "max": 0.95},
                {"key": "new_track_thresh", "label": "Detection confidence to start a new track", "type": "float", "default": 0.6, "min": 0.05, "max": 0.99},
                {"key": "match_thresh", "label": "Maximum match cost, 1 − IoU (higher accepts looser matches)", "type": "float", "default": 0.8, "min": 0.1, "max": 0.99},
                {"key": "proximity_thresh", "label": "Maximum box distance for appearance matching, 1 − IoU", "type": "float", "default": 0.5, "min": 0.05, "max": 0.95},
                *_COMMON_SETTINGS,
            ],
        },
    ]


_SETTINGS = {"bytetrack": ByteTrackSettings, "botsort": BoTSORTSettings}


def validate_tracker_settings(tracker_id: str, settings: dict | None) -> dict:
    """Coerce and validate settings for a tracker. Returns the full resolved settings.

    Raises ``ValueError`` with a user-facing message.
    """
    tid = tracker_id or "bytetrack"
    if tid == "auto":
        tid = "bytetrack"
    cls = _SETTINGS.get(tid)
    if cls is None:
        raise ValueError(f"unknown tracker '{tracker_id}'")
    from dataclasses import asdict

    return asdict(cls.from_dict(settings))


def create_tracker(tracker_id: str, settings: dict | None = None, device: str = "cpu", models_dir: str | Path | None = None) -> Tracker:
    if tracker_id in ("", "bytetrack", "auto"):
        return ByteTrack(ByteTrackSettings.from_dict(settings))
    if tracker_id == "botsort":
        return BoTSORT(BoTSORTSettings.from_dict(settings), device=device, models_dir=str(models_dir) if models_dir else None)
    raise ValueError(f"unknown or unavailable tracker '{tracker_id}'")


__all__ = [
    "Tracker",
    "TrackerStats",
    "TrackerUpdate",
    "ByteTrack",
    "ByteTrackSettings",
    "BoTSORT",
    "BoTSORTSettings",
    "create_tracker",
    "tracker_catalog",
    "validate_tracker_settings",
]
