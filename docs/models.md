# Models, runtimes and licences

CV-Scope does not hard-wire one detector. The model catalog
(`backend/pathscope/models/catalog.py`) lists every supported model with its
family, task, classes, size, approximate memory and compute needs, CPU/GPU
suitability, relative accuracy and speed, supported runtimes, licence,
source and installation state. The Models page renders this catalog, adds the
hardware recommendation, and lets you install, remove and benchmark models.

## Supported detectors (initial catalog)

| Model | Provider | Licence | Notes |
| --- | --- | --- | --- |
| YOLO11 n/s/m/l/x | Ultralytics | AGPL-3.0 | Current default family; best speed/accuracy trade-off for people and vehicles |
| YOLOv8 n/s/m | Ultralytics | AGPL-3.0 | Previous generation, kept for reproducing older studies |
| RT-DETR L/X | Ultralytics | AGPL-3.0 (Ultralytics implementation) | Transformer detector without NMS; strong in crowded scenes; GPU recommended |
| YOLO11 n/s/m (ONNX) | ONNX Runtime | inherits the weights' licence | Exported locally from the PyTorch weights; runs without PyTorch, on CPU, CUDA or TensorRT execution providers |
| SSDLite320 MobileNetV3 | torchvision | BSD-3-Clause | Fast, permissively licensed; weaker on small objects |
| Faster R-CNN MobileNetV3 FPN | torchvision | BSD-3-Clause | Permissive two-stage detector |
| Faster R-CNN ResNet50 FPN v2 | torchvision | BSD-3-Clause | Accurate, slow; offline analysis on a GPU |

All catalog models are trained on COCO, so the trackable classes are the COCO
classes relevant to movement studies: person, bicycle, car, motorcycle, bus,
truck, train, boat, dog, cat, horse. Detector labels are mapped to these
canonical names in `pathscope/vision/classes.py`.

Reference accuracy values shown in the catalog are the COCO val2017
mAP50-95 figures published by the upstream projects. They are for relative
comparison only. CV-Scope never displays a local FPS figure until you run a
benchmark on the machine.

## Licence guidance

* CV-Scope itself is Apache-2.0.
* **Ultralytics** code and weights are **AGPL-3.0**. Using them for research
  and internal deployments is fine; distributing a product built on them
  requires AGPL compliance for the whole product or a commercial licence from
  Ultralytics. The `ultralytics` package is therefore an optional extra and
  the licence is shown next to each model.
* **torchvision** detectors are BSD-3-Clause and can be used without such
  obligations.
* ONNX files exported from Ultralytics weights keep the AGPL-3.0 licence of
  the weights.
* Sample videos are CC-BY-4.0 (see `samples/README.md`).

## Inference runtimes

The runtime probe (`pathscope/vision/inference/runtime.py`) detects:

* PyTorch CUDA, ROCm, Metal (MPS) and CPU
* ONNX Runtime execution providers: TensorRT, CUDA, CoreML, CPU
* TensorRT and OpenVINO packages (reported; not yet used for native engines)

`AUTO` picks, in order, PyTorch CUDA → PyTorch MPS → ONNX Runtime CUDA →
PyTorch CPU → ONNX Runtime CPU, and records the fallback chain that was used
in the run snapshot. If a CUDA out-of-memory error occurs during inference the
detector falls back to the CPU for the rest of the run and the run diagnostics
show the resolved device.

## Presets

| Preset | Behaviour |
| --- | --- |
| AUTO | Recommended tier for the detected hardware |
| FAST | Smaller model, suited to several simultaneous streams |
| BALANCED | Middle tier |
| ACCURATE | Larger model and higher inference resolution; lower FPS |
| CUSTOM | Every field (device, resolution, thresholds, processing FPS, frame skip, tracker settings) is set by the user |

A detector chosen explicitly in the experiment overrides the tier's model; the
preset then still sets resolution and thresholds unless CUSTOM.

## Benchmark

`cvscope benchmark <model_id> [--device auto|cuda|cpu] [--image-size N]
[--video path] [--tracker bytetrack|botsort]` or the Benchmark button on the Models page runs about 120
frames through the detector and tracker and reports source and inference
resolution, preprocessing, detector and tracker time (mean, median, p95),
pipeline FPS, CPU usage, process memory and VRAM before/after load and peak.
Results are stored and shown next to the model; the recommendations panel
notes when local measurements exist.

## Trackers

Two trackers are implemented in CV-Scope, behind the same `Tracker`
interface. Both report anonymous, session-scoped track ids with the states
tentative, tracked, lost and removed. The run diagnostics show lost events,
reacquisitions, removed tracks and mean lifetime. Settings are under the
experiment's advanced settings.

| Tracker | Use it when | Cost |
| --- | --- | --- |
| ByteTrack (default) | Fixed camera, ordinary scenes | Negligible |
| BoT-SORT | The camera can shake, sway or pan, or people often cross or walk close together | Camera motion: about 2 ms per frame at 768x432 and 6 ms at 1080p (CPU). Colour histogram appearance: about 0.1 ms per object. ResNet-18 appearance: a few milliseconds per frame on a GPU, about 11 ms per object on a CPU |

### ByteTrack

`pathscope/vision/trackers/bytetrack.py`: a Kalman motion model on
(cx, cy, aspect, height) and two-stage IoU association (high-confidence
detections first, then low-confidence ones for tracks that were not matched),
with a confirmation step for new tracks and a lost-track buffer.

### BoT-SORT

`pathscope/vision/trackers/botsort.py` follows Aharon et al., 2022
(reference implementation: https://github.com/NirAharon/BoT-SORT, MIT). It is
ByteTrack's association with:

* **A Kalman state on (cx, cy, width, height)** with noise proportional to
  width and height.
* **Camera motion compensation** (`gmc.py`). The motion of the whole image
  between frames is estimated from background keypoints and applied to the
  predicted track states before matching. Methods: sparse optical flow
  (default), ORB feature matching, ECC image alignment, or off. Detection
  boxes are excluded from the estimate, and implausible estimates (scene cut,
  seek) are treated as no motion. The run diagnostics report the mean and
  maximum measured camera motion in pixels, so a camera that was bumped
  during a study is visible.
* **Score-weighted IoU** in the first association stage, a separate
  threshold for starting new tracks, and removal of a track that duplicates
  an older lost one.
* **Appearance matching (optional, off by default as in the reference).**
  For a track and a detection that are already close (IoU distance below the
  proximity threshold) and look alike, the cost is the smaller of the IoU cost
  and the appearance cost. Appearance can make a close match cheaper; it can
  never join boxes that are far apart.

Appearance methods:

| Method | What it is | Download |
| --- | --- | --- |
| Colour histogram | Soft circular H x S x V histograms of the upper and lower part of the box | None |
| Deep features, ResNet-18 | Generic ImageNet features from torchvision (BSD-3-Clause), not a person re-identification model | 45 MB, from the Models page |
| Custom ONNX model | Your own re-identification model: an ONNX file with an NCHW RGB input (ImageNet normalisation) placed in `<models>/reid/` | You provide it |

CV-Scope does not ship person re-identification weights, because the
public ones are trained on research-only datasets (Market-1501, MSMT17).
If you use one, check the licence of its training data.

The default similarity thresholds were calibrated on the two sample clips.
The calibration used 730 comparisons of a track with its own next detection
and 364 comparisons with other objects nearby. The thresholds were chosen so
that other nearby objects are practically never accepted:

| Method | Default minimum similarity | Same-object kept | Nearby other objects rejected |
| --- | --- | --- | --- |
| Colour histogram | 0.92 | 83% | 100% |
| ResNet-18 features | 0.925 | 86% | 99.5% |
| Custom ONNX model | 0.75 (BoT-SORT reference value for ReID models) | not calibrated | not calibrated |

This is a small calibration set. Adjust "Minimum appearance similarity" if
your scenes differ, for example uniforms or same-coloured vehicles, where
the colour histogram cannot tell objects apart.

Measured effect in CV-Scope's tests (`backend/tests/test_botsort.py`):

| Scenario | ByteTrack | BoT-SORT |
| --- | --- | --- |
| Three static people, the camera jolts by 40-50 px three times | 9 id changes | 0 id changes with any camera-motion method |
| Two people meet (one partly in front) and both turn back | ids swapped | ids swapped without appearance, kept with the colour histogram or ResNet-18 |

On the corridor sample clip, BoT-SORT without appearance produced 7 tracks
with a mean lifetime of 60 frames. ByteTrack produced 8 tracks with a mean
lifetime of 53 frames. There is no ground truth for the clip, so this is
reported as fragmentation, not accuracy.

Privacy: appearance summaries exist only in the tracker's memory while an
object is tracked. They are never written to disk, sent to the browser or
compared across runs or cameras, and they are discarded when the track ends.
See `docs/privacy.md`.

## Recognition models (licensed modules)

The face and plate models of the licensed recognition modules
(`docs/recognition.md`) are listed in the same catalog
(`pathscope/recognition/catalog.py`), downloaded on demand into
`<models>/recognition`, and usable only with a valid licence.

| Model | Task | Backend | Licence | Notes |
| --- | --- | --- | --- | --- |
| YuNet 2023mar (OpenCV Zoo) | face detector | OpenCV DNN, CPU | MIT | default; faces from about 10 px; five landmarks |
| SFace 2021dec (OpenCV Zoo) | face embedding, 128-d | OpenCV DNN, CPU | Apache-2.0 | default; Recognized from cosine 0.46 by default |
| SCRFD-10G (InsightFace buffalo_l) | face detector | ONNX Runtime | non-commercial research only | stronger on small and non-frontal faces; from the 275 MB pack, only this file is extracted |
| ArcFace ResNet-50 WebFace600K (InsightFace buffalo_l) | face embedding, 512-d | ONNX Runtime | non-commercial research only | more robust on low-quality footage; GPU recommended |
| YOLOv9-t 384 / 640, YOLOv9-s 608 (open-image-models) | plate detector | ONNX Runtime | MIT | end-to-end exports (NMS inside) |
| CCT-S v2 global, CCT-XS v1 (fast-plate-ocr) | plate OCR | ONNX Runtime | MIT | per-character confidence; v2 also predicts the region |

Every recognition event records the model version that produced it.
Benchmark the models on your machine under Recognition → Settings.

## Adding a model

1. Add a `ModelSpec` to the catalog with honest requirement and licence data.
2. If it needs a new provider, implement `Detector` (see `docs/developer.md`).
3. Provide a download URL or an export path; the manager handles progress and
   install state.
