"""Local timing of the recognition models (synthetic inputs; numbers only).

Measures the face detector on a typical head crop and the embedder on an
aligned crop, or the plate detector on a vehicle crop and the OCR on a plate
crop, on this machine. Results feed the hardware recommendations.
"""

from __future__ import annotations

import time

import cv2
import numpy as np

from pathscope.recognition.service import RecognitionNotReady, model_paths


def _timeit(fn, iterations: int) -> dict:
    fn()  # warm up
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000.0)
    arr = np.array(times)
    return {"mean_ms": round(float(arr.mean()), 2), "median_ms": round(float(np.median(arr)), 2), "p95_ms": round(float(np.percentile(arr, 95)), 2), "iterations": iterations}


def _synthetic(h: int, w: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.clip(rng.normal(120, 30, size=(h, w, 3)), 0, 255).astype(np.uint8)


def run_recognition_benchmark(module: str, values: dict, device: str = "auto", iterations: int = 30) -> dict:
    paths = model_paths(values)
    if module == "face":
        if paths.face is None:
            raise RecognitionNotReady("The face models are not installed." + (f" Missing: {', '.join(paths.missing)}." if paths.missing else ""))
        from pathscope.recognition.face.stack import create_face_stack

        stack = create_face_stack(paths.face["stack"], {"detector": paths.face["detector"], "embedder": paths.face["embedder"]}, device=device)
        head = _synthetic(220, 180)
        aligned = _synthetic(112, 112)
        try:
            det = _timeit(lambda: stack.detector.detect(head), iterations)
            emb = _timeit(lambda: stack.embedder.embed(aligned), iterations)
            frame = _synthetic(720, 1280)
            full = _timeit(lambda: stack.detector.detect(frame), max(5, iterations // 3))
        finally:
            stack.close()
        per_attempt = det["median_ms"] + emb["median_ms"]
        return {
            "module": "face", "stack": paths.face["stack"], "device": stack.detector.resolved_device, "detector": stack.detector.describe(), "embedder": stack.embedder.describe(),
            "detector_head_crop": det, "detector_full_720p": full, "embedder_timing": emb,
            "per_attempt_ms": round(per_attempt, 2), "attempts_per_second_at_full_load": round(1000.0 / per_attempt, 1) if per_attempt > 0 else None,
            "note": "Synthetic inputs: timing only. One attempt = one face detection on a head crop plus one embedding.",
        }
    if paths.plate is None:
        raise RecognitionNotReady("The plate models are not installed." + (f" Missing: {', '.join(paths.missing)}." if paths.missing else ""))
    from pathscope.recognition.plate.stack import create_plate_stack

    stack = create_plate_stack({k: v for k, v in paths.plate.items() if k != "stack"}, device=device, stack_id=paths.plate["stack"])
    vehicle = _synthetic(300, 400)
    plate = _synthetic(48, 160)
    cv2.putText(plate, "ABC12345", (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2, cv2.LINE_AA)
    try:
        det = _timeit(lambda: stack.detector.detect(vehicle), iterations)
        ocr = _timeit(lambda: stack.ocr.read(plate), iterations)
    finally:
        stack.close()
    per_attempt = det["median_ms"] + ocr["median_ms"]
    return {
        "module": "plate", "device": stack.detector.resolved_device, "detector": stack.detector.describe(), "ocr": {k: v for k, v in stack.ocr.describe().items() if k != "config"},
        "detector_vehicle_crop": det, "ocr_plate_crop": ocr, "per_attempt_ms": round(per_attempt, 2), "attempts_per_second_at_full_load": round(1000.0 / per_attempt, 1) if per_attempt > 0 else None,
        "note": "Synthetic inputs: timing only. One attempt = one plate detection on a vehicle crop plus one OCR read.",
    }
