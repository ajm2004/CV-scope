"""Constant-velocity Kalman filters for box tracking. Pure numpy.

* ``KalmanBoxFilter`` tracks (cx, cy, aspect, height), as in SORT and ByteTrack.
* ``KalmanFilterXYWH`` tracks (cx, cy, width, height) with width- and
  height-proportional noise, as in BoT-SORT; it fits box width better when an
  object's aspect ratio changes (a person turning, a car entering a turn).

Both expose ``measure(box)`` and ``to_box(mean)`` so trackers can stay
agnostic of the state layout, and ``warp_state`` applies a camera-motion
affine to a state (BoT-SORT camera motion compensation).
"""

from __future__ import annotations

import numpy as np


def xyxy_to_xyah(box) -> np.ndarray:
    x1, y1, x2, y2 = box
    w = max(x2 - x1, 1e-6)
    h = max(y2 - y1, 1e-6)
    return np.array([x1 + w / 2.0, y1 + h / 2.0, w / h, h], dtype=np.float64)


def xyah_to_xyxy(xyah: np.ndarray) -> tuple[float, float, float, float]:
    cx, cy, a, h = xyah[:4]
    w = a * h
    return (float(cx - w / 2.0), float(cy - h / 2.0), float(cx + w / 2.0), float(cy + h / 2.0))


def xyxy_to_xywh(box) -> np.ndarray:
    x1, y1, x2, y2 = box
    w = max(x2 - x1, 1e-6)
    h = max(y2 - y1, 1e-6)
    return np.array([x1 + w / 2.0, y1 + h / 2.0, w, h], dtype=np.float64)


def xywh_to_xyxy(xywh: np.ndarray) -> tuple[float, float, float, float]:
    cx, cy, w, h = xywh[:4]
    w = max(float(w), 1e-3)
    h = max(float(h), 1e-3)
    return (float(cx - w / 2.0), float(cy - h / 2.0), float(cx + w / 2.0), float(cy + h / 2.0))


class KalmanBoxFilter:
    """State (cx, cy, a, h, vcx, vcy, va, vh)."""

    def __init__(self) -> None:
        ndim, dt = 4, 1.0
        self._motion_mat = np.eye(2 * ndim, 2 * ndim)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt
        self._update_mat = np.eye(ndim, 2 * ndim)
        self._std_weight_position = 1.0 / 20
        self._std_weight_velocity = 1.0 / 160

    # ---- state layout
    def measure(self, box) -> np.ndarray:
        return xyxy_to_xyah(box)

    def to_box(self, mean: np.ndarray) -> tuple[float, float, float, float]:
        return xyah_to_xyxy(mean)

    # ---- filter
    def initiate(self, measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]
        h = measurement[3]
        std = [
            2 * self._std_weight_position * h,
            2 * self._std_weight_position * h,
            1e-2,
            2 * self._std_weight_position * h,
            10 * self._std_weight_velocity * h,
            10 * self._std_weight_velocity * h,
            1e-5,
            10 * self._std_weight_velocity * h,
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = mean[3]
        std_pos = [
            self._std_weight_position * h,
            self._std_weight_position * h,
            1e-2,
            self._std_weight_position * h,
        ]
        std_vel = [
            self._std_weight_velocity * h,
            self._std_weight_velocity * h,
            1e-5,
            self._std_weight_velocity * h,
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))
        mean = self._motion_mat @ mean
        covariance = self._motion_mat @ covariance @ self._motion_mat.T + motion_cov
        return mean, covariance

    def project(self, mean: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        h = mean[3]
        std = [
            self._std_weight_position * h,
            self._std_weight_position * h,
            1e-1,
            self._std_weight_position * h,
        ]
        innovation_cov = np.diag(np.square(std))
        mean = self._update_mat @ mean
        covariance = self._update_mat @ covariance @ self._update_mat.T
        return mean, covariance + innovation_cov

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        projected_mean, projected_cov = self.project(mean, covariance)
        # Kalman gain via solve (projected_cov is SPD)
        kalman_gain = np.linalg.solve(projected_cov, (covariance @ self._update_mat.T).T).T
        innovation = measurement - projected_mean
        new_mean = mean + innovation @ kalman_gain.T
        new_cov = covariance - kalman_gain @ projected_cov @ kalman_gain.T
        return new_mean, new_cov


class KalmanFilterXYWH(KalmanBoxFilter):
    """State (cx, cy, w, h, vcx, vcy, vw, vh), noise proportional to w and h (BoT-SORT)."""

    def measure(self, box) -> np.ndarray:
        return xyxy_to_xywh(box)

    def to_box(self, mean: np.ndarray) -> tuple[float, float, float, float]:
        return xywh_to_xyxy(mean)

    def initiate(self, measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean = np.r_[measurement, np.zeros_like(measurement)]
        w, h = measurement[2], measurement[3]
        p, v = self._std_weight_position, self._std_weight_velocity
        std = [2 * p * w, 2 * p * h, 2 * p * w, 2 * p * h, 10 * v * w, 10 * v * h, 10 * v * w, 10 * v * h]
        return mean, np.diag(np.square(std))

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        w, h = mean[2], mean[3]
        p, v = self._std_weight_position, self._std_weight_velocity
        motion_cov = np.diag(np.square([p * w, p * h, p * w, p * h, v * w, v * h, v * w, v * h]))
        mean = self._motion_mat @ mean
        covariance = self._motion_mat @ covariance @ self._motion_mat.T + motion_cov
        return mean, covariance

    def project(self, mean: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        w, h = mean[2], mean[3]
        p = self._std_weight_position
        innovation_cov = np.diag(np.square([p * w, p * h, p * w, p * h]))
        mean = self._update_mat @ mean
        covariance = self._update_mat @ covariance @ self._update_mat.T
        return mean, covariance + innovation_cov


def warp_state(mean: np.ndarray, covariance: np.ndarray, warp: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Apply a 2x3 camera-motion affine to an 8-D box state (BoT-SORT ``multi_gmc``).

    The 2x2 linear part rotates/scales every (x, y)-like pair of the state
    (position, size, and their velocities); the translation moves the centre.
    """
    r = warp[:2, :2]
    r8 = np.kron(np.eye(4), r)
    new_mean = r8 @ mean
    new_mean[:2] += warp[:2, 2]
    new_cov = r8 @ covariance @ r8.T
    return new_mean, new_cov
