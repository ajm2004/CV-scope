"""Deterministic anomaly detection: meaningful change from a learned normal picture.

How a change becomes an anomaly
-------------------------------

1. **Normal picture.** At the start the assistant learns the scene for
   ``learn_s`` seconds: the per-pixel median of the frames (people passing
   during learning do not end up in it) and the per-pixel noise level. The
   normal picture then follows slow daylight drift (``adapt_minutes``), but
   never where something is currently different, so a change is not
   "forgotten" while it is being watched.
2. **Candidate variance.** Each analysis (``analysis_fps``, on a small copy of
   the frame) compares the frame with the normal picture in Lab colour space:
   brightness after correcting the global exposure, and colour. A pixel
   differs when it is ``k_sigma`` noise deviations *and* ``min_contrast``
   levels away from normal, or its colour changed clearly.
3. **Noise filtering.** Differences that keep the local texture (shadows,
   light patches, a lamp switched on: high local correlation, same colour)
   are dropped; specks are removed morphologically; blobs smaller than a
   fraction of ``min_area_pct`` are ignored (dust, insects, compression).
   A change that crept in over minutes (the sun moving) is recognised by
   comparing with the picture from 12 to 40 s earlier and is taken into the
   normal picture instead of raising an event.
4. **Temporal validation.** A zone becomes a candidate when enough of it
   differs (or a watched object class is inside it) and is confirmed when the
   evidence lasts ``persistence_s`` in at least 60 % of the analyses and the
   confidence reaches ``min_confidence``.
5. **Classification.** presence (a detected object of a watched class),
   motion (the change is moving), or - once still - appeared / disappeared /
   moved / changed, judged from the contours around the changed area and by
   matching what disappeared with what appeared.
6. **End.** The event ends when the zone looks normal again (``cleared``) or
   when a still change is accepted as the new normal after ``accept_after_s``.

Whole-picture events: when most of the picture changes at once the zone
logic is paused. If the structure of the picture survived it was the
lighting; if it did not, the camera was covered, blinded or moved. Either
way the normal picture is learned again.

This module only needs numpy and OpenCV; it knows nothing about CV-Scope's
pipeline, database or API, so other camera applications can use it as is.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

import cv2
import numpy as np

from pathscope.anomaly.config import (
    FRAME_ZONE_ID,
    AnomalySettings,
    AnomalyZoneSettings,
    ResolvedThresholds,
)
from pathscope.anomaly.describe import summarize
from pathscope.anomaly.subjects import SubjectBook

# Fixed parameters of the method (the configurable ones live in config.py)
HIT_RATIO = 0.6  # share of analyses that must show the change during the persistence time
CHROMA_MIN = 10.0  # Lab colour difference that counts as a colour change
TEXTURE_VAR = 4.0  # local variance above which a patch has texture (well above the blurred noise)
ILLUM_NCC = 0.85  # texture kept this well = a lighting difference, not an object
GLOBAL_FRACTION = 0.45  # this much of the picture changing at once = lighting or camera
GLOBAL_BRIGHTNESS = (0.65, 1.5)  # median brightness outside this ratio = the lights changed
GLOBAL_HOLD_S = 1.0
TRANSFER_BINS = 16  # bands of normal brightness for the exposure correction
TRANSFER_MIN_PIXELS = 30
TRANSFER_RESIDUAL = 6.0  # a band this far from the exposure line is a local change
# A changed region whose texture survived (same pattern, darker or brighter,
# same colour) is a shadow or a light patch
REGION_ILLUM_NCC = 0.7
REGION_TEXTURED_SHARE = 0.3
FAINT_VAR = 1.5
SUDDEN_MIN_AGE_S = 12.0  # compare with a picture at least this old ...
SUDDEN_FRACTION = 0.3  # ... a change is sudden when this much of it is new since then
HISTORY_STEP_S = 2.0
HISTORY_SPAN_S = 40.0
QUIET_REFRESH_S = 2.0  # how often the "before" picture of a quiet zone is renewed
AFTER_REFRESH_S = 1.0
STILL_MOVING_FRACTION = 0.08  # below this share of moving pixels a change counts as still


# ---------------------------------------------------------------------------- inputs
@dataclass(slots=True)
class ObservedObject:
    """A detected / tracked object handed to the assistant (pixel box in the frame)."""

    track_id: int
    class_name: str
    confidence: float
    box: tuple[float, float, float, float]


def observed_objects(tracks: Iterable | None) -> list[ObservedObject]:
    """Accepts CV-Scope tracks, dicts ({track_id|id, class_name|cls, confidence|conf, box}) or ObservedObject."""
    out: list[ObservedObject] = []
    for t in tracks or []:
        if isinstance(t, ObservedObject):
            out.append(t)
            continue
        if isinstance(t, dict):
            if t.get("state", "tracked") != "tracked":
                continue
            out.append(ObservedObject(int(t.get("track_id", t.get("id", 0)) or 0), str(t.get("class_name", t.get("cls", "object"))), float(t.get("confidence", t.get("conf", 0.0)) or 0.0), tuple(t["box"])))  # type: ignore[arg-type]
            continue
        if getattr(t, "state", "tracked") != "tracked":
            continue
        out.append(ObservedObject(int(t.track_id), str(t.class_name), float(t.confidence), tuple(t.box)))  # type: ignore[arg-type]
    return out


# ---------------------------------------------------------------------------- outputs
@dataclass
class AnomalyUpdate:
    """A confirmed anomaly (phase ``confirmed``) or its end (phase ``ended``)."""

    phase: str
    uid: str
    zone_id: str
    zone_name: str
    kind: str
    confidence: float
    area_pct: float
    bbox: list[float]  # normalized x1, y1, x2, y2 of the changed area
    started_t: float
    confirmed_t: float
    wall_started: float
    wall_confirmed: float
    ended_t: float | None = None
    wall_ended: float | None = None
    end_reason: str | None = None
    objects: list[dict] = field(default_factory=list)
    subjects: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    summary: str = ""
    zone: dict = field(default_factory=dict)  # validation, interpret_at, webhooks, record_clip, expected_state
    instant: bool = False  # whole-picture events have no duration
    # Evidence (not serialized): full-resolution BGR frames and the changed area
    frames: dict[str, np.ndarray] = field(default_factory=dict, repr=False)
    mask: np.ndarray | None = field(default=None, repr=False)  # analysis-size bool mask
    zone_polygon: list[tuple[float, float]] | None = None

    @property
    def duration_s(self) -> float | None:
        return None if self.ended_t is None else max(0.0, self.ended_t - self.started_t)

    def to_dict(self) -> dict:
        return {
            "phase": self.phase,
            "uid": self.uid,
            "zone_id": self.zone_id,
            "zone_name": self.zone_name,
            "kind": self.kind,
            "confidence": round(self.confidence, 3),
            "area_pct": round(self.area_pct, 3),
            "bbox": [round(v, 4) for v in self.bbox],
            "started_t": round(self.started_t, 3),
            "confirmed_t": round(self.confirmed_t, 3),
            "ended_t": None if self.ended_t is None else round(self.ended_t, 3),
            "wall_started": self.wall_started,
            "wall_confirmed": self.wall_confirmed,
            "wall_ended": self.wall_ended,
            "duration_s": None if self.duration_s is None else round(self.duration_s, 2),
            "end_reason": self.end_reason,
            "objects": self.objects,
            "subjects": self.subjects,
            "metrics": self.metrics,
            "summary": self.summary,
            "zone": self.zone,
            "instant": self.instant,
        }


# ---------------------------------------------------------------------------- change map
class ChangeMap:
    """Differences of one analysed frame from the normal picture (analysis size)."""

    def __init__(self, lab: np.ndarray, base: np.ndarray, sigma: np.ndarray, valid: np.ndarray, prev_l: np.ndarray | None) -> None:
        L = lab[..., 0]
        Lb = base[..., 0]
        # Exposure and lighting of the whole picture: a brightness transfer
        # curve from pixel correspondences. For each band of normal brightness
        # the median of the current brightness of the same pixels says how the
        # exposure moved that band (non-linear Lab lightness, automatic
        # exposure, a dimmed lamp). An object covering a minority of the
        # pixels of a band does not move its median, so it is not corrected away.
        self.Lc, self.gain = _brightness_transfer(L, Lb, valid)
        self.L = L
        self.Lb = Lb
        self.dL = np.abs(self.Lc - Lb)
        self.z = self.dL / sigma
        self.dC = np.hypot(lab[..., 1] - base[..., 1], lab[..., 2] - base[..., 2])
        k = (7, 7)
        mf = cv2.blur(self.Lc, k)
        mb = cv2.blur(Lb, k)
        vf = cv2.blur(self.Lc * self.Lc, k) - mf * mf
        vb = cv2.blur(Lb * Lb, k) - mb * mb
        cov = cv2.blur(self.Lc * Lb, k) - mf * mb
        self.ncc = cov / np.sqrt(np.maximum(vf, 1e-3) * np.maximum(vb, 1e-3))
        self.textured = (vf > TEXTURE_VAR) & (vb > TEXTURE_VAR)
        # Faint structure (above the blurred noise) is enough to judge a whole region
        self.structured = (vf > FAINT_VAR) & (vb > FAINT_VAR)
        # Same texture, same colour, different brightness: shadow, light patch, lamp
        self.illum_like = self.textured & (self.ncc > ILLUM_NCC) & (self.dC < CHROMA_MIN * 0.6)
        self.valid = valid
        self.motion_diff = np.abs(L - prev_l) if prev_l is not None else np.zeros_like(L)
        self._edges: tuple[np.ndarray, np.ndarray] | None = None

    def changed(self, th: ResolvedThresholds) -> np.ndarray:
        lum = (self.dL > th.min_contrast) & (self.z > th.k_sigma)
        chroma = self.dC > max(CHROMA_MIN, th.min_contrast * 0.6)
        return (lum | chroma) & ~self.illum_like & self.valid

    def moving(self, th: ResolvedThresholds) -> np.ndarray:
        return self.motion_diff > max(10.0, th.min_contrast * 0.7)

    @property
    def edges(self) -> tuple[np.ndarray, np.ndarray]:
        """Gradient magnitude now and in the normal picture."""
        if self._edges is None:
            def mag(img: np.ndarray) -> np.ndarray:
                gx = cv2.Sobel(img, cv2.CV_32F, 1, 0, ksize=3)
                gy = cv2.Sobel(img, cv2.CV_32F, 0, 1, ksize=3)
                return cv2.magnitude(gx, gy)

            self._edges = (mag(self.Lc), mag(self.Lb))
        return self._edges


class SceneModel:
    """The learned normal picture with its noise level."""

    def __init__(self, frame_w: int, frame_h: int, settings: AnomalySettings, exclude: np.ndarray | None = None) -> None:
        self.frame_w, self.frame_h = frame_w, frame_h
        self.w = min(settings.working_width, frame_w)
        self.h = max(8, round(frame_h * self.w / frame_w))
        self.learn_s = settings.learn_s
        self.tau_s = settings.adapt_minutes * 60.0
        self.valid = ~exclude if exclude is not None else np.ones((self.h, self.w), bool)
        self.base: np.ndarray | None = None
        self.sigma: np.ndarray | None = None
        self.prev_l: np.ndarray | None = None
        self.history: deque[tuple[float, np.ndarray]] = deque()
        self.learning = True
        self._samples: list[np.ndarray] = []
        self._learn_start: float | None = None
        self._last_sample = -1e9
        self._last_adapt: float | None = None

    def prepare(self, frame: np.ndarray) -> np.ndarray:
        small = cv2.resize(frame, (self.w, self.h), interpolation=cv2.INTER_AREA) if frame.shape[1] != self.w else frame
        if small.ndim == 2:
            small = cv2.cvtColor(small, cv2.COLOR_GRAY2BGR)
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
        return cv2.GaussianBlur(lab, (5, 5), 1.2)

    def relearn(self) -> None:
        self.learning = True
        self._samples.clear()
        self._learn_start = None
        self.history.clear()

    def learn(self, lab: np.ndarray, t: float) -> bool:
        """Collect frames; True once the normal picture is ready."""
        if self._learn_start is None:
            self._learn_start = t
        if t - self._last_sample >= min(0.5, self.learn_s / 8.0):
            self._samples.append(lab)
            self._last_sample = t
            if len(self._samples) > 24:
                self._samples = self._samples[::2]
        if t - self._learn_start < self.learn_s or len(self._samples) < 5:
            return False
        stack = np.stack(self._samples)
        self.base = np.median(stack, axis=0).astype(np.float32)
        mad = np.median(np.abs(stack[..., 0] - self.base[..., 0]), axis=0) * 1.4826
        self.sigma = np.clip(cv2.GaussianBlur(mad.astype(np.float32), (5, 5), 1.5), 1.5, 25.0)
        self.learning = False
        self._samples.clear()
        self.prev_l = lab[..., 0].copy()
        self._last_adapt = t
        return True

    def compare(self, lab: np.ndarray) -> ChangeMap:
        assert self.base is not None and self.sigma is not None
        return ChangeMap(lab, self.base, self.sigma, self.valid, self.prev_l)

    def after_analysis(self, lab: np.ndarray, t: float, freeze: np.ndarray) -> None:
        """Follow slow drift outside of what is currently different; remember the picture."""
        assert self.base is not None and self.sigma is not None
        dt = 0.0 if self._last_adapt is None else max(0.0, t - self._last_adapt)
        self._last_adapt = t
        alpha = min(1.0, dt / max(self.tau_s, 1.0))
        if alpha > 0:
            keep = ~freeze
            diff = lab - self.base
            self.base[keep] += alpha * diff[keep]
            d2 = diff[..., 0] ** 2
            s2 = self.sigma**2
            s2[keep] += (alpha * 0.5) * (d2[keep] - s2[keep])
            self.sigma = np.clip(np.sqrt(np.maximum(s2, 0.0)), 1.5, 25.0).astype(np.float32)
        self.prev_l = lab[..., 0].copy()
        if not self.history or t - self.history[-1][0] >= HISTORY_STEP_S:
            self.history.append((t, lab[..., 0].copy()))
        while self.history and t - self.history[0][0] > HISTORY_SPAN_S:
            self.history.popleft()

    def absorb(self, lab: np.ndarray, mask: np.ndarray) -> None:
        """Take the current picture as normal where ``mask`` is set."""
        if self.base is None or not mask.any():
            return
        grown = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        self.base[grown] = lab[grown]

    def recent_reference(self, t: float) -> np.ndarray | None:
        """The analysed brightness of 12 to 40 s ago, when the history reaches back that far."""
        old = [h for h in self.history if t - h[0] >= SUDDEN_MIN_AGE_S]
        return old[-1][1] if old else None


# ---------------------------------------------------------------------------- zones
@dataclass
class _Episode:
    uid: str
    onset_t: float
    onset_wall: float
    last_signal_t: float
    analyses: int = 0
    hits: int = 0
    peak_area: float = 0.0
    union: np.ndarray | None = None
    last_mask: np.ndarray | None = None
    before: np.ndarray | None = None
    event_frame: np.ndarray | None = None
    after: np.ndarray | None = None
    after_t: float = -1e9
    objects: dict[int, dict] = field(default_factory=dict)
    boxes: dict[int, tuple[float, float, float, float]] = field(default_factory=dict)  # last normalized box per track
    presence_seen: bool = False
    moving_seen: bool = False
    still_since: float | None = None
    static_kind: str | None = None
    confirmed_t: float = 0.0
    confirmed_wall: float = 0.0
    kind: str = "changed"
    confidence: float = 0.0
    metrics: dict = field(default_factory=dict)


class ZoneMonitor:
    """State machine of one watched zone: idle -> candidate -> active -> idle."""

    def __init__(self, cfg: AnomalyZoneSettings, polygon: list[tuple[float, float]] | None, size: tuple[int, int], valid: np.ndarray) -> None:
        self.cfg = cfg
        self.th = cfg.thresholds()
        self.polygon = polygon
        w, h = size
        mask = np.zeros((h, w), np.uint8)
        if polygon is None:
            mask[:] = 1
        else:
            pts = np.array([[round(x * w), round(y * h)] for x, y in polygon], np.int32)
            cv2.fillPoly(mask, [pts], 1)
        self.mask = (mask > 0) & valid
        self.area_px = max(1, int(self.mask.sum()))
        self.min_area_px = self.area_px * self.th.min_area_pct / 100.0
        self.min_blob_px = max(4.0, 0.2 * self.min_area_px)
        self.pixel_kinds = bool({"motion", "appeared", "disappeared", "moved", "changed"} & set(cfg.detect))
        self.state = "idle"
        self.ep: _Episode | None = None
        self.cooldown_until = -1e9
        self.quiet_frame: np.ndarray | None = None
        self.quiet_t = -1e9
        self.filtered = 0  # candidates that did not last or were too weak
        self.drift_absorbed = 0
        self.illumination_regions = 0  # changed regions dropped as shadow or light patch
        self.confirmed = 0
        self.frame_size = (1, 1)

    @property
    def gap_s(self) -> float:
        return max(1.0, 0.5 * self.th.persistence_s)

    @property
    def clear_s(self) -> float:
        return max(3.0, self.th.persistence_s)

    # ------------------------------------------------------------------ measure
    def contains(self, obj: ObservedObject) -> bool:
        if self.polygon is None:
            return True
        fw, fh = self.frame_size
        x1, y1, x2, y2 = obj.box
        poly = np.array(self.polygon, np.float32)
        for px, py in (((x1 + x2) / 2 / fw, y2 / fh), ((x1 + x2) / 2 / fw, (y1 + y2) / 2 / fh)):
            if cv2.pointPolygonTest(poly, (float(px), float(py)), False) >= 0:
                return True
        return False

    def measure(self, cm: ChangeMap, objects: list[ObservedObject]) -> dict:
        present = []
        if "presence" in self.cfg.detect:
            wanted = set(self.cfg.presence_classes)
            present = [o for o in objects if (not wanted or o.class_name in wanted) and self.contains(o)]
        mask = np.zeros_like(self.mask)
        area = 0.0
        comps: list[np.ndarray] = []
        if self.pixel_kinds:
            raw = (cm.changed(self.th) & self.mask).astype(np.uint8)
            if raw.any():
                raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
                raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
                raw &= self.mask.astype(np.uint8)
                n, labels, stats, _ = cv2.connectedComponentsWithStats(raw, connectivity=8)
                for i in range(1, n):
                    if stats[i, cv2.CC_STAT_AREA] >= self.min_blob_px:
                        comp = labels == i
                        if illumination_region(cm, comp):
                            self.illumination_regions += 1
                            continue
                        comps.append(comp)
                        mask |= comp
                area = float(mask.sum())
        area_pct = 100.0 * area / self.area_px
        inside = [o for o in objects if self.contains(o)]  # every tracked object in the area, for the description
        m = {"present": present, "inside": inside, "mask": mask, "comps": comps, "area_pct": area_pct, "raw_signal": area >= self.min_area_px and area > 0}
        if area > 0:
            moving = cm.moving(self.th)
            m["moving_frac"] = float(moving[mask].mean())
            m["mean_z"] = float(np.minimum(cm.z[mask], 50.0).mean())
            m["struct_frac"] = float(((cm.textured & (cm.ncc < 0.5)) | (cm.dC > CHROMA_MIN))[mask].mean())
        else:
            m["moving_frac"] = 0.0
            m["mean_z"] = 0.0
            m["struct_frac"] = 0.0
        m["signal"] = m["raw_signal"] or bool(present)
        return m

    # ------------------------------------------------------------------ judge
    def confidence(self, ep: _Episode, m: dict, gain: float) -> float:
        th = self.th
        area = min(1.0, m["area_pct"] / (th.min_area_pct * 3.0)) if m["area_pct"] > 0 else 0.0
        persist = ep.hits / max(1, ep.analyses)
        magnitude = min(1.0, m["mean_z"] / (2.0 * th.k_sigma)) if m["mean_z"] else 0.0
        conf = 0.35 * area + 0.25 * persist + 0.2 * magnitude + 0.2 * m["struct_frac"]
        if abs(gain - 1.0) > 0.25:
            conf *= 0.8  # exposure moved a lot: a little less sure
        if m["present"]:
            best = max(o.confidence for o in m["present"])
            conf = max(conf, 0.6 + 0.4 * best)
        return float(min(1.0, conf))

    @staticmethod
    def classify_static(cm: ChangeMap, comps: list[np.ndarray]) -> tuple[str, dict]:
        """appeared / disappeared / moved / changed for a still change."""
        if not comps:
            return "changed", {}
        e_now, e_base = cm.edges
        k3 = np.ones((3, 3), np.uint8)
        verdicts: list[tuple[str, np.ndarray, float]] = []
        for comp in comps:
            c8 = comp.astype(np.uint8)
            ring = (cv2.dilate(c8, k3, iterations=2) > 0) & ~(cv2.erode(c8, k3, iterations=1) > 0)
            rn, rb = float(e_now[ring].mean()), float(e_base[ring].mean())
            inn, inb = float(e_now[comp].mean()), float(e_base[comp].mean())
            now, base = 0.7 * rn + 0.3 * inn, 0.7 * rb + 0.3 * inb
            if now > 1.2 * base + 2.0:
                verdict = "appeared"
            elif base > 1.2 * now + 2.0:
                verdict = "disappeared"
            else:
                verdict = "changed"
            verdicts.append((verdict, comp, float(comp.sum())))
        detail = {"components": [{"verdict": v, "area_px": int(a)} for v, _, a in verdicts]}
        appeared = [v for v in verdicts if v[0] == "appeared"]
        gone = [v for v in verdicts if v[0] == "disappeared"]
        for _, ca, aa in appeared:
            for _, cd, ad in gone:
                if not 0.4 <= aa / max(ad, 1.0) <= 2.5:
                    continue
                score = _patch_match(cm.Lb, cd, cm.Lc, ca)
                if score > 0.4:
                    detail["moved_match"] = round(score, 3)
                    return "moved", detail
        total = sum(a for _, _, a in verdicts)
        by_kind: dict[str, float] = {}
        for v, _, a in verdicts:
            by_kind[v] = by_kind.get(v, 0.0) + a
        kind, share = max(by_kind.items(), key=lambda kv: kv[1])
        if kind != "changed" and share < 0.7 * total:
            kind = "changed"
        return kind, detail

    def kind_now(self, ep: _Episode, cm: ChangeMap, m: dict) -> str:
        if m["present"] or (ep.presence_seen and self.state == "active"):
            return "presence"
        if m["moving_frac"] >= 0.25:
            return "motion"
        if ep.static_kind:
            return ep.static_kind
        kind, detail = self.classify_static(cm, m["comps"])
        ep.metrics["static"] = detail
        return kind

    # ------------------------------------------------------------------ step
    def step(self, cm: ChangeMap, m: dict, t: float, wall: float, snapshot: Callable[[], np.ndarray], sudden: Callable[[np.ndarray], bool], absorb: Callable[[np.ndarray], None], subjects: SubjectBook) -> list[AnomalyUpdate]:
        if self.state == "idle":
            if not m["signal"]:
                if t - self.quiet_t >= QUIET_REFRESH_S:
                    self.quiet_frame = snapshot()
                    self.quiet_t = t
                return []
            if t < self.cooldown_until:
                return []
            if not m["present"] and not sudden(m["mask"]):
                absorb(m["mask"])  # crept in slowly: daylight, not an event
                self.drift_absorbed += 1
                return []
            self.state = "candidate"
            self.ep = _Episode(uid=uuid.uuid4().hex[:16], onset_t=t, onset_wall=wall, last_signal_t=t, before=self.quiet_frame)
        ep = self.ep
        assert ep is not None
        ep.analyses += 1
        if m["signal"]:
            ep.hits += 1
            ep.last_signal_t = t
            ep.last_mask = m["mask"]
            ep.union = m["mask"].copy() if ep.union is None else (ep.union | m["mask"])
            fw, fh = self.frame_size
            for o in m["inside"]:
                ep.boxes[o.track_id] = (o.box[0] / fw, o.box[1] / fh, o.box[2] / fw, o.box[3] / fh)
                ep.objects[o.track_id] = {"track_id": o.track_id, "object_class": o.class_name, "confidence": round(max(o.confidence, ep.objects.get(o.track_id, {}).get("confidence", 0.0)), 3)}
            if m["present"]:
                ep.presence_seen = True
            if m["moving_frac"] >= 0.25:
                ep.moving_seen = True
            if m["area_pct"] >= ep.peak_area:
                ep.peak_area = m["area_pct"]
            if not m["present"] and m["area_pct"] > 0 and m["moving_frac"] < STILL_MOVING_FRACTION:
                if ep.still_since is None:
                    ep.still_since = t
                    ep.static_kind = None
                if ep.static_kind is None or t - ep.after_t >= AFTER_REFRESH_S:
                    ep.static_kind, ep.metrics["static"] = self.classify_static(cm, m["comps"])
            else:
                ep.still_since = None
        if self.state == "candidate":
            return self._candidate(ep, cm, m, t, wall, snapshot, subjects)
        return self._active(ep, cm, m, t, wall, snapshot, absorb, subjects)

    def _candidate(self, ep: _Episode, cm: ChangeMap, m: dict, t: float, wall: float, snapshot, subjects: SubjectBook) -> list[AnomalyUpdate]:
        if not m["signal"]:
            if t - ep.last_signal_t > self.gap_s:
                self._reset(filtered=True)
            return []
        if t - ep.onset_t < self.th.persistence_s or ep.hits / max(1, ep.analyses) < HIT_RATIO:
            return []
        conf = self.confidence(ep, m, cm.gain)
        kind = self.kind_now(ep, cm, m)
        if conf < self.th.min_confidence or kind not in self.cfg.detect:
            if t - ep.onset_t > 3.0 * self.th.persistence_s + 30.0:
                self._reset(filtered=True)
            return []
        self.state = "active"
        self.confirmed += 1
        ep.kind, ep.confidence = kind, conf
        ep.confirmed_t, ep.confirmed_wall = t, wall
        ep.event_frame = snapshot()
        ep.after, ep.after_t = ep.event_frame, t
        ep.metrics.update(self._metrics(ep, m, cm))
        upd = self._update("confirmed", ep, m["mask"], subjects)
        upd.frames = {k: v for k, v in (("before", ep.before), ("event", ep.event_frame)) if v is not None}
        return [upd]

    def _active(self, ep: _Episode, cm: ChangeMap, m: dict, t: float, wall: float, snapshot, absorb, subjects: SubjectBook) -> list[AnomalyUpdate]:
        if m["signal"]:
            if t - ep.after_t >= AFTER_REFRESH_S:
                ep.after, ep.after_t = snapshot(), t
            ep.confidence = max(ep.confidence, self.confidence(ep, m, cm.gain))
            accept = self.cfg.accept_after_s
            if accept > 0 and ep.still_since is not None and t - ep.still_since >= accept:
                absorb(ep.union if ep.union is not None else m["mask"])
                return [self._end(ep, t, wall, "accepted", subjects)]
            return []
        if t - ep.last_signal_t >= self.clear_s:
            return [self._end(ep, ep.last_signal_t, wall - (t - ep.last_signal_t), "cleared", subjects)]
        return []

    def _end(self, ep: _Episode, t: float, wall: float, reason: str, subjects: SubjectBook) -> AnomalyUpdate:
        if ep.presence_seen:
            ep.kind = "presence"
        elif ep.static_kind and ep.still_since is not None:
            ep.kind = ep.static_kind
        elif ep.moving_seen and ep.kind not in ("appeared", "disappeared", "moved", "changed"):
            ep.kind = "motion"
        ep.metrics["peak_area_pct"] = round(ep.peak_area, 3)
        upd = self._update("ended", ep, ep.last_mask if ep.last_mask is not None else ep.union, subjects)
        upd.ended_t, upd.wall_ended, upd.end_reason = t, wall, reason
        upd.area_pct = max(upd.area_pct, ep.peak_area)  # the largest extent, not the last trace
        upd.summary = summarize(upd)
        if ep.after is not None:
            upd.frames = {"after": ep.after}
        self._reset(filtered=False)
        self.cooldown_until = t + self.cfg.cooldown_s
        return upd

    def force_end(self, t: float, wall: float, reason: str, subjects: SubjectBook) -> list[AnomalyUpdate]:
        if self.state == "active" and self.ep is not None:
            return [self._end(self.ep, t, wall, reason, subjects)]
        self._reset(filtered=self.state == "candidate")
        return []

    def _reset(self, filtered: bool) -> None:
        if filtered:
            self.filtered += 1
        self.state = "idle"
        self.ep = None

    def _metrics(self, ep: _Episode, m: dict, cm: ChangeMap) -> dict:
        return {
            "area_pct": round(m["area_pct"], 3),
            "mean_z": round(m["mean_z"], 2),
            "struct_frac": round(m["struct_frac"], 3),
            "moving_frac": round(m["moving_frac"], 3),
            "exposure_gain": round(cm.gain, 3),
            "hit_ratio": round(ep.hits / max(1, ep.analyses), 3),
            "components": len(m["comps"]),
            "thresholds": self.th.model_dump(),
        }

    def _update(self, phase: str, ep: _Episode, mask: np.ndarray | None, subjects: SubjectBook) -> AnomalyUpdate:
        h, w = self.mask.shape
        area_mask = mask if mask is not None and mask.any() else (ep.union if ep.union is not None else self.mask)
        bbox = [0.0, 0.0, 1.0, 1.0]
        if area_mask is not None and area_mask.any():
            ys, xs = np.nonzero(area_mask)
            bbox = [xs.min() / w, ys.min() / h, (xs.max() + 1) / w, (ys.max() + 1) / h]
        elif ep.boxes:  # presence without a pixel change (a zone watching presence only): where the objects are
            bs = list(ep.boxes.values())
            bbox = [max(0.0, min(b[0] for b in bs)), max(0.0, min(b[1] for b in bs)), min(1.0, max(b[2] for b in bs)), min(1.0, max(b[3] for b in bs))]
        objects = sorted(ep.objects.values(), key=lambda o: o["track_id"])
        upd = AnomalyUpdate(
            phase=phase, uid=ep.uid, zone_id=self.cfg.id, zone_name=self.cfg.name or self.cfg.id, kind=ep.kind,
            confidence=ep.confidence, area_pct=100.0 * float(area_mask.sum()) / self.area_px if area_mask is not None else 0.0,
            bbox=bbox, started_t=ep.onset_t, confirmed_t=ep.confirmed_t, wall_started=ep.onset_wall, wall_confirmed=ep.confirmed_wall,
            objects=objects, subjects=subjects.describe(objects), metrics=dict(ep.metrics),
            zone={"validation": self.cfg.validation, "interpret_at": self.cfg.effective_interpret_at, "webhooks": list(self.cfg.webhooks), "record_clip": self.cfg.record_clip, "expected_state": self.cfg.expected_state},
            mask=area_mask, zone_polygon=self.polygon,
        )
        upd.summary = summarize(upd)
        return upd


def _brightness_transfer(L: np.ndarray, Lb: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, float]:
    """Map current brightness onto the normal picture's scale; returns (mapped, brightness ratio).

    Scaling the light by k changes Lab lightness almost affinely
    (L' = k^(1/3) (L + 16) - 16), so an exposure or lamp change is a straight
    line between normal and current brightness. The line is fitted to the
    median current brightness of each band of normal brightness, weighted by
    the band's size; bands that do not follow the line (a sun patch, an
    object) are dropped and the line fitted again, so a local change never
    bends the correction of the rest of the picture.
    """
    if valid.sum() < 100:
        return L, 1.0
    cur, base = L[valid], Lb[valid]
    ratio = float(np.clip((np.median(cur) + 1.0) / (np.median(base) + 1.0), 0.05, 20.0))
    bins = np.minimum((base * (TRANSFER_BINS / 256.0)).astype(np.int32), TRANSFER_BINS - 1)
    xs, ys, ws = [], [], []
    for b in range(TRANSFER_BINS):
        sel = bins == b
        n = int(sel.sum())
        if n >= TRANSFER_MIN_PIXELS:
            xs.append(float(np.median(base[sel])))
            ys.append(float(np.median(cur[sel])))
            ws.append(float(n))
    if not xs:
        return L, ratio
    x, y, w = np.array(xs), np.array(ys), np.array(ws)
    keep = np.ones(len(x), bool)
    a, b = 1.0, float(np.average(y - x, weights=w))
    for _ in range(3):
        if keep.sum() >= 2 and np.ptp(x[keep]) > 10.0:
            a, b = np.polyfit(x[keep], y[keep], 1, w=np.sqrt(w[keep]))
            a = float(np.clip(a, 0.3, 3.0))
            b = float(np.average(y[keep] - a * x[keep], weights=w[keep]))
        elif keep.any():
            a, b = 1.0, float(np.average(y[keep] - x[keep], weights=w[keep]))
        resid = np.abs(y - (a * x + b))
        new_keep = resid <= max(TRANSFER_RESIDUAL, 2.5 * float(np.median(resid[keep])) if keep.any() else TRANSFER_RESIDUAL)
        if (new_keep == keep).all() or not new_keep.any():
            break
        keep = new_keep
    return ((L - b) / a).astype(np.float32), ratio


def illumination_region(cm: ChangeMap, comp: np.ndarray) -> bool:
    """The region kept its texture and colour and only got darker or brighter."""
    tex = comp & cm.structured
    if tex.sum() < REGION_TEXTURED_SHARE * comp.sum():
        return False  # too flat to tell: treated as a real change
    if float(np.median(cm.ncc[tex])) < REGION_ILLUM_NCC:
        return False
    return float(np.median(cm.dC[comp])) < CHROMA_MIN * 0.8


def _patch_match(img_a: np.ndarray, mask_a: np.ndarray, img_b: np.ndarray, mask_b: np.ndarray) -> float:
    """Normalized correlation of the bounding patches of two regions."""
    def patch(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
        ys, xs = np.nonzero(mask)
        return img[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]

    a, b = patch(img_a, mask_a), patch(img_b, mask_b)
    if a.size < 9 or b.size < 9:
        return 0.0
    b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    a = a - a.mean()
    b = b - b.mean()
    den = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-6 else 0.0


# ---------------------------------------------------------------------------- assistant
class AnomalyAssistant:
    """Watch one camera for meaningful change.

    ``zones`` maps each configured zone id to its polygon (normalized points);
    the whole-picture zone (id ``frame``) needs none. ``ignore`` polygons are
    never watched. Feed every frame (or every processed frame) to ``observe``;
    it analyses at ``analysis_fps`` and returns confirmed and ended anomalies.
    """

    def __init__(self, settings: AnomalySettings, frame_size: tuple[int, int], zones: dict[str, list[tuple[float, float]]] | None = None, ignore: list[list[tuple[float, float]]] | None = None) -> None:
        self.settings = settings
        self.frame_w, self.frame_h = frame_size
        exclude = None
        w = min(settings.working_width, self.frame_w)
        h = max(8, round(self.frame_h * w / self.frame_w))
        if ignore and settings.use_ignore_regions:
            ex = np.zeros((h, w), np.uint8)
            for poly in ignore:
                cv2.fillPoly(ex, [np.array([[round(x * w), round(y * h)] for x, y in poly], np.int32)], 1)
            exclude = ex > 0
        self.model = SceneModel(self.frame_w, self.frame_h, settings, exclude)
        self.zones: list[ZoneMonitor] = []
        polys = zones or {}
        for z in settings.zones:
            if not z.enabled:
                continue
            if z.id != FRAME_ZONE_ID and z.id not in polys:
                continue  # the zone was removed from the scene
            zm = ZoneMonitor(z, None if z.id == FRAME_ZONE_ID else polys[z.id], (self.model.w, self.model.h), self.model.valid)
            zm.frame_size = (self.frame_w, self.frame_h)
            self.zones.append(zm)
        self.subjects = SubjectBook()
        self._next_due: float | None = None
        self._global_since: float | None = None
        self._last_t = 0.0
        self._last_wall = time.time()
        self.stats = {"analyses": 0, "learned": 0, "confirmed": 0, "global_events": 0}
        self.analysis_ms = 0.0

    # ------------------------------------------------------------------ public
    @property
    def state(self) -> str:
        return "learning" if self.model.learning else "watching"

    def due(self, t: float) -> bool:
        interval = 1.0 / self.settings.analysis_fps
        if self._next_due is None or t >= self._next_due - 0.2 * interval:
            self._next_due = t + interval if self._next_due is None or t - self._next_due > interval else self._next_due + interval
            return True
        return False

    def observe(self, frame: np.ndarray, t: float, wall_time: float | None = None, objects: Iterable | None = None, resolver=None) -> list[AnomalyUpdate]:
        """Analyse ``frame`` (BGR, full size) taken at media time ``t`` when an analysis is due."""
        if not self.zones or not self.due(t):
            return []
        t0 = time.perf_counter()
        wall = wall_time if wall_time is not None else time.time()
        self._last_t, self._last_wall = t, wall
        self.subjects.resolver = resolver if self.settings.recognition else None
        lab = self.model.prepare(frame)
        self.stats["analyses"] += 1
        if self.model.learning:
            if self.model.learn(lab, t):
                self.stats["learned"] += 1
                for z in self.zones:
                    z.quiet_frame, z.quiet_t = frame.copy(), t
            self.analysis_ms = (time.perf_counter() - t0) * 1000.0
            return []
        cm = self.model.compare(lab)
        cached: list[np.ndarray] = []

        def snapshot() -> np.ndarray:
            if not cached:
                cached.append(frame.copy())
            return cached[0]

        out = self._global(cm, t, wall, snapshot)
        if out is not None:
            self.analysis_ms = (time.perf_counter() - t0) * 1000.0
            return out
        objs = observed_objects(objects)
        freeze = np.zeros((self.model.h, self.model.w), bool)
        reference = self.model.recent_reference(t)

        def sudden(mask: np.ndarray) -> bool:
            if reference is None or not mask.any():
                return True
            sel = mask & (reference > 8.0)
            if not sel.any():
                return True
            g = float(np.clip(np.median(cm.L[sel] / reference[sel]), 0.4, 2.5))
            new = np.abs(cm.L / g - reference) > 12.0
            return float(new[mask].mean()) >= SUDDEN_FRACTION

        def absorb(mask: np.ndarray) -> None:
            self.model.absorb(lab, mask)

        updates: list[AnomalyUpdate] = []
        for z in self.zones:
            m = z.measure(cm, objs)
            freeze |= m["mask"]
            if z.ep is not None and z.ep.union is not None:
                freeze |= z.ep.union
            updates.extend(z.step(cm, m, t, wall, snapshot, sudden, absorb, self.subjects))
        self.stats["confirmed"] += sum(1 for u in updates if u.phase == "confirmed")
        grown = cv2.dilate(freeze.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
        self.model.after_analysis(lab, t, grown)
        self.analysis_ms = (time.perf_counter() - t0) * 1000.0
        return updates

    def rebaseline(self, zone_id: str | None = None, frame: np.ndarray | None = None) -> None:
        """Take the current picture as normal: for one zone (needs ``frame``) or everything (learn again)."""
        if zone_id is None or frame is None or self.model.learning:
            for z in self.zones:
                z.force_end(self._last_t, self._last_wall, "rebaselined", self.subjects)
            self.model.relearn()
            return
        for z in self.zones:
            if z.cfg.id == zone_id:
                self.model.absorb(self.model.prepare(frame), z.mask)
                z._reset(filtered=False)

    def finish(self, t: float | None = None, wall: float | None = None, reason: str = "run_ended") -> list[AnomalyUpdate]:
        """End every open anomaly (at the end of a run)."""
        t = self._last_t if t is None else t
        wall = self._last_wall if wall is None else wall
        out: list[AnomalyUpdate] = []
        for z in self.zones:
            out.extend(z.force_end(t, wall, reason, self.subjects))
        return out

    def status(self) -> dict:
        return {
            "state": self.state,
            "analysis_ms": round(self.analysis_ms, 2),
            "zones": [
                {"id": z.cfg.id, "name": z.cfg.name or z.cfg.id, "state": z.state, "confirmed": z.confirmed, "filtered": z.filtered, "drift_absorbed": z.drift_absorbed, "illumination_regions": z.illumination_regions}
                for z in self.zones
            ],
            **self.stats,
        }

    # ------------------------------------------------------------------ whole picture
    def _global(self, cm: ChangeMap, t: float, wall: float, snapshot) -> list[AnomalyUpdate] | None:
        """Lighting switched or camera covered/moved: pause zones and learn again."""
        valid = cm.valid
        changed = (((cm.dL > 20.0) & (cm.z > 3.5)) | (cm.dC > 12.0)) & ~cm.illum_like & valid
        frac = float(changed[valid].mean()) if valid.any() else 0.0
        bright = not (GLOBAL_BRIGHTNESS[0] <= cm.gain <= GLOBAL_BRIGHTNESS[1])
        if frac < GLOBAL_FRACTION and not bright:
            self._global_since = None
            return None
        if self._global_since is None:
            self._global_since = t
        if t - self._global_since < GLOBAL_HOLD_S:
            return []  # wait: zones are not judged while most of the picture changes
        self._global_since = None
        tex = cm.textured & valid
        structure = float(np.median(cm.ncc[tex])) if tex.sum() > 50 else 0.0
        blank = float(cm.L[valid].std()) < 6.0 if valid.any() else False
        kind = "tamper" if blank or structure < 0.35 else "lighting"
        out: list[AnomalyUpdate] = []
        for z in self.zones:
            out.extend(z.force_end(t, wall, "view_changed", self.subjects))
        before = next((z.quiet_frame for z in self.zones if z.quiet_frame is not None), None)
        self.model.relearn()
        self.stats["global_events"] += 1
        report = self.settings.tamper_events if kind == "tamper" else self.settings.lighting_events
        if report:
            upd = AnomalyUpdate(
                phase="confirmed", uid=uuid.uuid4().hex[:16], zone_id=FRAME_ZONE_ID, zone_name="Whole picture", kind=kind,
                confidence=min(1.0, 0.5 + frac / 2.0), area_pct=100.0 * frac, bbox=[0.0, 0.0, 1.0, 1.0], started_t=t - GLOBAL_HOLD_S,
                confirmed_t=t, wall_started=wall - GLOBAL_HOLD_S, wall_confirmed=wall, instant=True,
                metrics={"changed_fraction": round(frac, 3), "structure_kept": round(structure, 3), "exposure_gain": round(cm.gain, 3), "blank": blank},
                zone={"validation": "deterministic", "interpret_at": "confirm", "webhooks": [], "record_clip": True, "expected_state": ""},
                mask=changed,
            )
            upd.summary = summarize(upd)
            upd.frames = {k: v for k, v in (("before", before), ("event", snapshot())) if v is not None}
            out.append(upd)
        return out
