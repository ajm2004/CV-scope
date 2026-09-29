"""Per-track plate recognition.

For each vehicle track the pipeline, at a throttled rate, looks for a plate in
the vehicle box, scores the crop, runs OCR and feeds the read into the
track's temporal consensus. Once enough reads agree on a complete plate, the
text goes through the format layer, is looked up in the vehicle registry and
associated with the track; the association is re-validated periodically.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from pathscope.domain.entities import (
    STATUS_INSUFFICIENT,
    STATUS_RECOGNIZED,
    STATUS_UNKNOWN,
    STATUS_UNRESOLVED,
    EntityRef,
    anonymous_entity,
)
from pathscope.domain.scene import VEHICLE_CLASSES
from pathscope.recognition.common.types import ConsensusResult, PlateObservation, QualityReport
from pathscope.recognition.plate.parser.base import ParsedPlate, PlateParser
from pathscope.recognition.plate.preprocessing import (
    assess_plate_quality,
    plate_crop,
    prepare_for_ocr,
)
from pathscope.recognition.plate.stack import PlateStack
from pathscope.recognition.plate.temporal import PlateConsensus
from pathscope.vision.types import Track


@dataclass
class PlatePipelineConfig:
    min_plate_px: float = 14.0
    min_detection_score: float = 0.3
    min_char_confidence: float = 0.5
    min_read_confidence: float = 0.6
    min_observations: int = 2
    consensus_agreement: float = 0.6
    interval_s: float = 0.25
    revalidate_s: float = 10.0
    decision_timeout_s: float = 6.0
    max_per_frame: int = 4
    contrast_normalize: bool = False
    record_unknown_plates: bool = True
    store_crops: bool = False
    max_reads: int = 15

    @classmethod
    def from_settings(cls, cfg: dict) -> PlatePipelineConfig:
        c = cls()
        for k in ("min_plate_px", "min_detection_score", "min_char_confidence", "min_read_confidence", "consensus_agreement", "interval_s", "revalidate_s", "decision_timeout_s"):
            if cfg.get(k) is not None:
                setattr(c, k, float(cfg[k]))
        for k in ("min_observations", "max_per_frame", "max_reads"):
            if cfg.get(k) is not None:
                setattr(c, k, int(cfg[k]))
        for k in ("contrast_normalize", "record_unknown_plates", "store_crops"):
            if cfg.get(k) is not None:
                setattr(c, k, bool(cfg[k]))
        return c


@dataclass
class VehicleEntry:
    vehicle_id: str
    plate: str
    label: str = ""
    groups: list[str] = field(default_factory=list)
    active: bool = True


class VehicleIndex:
    def __init__(self, vehicles: list[VehicleEntry] | None = None) -> None:
        self._by_plate: dict[str, VehicleEntry] = {}
        for v in vehicles or []:
            if v.active and v.plate:
                self._by_plate[v.plate] = v

    def lookup(self, plate: str) -> VehicleEntry | None:
        return self._by_plate.get(plate)

    def __len__(self) -> int:
        return len(self._by_plate)


@dataclass
class TrackPlateState:
    track_id: int
    first_seen_t: float
    consensus: PlateConsensus
    last_attempt_t: float = -1e9
    plate_seen: bool = False
    last_quality: dict | None = None
    last_raw: str | None = None
    reads: int = 0
    usable: int = 0
    rejected: dict[str, int] = field(default_factory=dict)
    best_quality: float = 0.0
    best_frame: int | None = None
    best_crop: np.ndarray | None = None
    consensus_result: ConsensusResult | None = None
    plate: str | None = None
    raw: str | None = None
    parsed: ParsedPlate | None = None
    vehicle: VehicleEntry | None = None
    confidence: float | None = None
    status: str = STATUS_UNRESOLVED
    settled: bool = False
    resolved_at: float | None = None
    revalidate_at: float = 0.0
    disagreements: int = 0
    recognition_event_id: int | None = None
    history: deque = field(default_factory=lambda: deque(maxlen=8))


@dataclass
class PlateStepResult:
    events: list[dict]
    attempts: int
    plates: int


class PlateRecognitionPipeline:
    module = "plate"

    def __init__(self, stack: PlateStack, parser: PlateParser, vehicles: VehicleIndex | None = None, cfg: PlatePipelineConfig | None = None) -> None:
        self.stack = stack
        self.parser = parser
        self.vehicles = vehicles or VehicleIndex()
        self.cfg = cfg or PlatePipelineConfig()
        self.states: dict[int, TrackPlateState] = {}
        self.stats = {"attempts": 0, "plates_detected": 0, "usable": 0, "decisions": 0, "plates_read": 0, "registered": 0, "unknown": 0, "insufficient": 0, "plate_changed": 0, "detect_ms": 0.0, "ocr_ms": 0.0}

    # ------------------------------------------------------------- entity interface
    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        st = self.states.get(track_id)
        if st is None:
            return anonymous_entity(track_id, object_class)
        if st.plate is not None:
            veh = st.vehicle
            return EntityRef(
                "registered_vehicle" if veh else "recognized_plate", track_id, object_class, plate=st.plate,
                vehicle_id=veh.vehicle_id if veh else None, vehicle_label=veh.label if veh else None, groups=list(veh.groups) if veh else [],
                confidence=st.confidence, status=STATUS_RECOGNIZED, settled=True, resolved_at=st.resolved_at, recognition_event_id=st.recognition_event_id,
            )
        return anonymous_entity(track_id, object_class, status=st.status, settled=st.settled)

    def forget(self, track_id: int) -> None:
        self.states.pop(track_id, None)

    def overlay(self, track_id: int) -> dict | None:
        st = self.states.get(track_id)
        if st is None:
            return None
        d: dict = {"status": st.status}
        if st.plate:
            d["plate"] = st.plate
            d["confidence"] = round(st.confidence or 0.0, 3)
            if st.vehicle:
                d["vehicle"] = st.vehicle.label or st.vehicle.vehicle_id
                d["vehicle_id"] = st.vehicle.vehicle_id
        return d

    # ------------------------------------------------------------- main step
    def observe(self, frame: np.ndarray, tracks: list[Track], t: float, frame_index: int, wall_time: float | None = None) -> PlateStepResult:
        wall = wall_time or time.time()
        events: list[dict] = []
        candidates: list[tuple[int, float, Track]] = []
        for tr in tracks:
            if tr.class_name not in VEHICLE_CLASSES or tr.state != "tracked" or not tr.updated:
                continue
            if (tr.box[3] - tr.box[1]) < 2 * self.cfg.min_plate_px:
                continue
            st = self.states.get(tr.track_id)
            if st is None:
                st = self.states[tr.track_id] = TrackPlateState(tr.track_id, t, PlateConsensus(self.cfg.max_reads, self.cfg.min_char_confidence, self.cfg.consensus_agreement))
            if t - st.last_attempt_t < self.cfg.interval_s:
                continue
            if st.plate is not None and t < st.revalidate_at:
                continue
            candidates.append((0 if st.plate is None else 1, -(tr.box[3] - tr.box[1]), tr))
        candidates.sort(key=lambda c: (c[0], c[1]))
        attempts = plates = 0
        for _, _, tr in candidates[: self.cfg.max_per_frame]:
            st = self.states[tr.track_id]
            st.last_attempt_t = t
            attempts += 1
            self.stats["attempts"] += 1
            obs = self._observe_track(frame, tr, st, t, frame_index)
            if obs is not None:
                plates += 1
            events.extend(self._decide(st, t, frame_index, wall, tr.class_name))
        for tr in tracks:
            st = self.states.get(tr.track_id)
            if st is None or st.plate is not None or st.settled:
                continue
            if st.usable == 0 and t - st.first_seen_t >= self.cfg.decision_timeout_s:
                st.status, st.settled = STATUS_INSUFFICIENT, True
                self.stats["insufficient"] += 1
                st.history.append({"t": round(t, 2), "result": STATUS_INSUFFICIENT, "reason": "no readable plate"})
        return PlateStepResult(events, attempts, plates)

    def _observe_track(self, frame: np.ndarray, tr: Track, st: TrackPlateState, t: float, frame_index: int) -> PlateObservation | None:
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = tr.box
        w, h = x2 - x1, y2 - y1
        region = (max(0.0, x1 - 0.05 * w), max(0.0, y1 - 0.05 * h), min(float(fw), x2 + 0.05 * w), min(float(fh), y2 + 0.05 * h))
        xa, ya = int(region[0]), int(region[1])
        crop = frame[ya : int(np.ceil(region[3])), xa : int(np.ceil(region[2]))]
        if crop.size == 0 or crop.shape[0] < 16 or crop.shape[1] < 16:
            st.plate_seen = False
            return None
        t0 = time.perf_counter()
        dets = self.stack.detector.detect(crop)
        self.stats["detect_ms"] += (time.perf_counter() - t0) * 1000.0
        dets = [d for d in dets if d.score >= self.cfg.min_detection_score]
        if not dets:
            st.plate_seen = False
            st.last_quality = None
            return None
        det = dets[0]
        det.box = (det.box[0] + xa, det.box[1] + ya, det.box[2] + xa, det.box[3] + ya)
        st.plate_seen = True
        self.stats["plates_detected"] += 1
        pcrop = plate_crop(frame, det.box, margin=0.12)
        quality: QualityReport = assess_plate_quality(pcrop, det, self.cfg.min_plate_px)
        st.last_quality = quality.to_dict()
        st.reads += 1
        obs = PlateObservation(tr.track_id, frame_index, t, det, quality)
        if not quality.usable or pcrop is None:
            for r in quality.reasons or ["unusable"]:
                st.rejected[r] = st.rejected.get(r, 0) + 1
            return obs
        t1 = time.perf_counter()
        read = self.stack.ocr.read(prepare_for_ocr(pcrop, self.cfg.contrast_normalize))
        self.stats["ocr_ms"] += (time.perf_counter() - t1) * 1000.0
        if read is None or not read.chars:
            st.rejected["ocr_empty"] = st.rejected.get("ocr_empty", 0) + 1
            return obs
        obs.read = read
        st.usable += 1
        self.stats["usable"] += 1
        st.last_raw = read.masked(self.cfg.min_char_confidence)
        st.consensus.add(read, weight=quality.score, t=t)
        if quality.score > st.best_quality:
            st.best_quality, st.best_frame = quality.score, frame_index
            if self.cfg.store_crops:
                st.best_crop = pcrop.copy()
        return obs

    def _decide(self, st: TrackPlateState, t: float, frame_index: int, wall: float, object_class: str) -> list[dict]:
        if st.consensus.n < self.cfg.min_observations:
            return []
        res = st.consensus.result()
        st.consensus_result = res
        st.decisions = getattr(st, "decisions", 0) + 1
        self.stats["decisions"] += 1
        events: list[dict] = []
        if res.complete and res.confidence >= self.cfg.min_read_confidence:
            region_hint, _ = st.consensus.region()
            parsed, vehicle = self._parse_and_lookup(res.text, region_hint)
            normalized = parsed.normalized
            st.history.append({"t": round(t, 2), "frame": frame_index, "consensus": res.to_dict(), "normalized": normalized, "valid": parsed.valid, "format": parsed.format_id})
            if not parsed.valid:
                # a complete read that fits no enabled format: keep collecting, report unknown when it persists
                if st.consensus.n >= 3 * self.cfg.min_observations and st.plate is None:
                    st.status, st.settled = STATUS_UNKNOWN, True
                    self.stats["unknown"] += 1
                return events
            if st.plate is None:
                st.plate, st.raw, st.parsed, st.vehicle = normalized, res.text, parsed, vehicle
                st.confidence, st.status, st.settled, st.resolved_at = res.confidence, STATUS_RECOGNIZED, True, t
                st.disagreements = 0
                self.stats["plates_read"] += 1
                if vehicle:
                    self.stats["registered"] += 1
                if vehicle is not None or self.cfg.record_unknown_plates:
                    events.append(self._event("registered_vehicle" if vehicle else "plate_read", st, res, t, frame_index, wall, object_class))
            elif st.plate == normalized:
                st.confidence = max(st.confidence or 0.0, res.confidence)
                st.disagreements = 0
            else:
                st.disagreements += 1
                if st.disagreements >= 2:
                    previous = st.plate
                    st.plate, st.raw, st.parsed, st.vehicle = normalized, res.text, parsed, vehicle
                    st.confidence, st.resolved_at, st.disagreements = res.confidence, t, 0
                    self.stats["plate_changed"] += 1
                    if vehicle is not None or self.cfg.record_unknown_plates:
                        events.append(self._event("plate_changed", st, res, t, frame_index, wall, object_class, extra={"previous_plate": previous}))
            st.revalidate_at = t + self.cfg.revalidate_s
            st.consensus.clear()
        else:
            st.history.append({"t": round(t, 2), "frame": frame_index, "consensus": res.to_dict()})
            if st.plate is None and st.consensus.n >= 3 * self.cfg.min_observations:
                st.status, st.settled = STATUS_UNKNOWN, True
                self.stats["unknown"] += 1
        return events

    def _parse_and_lookup(self, text: str, region_hint: str | None) -> tuple[ParsedPlate, VehicleEntry | None]:
        """A plate that is registered exactly as read wins over any confusable
        repair a format might suggest; otherwise the format layer decides."""
        exact = self.parser.parse_exact(text, region_hint)
        vehicle = self.vehicles.lookup(exact.normalized) if exact.normalized else None
        if vehicle is not None:
            if not exact.valid:
                exact = ParsedPlate(text, exact.normalized, True, "registry", "Registered vehicle", None, region_hint, {}, 0)
            return exact, vehicle
        parsed = self.parser.parse(text, region_hint)
        return parsed, (self.vehicles.lookup(parsed.normalized) if parsed.valid else None)

    def _event(self, kind: str, st: TrackPlateState, res: ConsensusResult, t: float, frame_index: int, wall: float, object_class: str, extra: dict | None = None) -> dict:
        crop_jpeg = None
        if self.cfg.store_crops and st.best_crop is not None:
            ok, enc = cv2.imencode(".jpg", st.best_crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
            crop_jpeg = enc.tobytes() if ok else None
        parsed = st.parsed
        region, region_share = st.consensus.region() if st.consensus.n else (None, 0.0)
        return {
            "module": "plate",
            "kind": kind,
            "track_id": st.track_id,
            "object_class": object_class,
            "vehicle_id": st.vehicle.vehicle_id if st.vehicle else None,
            "vehicle_label": st.vehicle.label if st.vehicle else None,
            "plate_raw": st.raw,
            "plate_normalized": st.plate,
            "plate_format": parsed.format_id if parsed else None,
            "plate_fields": parsed.fields if parsed else {},
            "plate_country": parsed.country if parsed else None,
            "plate_region": (parsed.region if parsed else None) or region,
            "similarity": None,
            "confidence": round(res.confidence, 4),
            "status": STATUS_RECOGNIZED,
            "quality": round(st.best_quality, 3),
            "n_observations": st.reads,
            "usable_observations": st.usable,
            "best_frame_index": st.best_frame,
            "model_version": self.stack.model_version,
            "frame_index": frame_index,
            "media_time_s": round(t, 3),
            "wall_time": wall,
            "context": {"per_char": res.per_char, "substitutions": parsed.substitutions if parsed else 0, "region_share": round(region_share, 3), "rejected": dict(st.rejected), **(extra or {})},
            "crop_jpeg": crop_jpeg,
        }

    # ------------------------------------------------------------- diagnostics
    def diagnostics(self) -> dict:
        tracks = []
        for tid, st in self.states.items():
            cons = st.consensus_result.to_dict() if st.consensus_result else None
            tracks.append(
                {
                    "track_id": tid,
                    "plate_detected": st.plate_seen,
                    "quality": st.last_quality,
                    "raw_ocr": st.last_raw,
                    "reads": st.reads,
                    "usable": st.usable,
                    "rejected": dict(st.rejected),
                    "consensus": cons,
                    "normalized": st.plate,
                    "format": st.parsed.format_id if st.parsed else None,
                    "vehicle": (st.vehicle.label or st.vehicle.vehicle_id) if st.vehicle else None,
                    "vehicle_id": st.vehicle.vehicle_id if st.vehicle else None,
                    "result": st.status,
                    "confidence": round(st.confidence, 3) if st.confidence is not None else None,
                    "best_frame": st.best_frame,
                    "settled": st.settled,
                    "history": list(st.history),
                }
            )
        return {
            "module": "plate",
            "model": self.stack.describe(),
            "parser": self.parser.describe(),
            "vehicles": len(self.vehicles),
            "stats": {k: (round(v, 1) if isinstance(v, float) else v) for k, v in self.stats.items()},
            "tracks": tracks,
        }

    def describe(self) -> dict:
        return {"stack": self.stack.describe(), "parser": self.parser.describe(), "vehicles": len(self.vehicles), "config": self.cfg.__dict__}

    def close(self) -> None:
        self.stack.close()
