"""Global (camera) motion compensation for BoT-SORT.

Estimates the 2x3 affine transform that maps the previous frame onto the
current one, so predicted track positions can be moved with the camera before
association. Fixed cameras still shake (wind, vibration, a bumped mount), and
without compensation a jolt of a few tens of pixels breaks IoU matching.

Methods, following the BoT-SORT reference implementation:

* ``sparseOptFlow``: Shi-Tomasi corners tracked with pyramidal Lucas-Kanade,
  then a RANSAC similarity fit. Default; fast and robust.
* ``orb``: FAST keypoints with ORB descriptors, ratio-test matching and a
  RANSAC fit. Handles larger motions.
* ``ecc``: dense Enhanced Correlation Coefficient alignment (Euclidean),
  coarse to fine. Precise, slowest.
* ``none``: identity.

Detection boxes are masked out when picking keypoints (moving objects are not
camera motion), and implausible estimates (a scene cut, a seek, a failed fit)
fall back to the identity transform.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

GMC_METHODS = ("sparseOptFlow", "orb", "ecc", "none")


def _identity() -> np.ndarray:
    return np.eye(2, 3, dtype=np.float64)


class GlobalMotionCompensation:
    def __init__(self, method: str = "sparseOptFlow", downscale: int = 0, work_width: int = 640) -> None:
        """``downscale=0`` picks a factor so the working image is at most ``work_width`` wide."""
        if method not in GMC_METHODS:
            raise ValueError(f"unknown camera motion compensation method '{method}'")
        self.method = method
        self._fixed_downscale = max(0, int(downscale))
        self._work_width = work_width
        self.downscale = max(1, self._fixed_downscale)
        self._prev_gray: np.ndarray | None = None
        self._prev_kp = None
        self._prev_desc = None
        if method == "orb":
            self._detector = cv2.FastFeatureDetector_create(20)
            self._extractor = cv2.ORB_create()
            self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        # statistics (pixels of apparent camera motion at the frame centre)
        self.frames = 0
        self.rejected = 0
        self.motion_sum = 0.0
        self.motion_max = 0.0
        self.time_ms_sum = 0.0

    def reset(self) -> None:
        self._prev_gray = None
        self._prev_kp = None
        self._prev_desc = None

    # ------------------------------------------------------------------ public
    def apply(self, frame_bgr: np.ndarray | None, boxes: list | np.ndarray | None = None) -> np.ndarray:
        """Affine mapping previous-frame pixel coordinates to current-frame coordinates."""
        if self.method == "none" or frame_bgr is None:
            return _identity()
        t0 = time.perf_counter()
        h, w = frame_bgr.shape[:2]
        ds = self._fixed_downscale or max(2, -(-w // self._work_width))
        if ds != self.downscale:
            self.downscale = ds
            self.reset()  # previous state was stored at another scale
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY) if frame_bgr.ndim == 3 else frame_bgr
        if self.downscale > 1:
            if self.method == "ecc":
                gray = cv2.GaussianBlur(gray, (3, 3), 1.5)
            gray = cv2.resize(gray, (w // self.downscale, h // self.downscale), interpolation=cv2.INTER_AREA)
        try:
            if self.method == "sparseOptFlow":
                warp = self._sparse_optflow(gray, boxes)
            elif self.method == "orb":
                warp = self._orb(gray, boxes)
            else:
                warp = self._ecc(gray)
        except cv2.error:
            warp = None
            self.reset()
            self._prev_gray = gray
        if warp is None:
            warp = _identity()
        else:
            warp = warp.astype(np.float64)
            warp[0, 2] *= self.downscale
            warp[1, 2] *= self.downscale
            if not self._plausible(warp, w, h):
                self.rejected += 1
                warp = _identity()
        self._record(warp, w, h, (time.perf_counter() - t0) * 1000.0)
        return warp

    def stats(self) -> dict:
        n = max(self.frames, 1)
        return {
            "camera_motion_method": self.method,
            "camera_motion_mean_px": round(self.motion_sum / n, 2),
            "camera_motion_max_px": round(self.motion_max, 2),
            "camera_motion_rejected": self.rejected,
            "camera_motion_ms_mean": round(self.time_ms_sum / n, 2),
        }

    # ------------------------------------------------------------------ helpers
    def _mask(self, shape: tuple[int, int], boxes) -> np.ndarray:
        h, w = shape
        mask = np.zeros((h, w), dtype=np.uint8)
        mask[int(0.02 * h) : int(0.98 * h), int(0.02 * w) : int(0.98 * w)] = 255
        if boxes is not None:
            for b in boxes:
                x1, y1, x2, y2 = (int(round(v / self.downscale)) for v in b[:4])
                mask[max(0, y1) : max(0, y2), max(0, x1) : max(0, x2)] = 0
        return mask

    def _plausible(self, warp: np.ndarray, w: int, h: int) -> bool:
        if not np.isfinite(warp).all():
            return False
        scale = float(np.sqrt(abs(np.linalg.det(warp[:2, :2]))))
        if not 0.9 <= scale <= 1.1:
            return False
        c = np.array([w / 2.0, h / 2.0, 1.0])
        shift = float(np.hypot(*(warp @ c - c[:2])))
        return shift <= 0.25 * max(w, h)

    def _record(self, warp: np.ndarray, w: int, h: int, ms: float) -> None:
        c = np.array([w / 2.0, h / 2.0, 1.0])
        motion = float(np.hypot(*(warp @ c - c[:2])))
        self.frames += 1
        self.motion_sum += motion
        self.motion_max = max(self.motion_max, motion)
        self.time_ms_sum += ms

    # ------------------------------------------------------------------ methods
    def _sparse_optflow(self, gray: np.ndarray, boxes) -> np.ndarray | None:
        mask = self._mask(gray.shape[:2], boxes)
        keypoints = cv2.goodFeaturesToTrack(gray, maxCorners=1000, qualityLevel=0.01, minDistance=1, blockSize=3, mask=mask, useHarrisDetector=False, k=0.04)
        prev_gray, prev_kp = self._prev_gray, self._prev_kp
        self._prev_gray, self._prev_kp = gray, keypoints
        if prev_gray is None or prev_kp is None or len(prev_kp) < 5 or prev_gray.shape != gray.shape:
            return None
        next_pts, status, _err = cv2.calcOpticalFlowPyrLK(prev_gray, gray, prev_kp, None)
        if next_pts is None or status is None:
            return None
        good = status.reshape(-1) == 1
        src = prev_kp.reshape(-1, 2)[good]
        dst = next_pts.reshape(-1, 2)[good]
        if len(src) < 5:
            return None
        return self._fit(src, dst)

    def _orb(self, gray: np.ndarray, boxes) -> np.ndarray | None:
        mask = self._mask(gray.shape[:2], boxes)
        kps = self._detector.detect(gray, mask)
        kps, desc = self._extractor.compute(gray, kps)
        prev_kp, prev_desc, prev_gray = self._prev_kp, self._prev_desc, self._prev_gray
        self._prev_kp, self._prev_desc, self._prev_gray = kps, desc, gray
        if prev_desc is None or desc is None or len(prev_kp) < 5 or len(kps) < 5 or prev_gray.shape != gray.shape:
            return None
        h, w = gray.shape[:2]
        max_dist = 0.25 * np.array([w, h])
        src, dst, disp = [], [], []
        for pair in self._matcher.knnMatch(prev_desc, desc, 2):
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance >= 0.9 * n.distance:
                continue
            p = np.array(prev_kp[m.queryIdx].pt)
            q = np.array(kps[m.trainIdx].pt)
            d = q - p
            if abs(d[0]) < max_dist[0] and abs(d[1]) < max_dist[1]:
                src.append(p)
                dst.append(q)
                disp.append(d)
        if len(src) < 5:
            return None
        disp = np.array(disp)
        mu, sd = disp.mean(axis=0), disp.std(axis=0) + 1e-6
        keep = np.all(np.abs(disp - mu) < 2.5 * sd, axis=1)
        src, dst = np.array(src)[keep], np.array(dst)[keep]
        if len(src) < 5:
            return None
        return self._fit(src, dst)

    def _fit(self, src: np.ndarray, dst: np.ndarray) -> np.ndarray | None:
        """RANSAC similarity fit; unreliable fits (few inliers) count as no estimate."""
        warp, inliers = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if warp is None or inliers is None:
            return None
        n_in = int(inliers.sum())
        if n_in < max(10, int(0.3 * len(src))):
            self.rejected += 1
            return None
        return warp

    def _ecc(self, gray: np.ndarray) -> np.ndarray | None:
        prev = self._prev_gray
        self._prev_gray = gray
        if prev is None or prev.shape != gray.shape:
            return None
        # Pyramid: estimate at 1/4 of the working resolution, then refine.
        levels = []
        a, b = prev, gray
        for _ in range(3):
            levels.append((a, b))
            if min(a.shape[:2]) < 120:
                break
            a, b = cv2.pyrDown(a), cv2.pyrDown(b)
        warp = np.eye(2, 3, dtype=np.float32)
        for depth, (a, b) in enumerate(reversed(levels)):
            iters = 60 if depth == 0 else 25
            criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-4)
            cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_EUCLIDEAN, criteria, None, 3)
            if depth < len(levels) - 1:
                warp[:, 2] *= 2.0  # translation to the next finer level
        if cc < 0.8:  # images do not match (scene cut, seek, heavy occlusion)
            self.rejected += 1
            return None
        return warp
