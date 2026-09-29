"""Synthetic scenes for the relationship engine tests.

A 1000 x 1000 px frame with a scale calibration of 0.05 m per pixel
(1 m = 20 px = 0.02 of the frame width). Objects are given in metres on the
ground; people are 20 px wide boxes, vehicles 80 px (4 m) wide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pathscope.domain.entities import STATUS_RECOGNIZED, EntityRef, anonymous_entity
from pathscope.domain.scene import SceneDocument
from pathscope.relationships.engine import EngineContext, RelationEngine
from pathscope.relationships.rules import (
    CompiledRule,
    RelationExperimentSettings,
    RelationRuleDefinition,
)
from pathscope.spatial.engine import Interaction
from pathscope.vision.types import Track

W = H = 1000
PX_PER_M = 20.0


def scene(calibrated: bool = True, objects: list[dict] | None = None, routes: list[dict] | None = None) -> SceneDocument:
    doc: dict = {"frame_width": W, "frame_height": H, "objects": objects or [], "routes": routes or []}
    if calibrated:
        doc["calibration"] = {"unit": "m", "known_distance": {"a": {"x": 0.0, "y": 0.5}, "b": {"x": 1.0, "y": 0.5}, "distance": W / PX_PER_M}}
    return SceneDocument.model_validate(doc)


def zone(zid: str, name: str, x0: float, y0: float, x1: float, y1: float) -> dict:
    return {"id": zid, "name": name, "type": "zone", "points": [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]}


def rule(key: str, **definition) -> CompiledRule:
    return CompiledRule(key=key, version=1, definition=RelationRuleDefinition.model_validate(definition))


@dataclass
class FakeResolver:
    """Recognition decisions scheduled by media time."""

    face: bool = True
    plate: bool = True
    decisions: dict[int, list[tuple[float, EntityRef]]] = field(default_factory=dict)
    now: float = 0.0

    def provides(self) -> set[str]:
        return {m for m, on in (("face", self.face), ("plate", self.plate)) if on}

    def resolve(self, track_id: int, object_class: str) -> EntityRef:
        best = None
        for t, ent in self.decisions.get(track_id, []):
            if t <= self.now + 1e-9:
                best = ent
        return best or anonymous_entity(track_id, object_class)

    def forget(self, track_id: int) -> None:
        return None

    def person(self, track_id: int, at: float, identity: str, confidence: float = 0.93) -> None:
        self.decisions.setdefault(track_id, []).append(
            (at, EntityRef("enrolled_person", track_id, "person", identity_id=identity, display_name=identity, confidence=confidence, status=STATUS_RECOGNIZED, settled=True))
        )

    def vehicle(self, track_id: int, at: float, plate: str, vehicle_id: str | None = None, groups: list[str] | None = None, confidence: float = 0.9) -> None:
        kind = "registered_vehicle" if vehicle_id else "recognized_plate"
        self.decisions.setdefault(track_id, []).append(
            (at, EntityRef(kind, track_id, "car", plate=plate, vehicle_id=vehicle_id, groups=groups or [], confidence=confidence, status=STATUS_RECOGNIZED, settled=True))
        )


class Sim:
    """Steps an engine at a fixed rate with objects placed in metres."""

    def __init__(self, rules: list[CompiledRule], settings: dict | None = None, calibrated: bool = True, objects: list[dict] | None = None,
                 routes: list[dict] | None = None, resolver: FakeResolver | None = None, fps: float = 10.0) -> None:
        self.doc = scene(calibrated, objects, routes)
        self.resolver = resolver
        self.engine = RelationEngine(
            EngineContext(run_id=1, camera_id=1, experiment_id=1, frame_width=W, frame_height=H, scene=self.doc, scene_config_id=1, scene_version=1),
            rules, RelationExperimentSettings.model_validate({"enabled": True, **(settings or {})}), resolver,
        )
        self.dt = 1.0 / fps
        self.t = 0.0
        self.out: dict[str, list] = {"entities": [], "observations": [], "relationships": [], "correlated": []}
        self.seen: dict[int, Track] = {}

    def track(self, tid: int, cls: str, x_m: float, y_m: float, conf: float = 0.9) -> Track:
        half = (40 if cls != "person" else 10)
        px, py = x_m * PX_PER_M, y_m * PX_PER_M
        prev = self.seen.get(tid)
        tr = Track(tid, cls, conf, (px - half, py - 60, px + half, py), "tracked", (prev.hits + 1) if prev else 3, 0, 0, 0,
                   prev.first_time if prev else self.t, self.t, conf)
        self.seen[tid] = tr
        return tr

    def step(self, objs: dict[int, tuple[str, float, float]], interactions: list[Interaction] | None = None, events: list[dict] | None = None, ended: list[int] | None = None) -> None:
        if self.resolver is not None:
            self.resolver.now = self.t
        tracks = [self.track(tid, cls, x, y) for tid, (cls, x, y) in objs.items()]
        ias = list(interactions or [])
        for tid in ended or []:
            ias.append(Interaction("track_ended", tid, self.seen[tid].class_name, self.t, 0, (0, 0)))
        self.engine.step(self.t, 1_000_000.0 + self.t, tracks, ias, events or [])
        self._drain()
        self.t = round(self.t + self.dt, 6)

    def finish(self) -> None:
        self.engine.finish(self.t, 1_000_000.0 + self.t)
        self._drain()

    def _drain(self) -> None:
        p = self.engine.drain()
        if p:
            for k in self.out:
                self.out[k].extend(p[k])

    def rels(self, type_id: str | None = None) -> list[dict]:
        """Latest version of every relationship (the engine re-emits updates)."""
        latest: dict[str, dict] = {}
        for r in self.out["relationships"]:
            latest[r["uid"]] = r
        return [r for r in latest.values() if type_id is None or r["type"] == type_id]
