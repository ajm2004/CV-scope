"""Central recognition settings: thresholds, throttling, retention, privacy.

Stored in the ordinary ``settings`` table under the ``recognition.`` prefix
but exposed only through the authenticated recognition API (the public
``/api/settings`` endpoint does not list them). Threshold values marked
"model default" (``None``) fall back to the loaded model's calibrated values.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.db.models import Setting

PREFIX = "recognition."

# key -> definition. ``kind``: bool | int | float | enum | string. ``advanced``
# settings appear under Advanced settings in the UI.
RECOGNITION_SETTING_DEFINITIONS: dict[str, dict[str, Any]] = {
    # ---- modules
    "recognition.face.enabled": {"default": True, "section": "face", "label": "Face recognition module", "kind": "bool", "help": "Off shows the module as Disabled even with a valid licence."},
    "recognition.plate.enabled": {"default": True, "section": "plate", "label": "Plate recognition module", "kind": "bool"},
    # ---- face stack
    "recognition.face.stack": {"default": "opencv", "section": "face", "label": "Face model stack", "kind": "enum", "options": ["opencv", "insightface"],
                               "help": "opencv: YuNet detector + SFace embeddings (MIT / Apache-2.0, CPU). insightface: SCRFD + ArcFace ResNet-50 (stronger; model weights are for non-commercial research use only)."},
    "recognition.face.device": {"default": "auto", "section": "face", "label": "Face inference device", "kind": "enum", "options": ["auto", "cuda", "cpu"], "advanced": True},
    "recognition.face.match_threshold": {"default": None, "section": "face", "label": "Similarity for Recognized", "kind": "float", "min": 0.0, "max": 1.0, "nullable": True, "advanced": True,
                                         "help": "Cosine similarity at or above which a match is Recognized. Empty = model default."},
    "recognition.face.possible_threshold": {"default": None, "section": "face", "label": "Similarity for Possible match", "kind": "float", "min": 0.0, "max": 1.0, "nullable": True, "advanced": True,
                                            "help": "Between this and the Recognized threshold a match is reported as Possible and does not trigger rules. Empty = model default."},
    "recognition.face.margin": {"default": 0.05, "section": "face", "label": "Minimum margin to the runner-up", "kind": "float", "min": 0.0, "max": 0.5, "advanced": True,
                                "help": "If the second-best identity is closer than this, the result is Possible match, not Recognized."},
    "recognition.face.min_face_px": {"default": 40, "section": "face", "label": "Minimum face height (px)", "kind": "int", "min": 16, "max": 400,
                                     "help": "Smaller faces are not identified. Enrollment needs at least twice this."},
    "recognition.face.min_quality": {"default": 0.45, "section": "face", "label": "Minimum usable face quality", "kind": "float", "min": 0.0, "max": 1.0, "advanced": True},
    "recognition.face.min_observations": {"default": 3, "section": "face", "label": "Usable observations before deciding", "kind": "int", "min": 1, "max": 20},
    "recognition.face.max_observations": {"default": 12, "section": "face", "label": "Observations kept per track", "kind": "int", "min": 3, "max": 60, "advanced": True},
    "recognition.face.interval_s": {"default": 0.4, "section": "face", "label": "Seconds between face attempts per track", "kind": "float", "min": 0.05, "max": 10.0, "advanced": True},
    "recognition.face.revalidate_s": {"default": 15.0, "section": "face", "label": "Re-check a recognized track every (s)", "kind": "float", "min": 1.0, "max": 600.0, "advanced": True},
    "recognition.face.decision_timeout_s": {"default": 8.0, "section": "face", "label": "Give up on a track after (s) without a usable face", "kind": "float", "min": 1.0, "max": 120.0, "advanced": True},
    "recognition.face.max_per_frame": {"default": 4, "section": "face", "label": "Face attempts per processed frame", "kind": "int", "min": 1, "max": 32, "advanced": True},
    "recognition.face.enrollment_min_quality": {"default": 0.6, "section": "face", "label": "Minimum quality of an enrollment image", "kind": "float", "min": 0.0, "max": 1.0},
    "recognition.face.enrollment_min_views": {"default": 3, "section": "face", "label": "Face views required to enroll", "kind": "int", "min": 1, "max": 6, "help": "Front is always required."},
    "recognition.face.enrollment_consistency": {"default": 0.35, "section": "face", "label": "Minimum consistency between enrollment images", "kind": "float", "min": 0.0, "max": 1.0, "advanced": True,
                                                "help": "Mean similarity between the person's own enrollment embeddings. Lower values suggest the images show different people."},
    # ---- plate stack
    "recognition.plate.detector_model": {"default": "plate-det-yolov9t-384", "section": "plate", "label": "Plate detector", "kind": "string", "help": "Model id from the Models page (plate detection task)."},
    "recognition.plate.ocr_model": {"default": "plate-ocr-cct-s-v2", "section": "plate", "label": "Plate OCR model", "kind": "string"},
    "recognition.plate.device": {"default": "auto", "section": "plate", "label": "Plate inference device", "kind": "enum", "options": ["auto", "cuda", "cpu"], "advanced": True},
    "recognition.plate.min_plate_px": {"default": 14, "section": "plate", "label": "Minimum plate height (px)", "kind": "int", "min": 6, "max": 200},
    "recognition.plate.min_char_confidence": {"default": 0.5, "section": "plate", "label": "Character confidence below which a character is '?'", "kind": "float", "min": 0.0, "max": 1.0, "advanced": True},
    "recognition.plate.min_read_confidence": {"default": 0.6, "section": "plate", "label": "Minimum consensus confidence", "kind": "float", "min": 0.0, "max": 1.0, "advanced": True},
    "recognition.plate.min_observations": {"default": 2, "section": "plate", "label": "Plate reads before deciding", "kind": "int", "min": 1, "max": 20},
    "recognition.plate.consensus_agreement": {"default": 0.6, "section": "plate", "label": "Share of reads that must agree per character", "kind": "float", "min": 0.34, "max": 1.0, "advanced": True},
    "recognition.plate.interval_s": {"default": 0.25, "section": "plate", "label": "Seconds between plate attempts per track", "kind": "float", "min": 0.05, "max": 10.0, "advanced": True},
    "recognition.plate.revalidate_s": {"default": 10.0, "section": "plate", "label": "Re-check a read plate every (s)", "kind": "float", "min": 1.0, "max": 600.0, "advanced": True},
    "recognition.plate.decision_timeout_s": {"default": 6.0, "section": "plate", "label": "Give up on a vehicle after (s) without a readable plate", "kind": "float", "min": 1.0, "max": 120.0, "advanced": True},
    "recognition.plate.max_per_frame": {"default": 4, "section": "plate", "label": "Plate attempts per processed frame", "kind": "int", "min": 1, "max": 32, "advanced": True},
    "recognition.plate.formats": {"default": "generic", "section": "plate", "label": "Plate formats (comma separated, tried in order)", "kind": "string",
                                  "help": "Built in: generic, uae, uk, eu_generic, us_generic. Custom formats: <data>/recognition/plate_formats.json."},
    "recognition.plate.default_region": {"default": "", "section": "plate", "label": "Default country / region code", "kind": "string", "help": "Used when a format cannot infer it, for example AE, GB, DE, US."},
    "recognition.plate.record_unknown_plates": {"default": True, "section": "plate", "label": "Record plates that are not registered", "kind": "bool",
                                                "help": "Deployment policy: off keeps only reads that match a registered vehicle."},
    "recognition.plate.contrast_normalize": {"default": False, "section": "plate", "label": "Normalise plate contrast before OCR (CLAHE)", "kind": "bool", "advanced": True,
                                             "help": "Contrast normalisation only; no generative enhancement is ever applied."},
    # ---- rules
    "recognition.rules.subject_grace_s": {"default": 5.0, "section": "rules", "label": "Wait for recognition after a trigger (s)", "kind": "float", "min": 0.0, "max": 60.0,
                                          "help": "A rule with a recognition condition waits this long for the identity or plate before the event is dropped (or, for 'anonymous', emitted)."},
    # ---- retention / privacy
    "recognition.retention.events_days": {"default": 30, "section": "retention", "label": "Keep recognition events (days, 0 = forever)", "kind": "int", "min": 0, "max": 3650},
    "recognition.retention.unknown_plate_days": {"default": 7, "section": "retention", "label": "Keep unregistered plate reads (days, 0 = forever)", "kind": "int", "min": 0, "max": 3650},
    "recognition.retention.deleted_media_grace_days": {"default": 0, "section": "retention", "label": "Keep media of deleted profiles (days)", "kind": "int", "min": 0, "max": 365,
                                                       "help": "0 removes enrollment images the moment a profile is deleted. Templates are always removed immediately."},
    "recognition.retention.audit_days": {"default": 365, "section": "retention", "label": "Keep audit records (days, 0 = forever)", "kind": "int", "min": 0, "max": 3650},
    "recognition.privacy.store_enrollment_images": {"default": True, "section": "privacy", "label": "Keep enrollment images", "kind": "bool",
                                                    "help": "Off keeps only the encrypted templates after enrollment; re-enrollment then needs new images."},
    "recognition.privacy.store_recognition_crops": {"default": False, "section": "privacy", "label": "Store the best face / plate crop with each recognition event", "kind": "bool",
                                                    "help": "Crops are encrypted at rest and only shown to operators. Off by default."},
}


def definitions() -> list[dict[str, Any]]:
    out = []
    for key, d in RECOGNITION_SETTING_DEFINITIONS.items():
        out.append({"key": key, **{k: v for k, v in d.items() if k != "default"}, "default": d["default"], "advanced": d.get("advanced", False)})
    return out


def all_recognition_settings(session: Session) -> dict[str, Any]:
    values = {key: d["default"] for key, d in RECOGNITION_SETTING_DEFINITIONS.items()}
    for row in session.scalars(select(Setting).where(Setting.key.like(f"{PREFIX}%"))):
        if row.key in RECOGNITION_SETTING_DEFINITIONS:
            values[row.key] = row.value
    return values


def get_recognition_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(Setting, key)
    if row is not None:
        return row.value
    d = RECOGNITION_SETTING_DEFINITIONS.get(key)
    return d["default"] if d is not None else default


def coerce(key: str, value: Any) -> Any:
    d = RECOGNITION_SETTING_DEFINITIONS[key]
    kind = d["kind"]
    if value is None or value == "":
        if d.get("nullable"):
            return None
        if kind in ("string",):
            return ""
        raise ValueError(f"{d['label']} needs a value")
    if kind == "bool":
        return bool(value)
    if kind == "int":
        v = int(value)
    elif kind == "float":
        v = float(value)
    elif kind == "enum":
        options = list(d.get("options", []))
        if key == "recognition.face.stack":
            from pathscope.recognition.face.stack import stub_allowed

            if stub_allowed():
                options.append("stub")  # test stand-in, never in production
        if value not in options:
            raise ValueError(f"'{value}' is not a valid option for {d['label']}")
        return value
    else:
        return str(value)
    if "min" in d and v < d["min"]:
        raise ValueError(f"{d['label']} must be at least {d['min']}")
    if "max" in d and v > d["max"]:
        raise ValueError(f"{d['label']} must be at most {d['max']}")
    return v


def set_recognition_settings(session: Session, values: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate and store; returns (all values, changed keys)."""
    changed: list[str] = []
    for key, value in values.items():
        if key not in RECOGNITION_SETTING_DEFINITIONS:
            continue
        value = coerce(key, value)
        row = session.get(Setting, key)
        if row is None:
            session.add(Setting(key=key, value=value))
            changed.append(key)
        elif row.value != value:
            row.value = value
            changed.append(key)
    session.commit()
    return all_recognition_settings(session), changed


def module_config(values: dict[str, Any], module: str) -> dict[str, Any]:
    """The settings of one module with the prefix stripped: {"enabled": ..., "stack": ...}."""
    prefix = f"{PREFIX}{module}."
    return {k[len(prefix):]: v for k, v in values.items() if k.startswith(prefix)}
