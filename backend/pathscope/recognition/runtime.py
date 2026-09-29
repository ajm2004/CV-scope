"""The per-run recognition runtime.

Built inside the camera worker from the run payload that the API process
prepared (``pathscope.recognition.service.build_run_payload``): model paths,
central settings, the enrolled identities' templates (decrypted in memory
only) and the vehicle registry. The vision pipeline calls ``observe`` once
per processed frame; the rule engine uses the runtime as its
``EntityResolver``. Nothing here touches the database.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from pathscope.domain.entities import EntityRef, anonymous_entity, module_for_class
from pathscope.recognition.face.matcher import FaceMatcher, IdentityTemplates
from pathscope.recognition.face.pipeline import FacePipelineConfig, FaceRecognitionPipeline
from pathscope.recognition.face.stack import create_face_stack
from pathscope.recognition.plate.parser import PlateFormat, PlateParser
from pathscope.recognition.plate.pipeline import (
    PlatePipelineConfig,
    PlateRecognitionPipeline,
    VehicleEntry,
    VehicleIndex,
)
from pathscope.recognition.plate.stack import create_plate_stack
from pathscope.vision.types import Track


@dataclass
class RecognitionStepResult:
    events: list[dict] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)


def _date(v) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


class RecognitionRuntime:
    def __init__(self, face: FaceRecognitionPipeline | None = None, plate: PlateRecognitionPipeline | None = None, subject_grace_s: float = 5.0, diag_interval_s: float = 1.0) -> None:
        self.face = face
        self.plate = plate
        self.subject_grace_s = float(subject_grace_s)
        self.diag_interval_s = float(diag_interval_s)
        self._last_diag = 0.0
        self.stats = {"frames": 0, "events": 0}

    # ------------------------------------------------------------- construction
    @classmethod
    def from_payload(cls, payload: dict, device: str = "auto") -> RecognitionRuntime:
        face = None
        plate = None
        if payload.get("face"):
            face = cls._build_face(payload["face"], device, bool(payload.get("store_crops", False)))
        if payload.get("plate"):
            plate = cls._build_plate(payload["plate"], device, bool(payload.get("store_crops", False)))
        return cls(face, plate, float(payload.get("grace_s", 5.0)))

    @staticmethod
    def _build_face(p: dict, device: str, store_crops: bool) -> FaceRecognitionPipeline:
        cfg = dict(p.get("config") or {})
        cfg["store_crops"] = store_crops
        stack = create_face_stack(str(p.get("stack", "opencv")), p.get("models") or {}, device=str(cfg.get("device") or device), cfg=cfg)
        identities: list[IdentityTemplates] = []
        for ident in p.get("identities") or []:
            templates = np.asarray(ident.get("templates") or [], dtype=np.float32)
            if templates.size == 0:
                continue
            identities.append(
                IdentityTemplates(
                    identity_id=str(ident["id"]), display_name=str(ident.get("name") or ident["id"]), embeddings=templates,
                    active=bool(ident.get("active", True)), valid_from=_date(ident.get("valid_from")), valid_until=_date(ident.get("valid_until")),
                    model_version=str(ident.get("model_version", "")),
                )
            )
        match_thr = cfg.get("match_threshold")
        possible_thr = cfg.get("possible_threshold")
        matcher = FaceMatcher(
            identities,
            float(match_thr) if match_thr is not None else stack.embedder.default_match_threshold,
            float(possible_thr) if possible_thr is not None else stack.embedder.default_possible_threshold,
            float(cfg.get("margin", 0.05)),
        )
        return FaceRecognitionPipeline(stack, matcher, FacePipelineConfig.from_settings(cfg))

    @staticmethod
    def _build_plate(p: dict, device: str, store_crops: bool) -> PlateRecognitionPipeline:
        cfg = dict(p.get("config") or {})
        cfg["store_crops"] = store_crops
        stack = create_plate_stack(p.get("models") or {}, device=str(cfg.get("device") or device), cfg=cfg, stack_id=str(p.get("stack", "onnx")))
        formats = [PlateFormat.from_dict(f) for f in (p.get("formats") or [])] or [PlateFormat(id="generic", name="Generic", builtin=True)]
        parser = PlateParser(formats, default_region=str(cfg.get("default_region") or ""))
        vehicles = VehicleIndex([VehicleEntry(str(v["id"]), str(v["plate"]), str(v.get("label", "")), list(v.get("groups") or []), bool(v.get("active", True))) for v in (p.get("vehicles") or [])])
        return PlateRecognitionPipeline(stack, parser, vehicles, PlatePipelineConfig.from_settings(cfg))

    # ------------------------------------------------------------- EntityResolver
    def provides(self) -> set[str]:
        out: set[str] = set()
        if self.face is not None:
            out.add("face")
        if self.plate is not None:
            out.add("plate")
        return out

    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        module = module_for_class(object_class)
        if module == "face" and self.face is not None:
            return self.face.resolve(track_id, object_class)
        if module == "plate" and self.plate is not None:
            return self.plate.resolve(track_id, object_class)
        return anonymous_entity(track_id, object_class)

    def forget(self, track_id: int) -> None:
        if self.face is not None:
            self.face.forget(track_id)
        if self.plate is not None:
            self.plate.forget(track_id)

    # ------------------------------------------------------------- pipeline hook
    def observe(self, frame: np.ndarray, tracks: list[Track], t: float, frame_index: int, wall_time: float | None = None) -> RecognitionStepResult:
        result = RecognitionStepResult()
        self.stats["frames"] += 1
        if self.face is not None:
            t0 = time.perf_counter()
            r = self.face.observe(frame, tracks, t, frame_index, wall_time)
            result.timings_ms["face"] = (time.perf_counter() - t0) * 1000.0
            result.events.extend(r.events)
        if self.plate is not None:
            t0 = time.perf_counter()
            r2 = self.plate.observe(frame, tracks, t, frame_index, wall_time)
            result.timings_ms["plate"] = (time.perf_counter() - t0) * 1000.0
            result.events.extend(r2.events)
        self.stats["events"] += len(result.events)
        return result

    def overlay(self, track_id: int, object_class: str) -> dict | None:
        """Identity / plate for live overlays (names included; the API strips
        them for viewers without a recognition token)."""
        module = module_for_class(object_class)
        if module == "face" and self.face is not None:
            return self.face.overlay(track_id)
        if module == "plate" and self.plate is not None:
            return self.plate.overlay(track_id)
        return None

    def diagnostics_due(self, now: float) -> bool:
        if now - self._last_diag >= self.diag_interval_s:
            self._last_diag = now
            return True
        return False

    def diagnostics(self) -> dict:
        return {
            "face": self.face.diagnostics() if self.face is not None else None,
            "plate": self.plate.diagnostics() if self.plate is not None else None,
            "stats": dict(self.stats),
        }

    def describe(self) -> dict:
        return {
            "modules": sorted(self.provides()),
            "face": self.face.describe() if self.face is not None else None,
            "plate": self.plate.describe() if self.plate is not None else None,
            "subject_grace_s": self.subject_grace_s,
        }

    def close(self) -> None:
        if self.face is not None:
            self.face.close()
        if self.plate is not None:
            self.plate.close()
