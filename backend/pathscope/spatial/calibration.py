"""Perspective calibration: image plane -> ground plane.

Three modes, reported explicitly so measurements are never presented as more
precise than they are:

* ``homography``: four or more image/ground point pairs give a full planar
  homography; distances and speeds are in the calibration unit (metres).
* ``scale``: a single known distance gives a uniform pixel->unit scale; only
  approximately valid for near-orthographic views.
* ``none``: measurements stay in normalized frame units ("frame/s").
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from pathscope.domain.scene import Calibration


@dataclass
class GroundMapper:
    mode: str  # homography | scale | none
    unit: str  # "m" or "frame"
    frame_width: int
    frame_height: int
    homography: np.ndarray | None = None
    scale_per_pixel: float | None = None

    @classmethod
    def from_calibration(
        cls, calibration: Calibration | None, frame_width: int, frame_height: int
    ) -> GroundMapper:
        if calibration is None:
            return cls("none", "frame", frame_width, frame_height)
        if len(calibration.points) >= 4:
            try:
                import cv2

                src = np.array(
                    [[p.image.x * frame_width, p.image.y * frame_height] for p in calibration.points],
                    dtype=np.float64,
                )
                dst = np.array(
                    [[p.ground_x, p.ground_y] for p in calibration.points], dtype=np.float64
                )
                h, _mask = cv2.findHomography(src, dst, 0)
                if h is not None and np.isfinite(h).all():
                    return cls("homography", calibration.unit, frame_width, frame_height, homography=h)
            except Exception:  # pragma: no cover - depends on cv2 numerics
                pass
        if calibration.known_distance is not None:
            kd = calibration.known_distance
            px = np.hypot(
                (kd.a.x - kd.b.x) * frame_width, (kd.a.y - kd.b.y) * frame_height
            )
            if px > 1e-6:
                return cls(
                    "scale", calibration.unit, frame_width, frame_height,
                    scale_per_pixel=kd.distance / px,
                )
        return cls("none", "frame", frame_width, frame_height)

    # ------------------------------------------------------------------
    def to_ground(self, x_norm: float, y_norm: float) -> tuple[float, float]:
        """Map a normalized image point to ground coordinates in ``unit``."""
        if self.mode == "homography" and self.homography is not None:
            px, py = x_norm * self.frame_width, y_norm * self.frame_height
            v = self.homography @ np.array([px, py, 1.0])
            if abs(v[2]) < 1e-12:
                return (float("nan"), float("nan"))
            return (float(v[0] / v[2]), float(v[1] / v[2]))
        if self.mode == "scale" and self.scale_per_pixel is not None:
            return (
                x_norm * self.frame_width * self.scale_per_pixel,
                y_norm * self.frame_height * self.scale_per_pixel,
            )
        return (x_norm, y_norm)

    def distance(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        """Distance between two normalized image points, in ``unit``."""
        ga = self.to_ground(*a)
        gb = self.to_ground(*b)
        return float(np.hypot(ga[0] - gb[0], ga[1] - gb[1]))

    @property
    def speed_unit(self) -> str:
        return f"{self.unit}/s"

    def describe(self) -> dict:
        return {"mode": self.mode, "unit": self.unit, "speed_unit": self.speed_unit}
