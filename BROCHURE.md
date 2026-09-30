# CV-Scope

**Turn any fixed camera into a research and monitoring instrument, without writing code.**

CV-Scope is an open-source computer-vision platform for fixed cameras. You
connect a camera or a recorded video, draw what matters directly on the
picture (a doorway line, a queue area, the routes people can take), and start
an experiment. CV-Scope detects and tracks people, vehicles and other objects,
turns their movement into events, and gives you data you can analyse, verify
and export.

```text
Camera / video  →  Detection  →  Tracking  →  Your lines, zones and routes  →  Events  →  Analysis and export
```

![Scene Builder: gates, a zone and two routes drawn over a corridor camera](docs/screenshots/06-scene-builder.png)

---

## Who it is for

| You are... | You use CV-Scope to... |
| --- | --- |
| **A researcher** | Run behavioural and pedestrian studies: which route people choose, how long they stay, how a change (signage, layout) alters behaviour, compared run against run. |
| **A facilities or retail team** | Count visitors through doors, measure occupancy and space use, and time queues. |
| **A traffic or mobility analyst** | Count vehicles, cyclists and pedestrians by class and direction, analyse turns, calibrate speeds. |
| **An operator or site manager** | Watch cameras live, record clips around events, be told when something in a room changes, and follow movements across several cameras. |
| **A student or educator** | Learn detection, tracking and spatial analytics hands-on, with 26 guided exercises from a first line count to a full study. |

---

## What you can do

**Draw your study on the picture.** A Scene Builder puts lines, gates, zones,
routes, checkpoints, ignore areas and calibration points directly over the
camera frame. Nothing to program: rules such as "person enters the Server
Room *and stays more than 5 minutes*" are built from menus.

**Count, time and follow movement.** Crossings with direction, zone entries,
exits, occupancy and dwell time, route choices (and routes abandoned
half-way), multi-step sequences, and speeds in real units once calibrated.

**Run proper experiments.** Each experiment fixes the scene, objects,
detector, tracker and rules, with notes on the research question and
conditions. Duplicate it to change one condition and compare the results.

**See and export the results.** Live counters and events while a camera runs;
afterwards, route distributions, time series, heatmaps, trajectories and
experiment comparisons. Export to CSV, JSON or Parquet, or push events to
other systems through webhooks and a REST API.

**Check the numbers.** Replay a run with its geometry and trajectories on the
video, mark each event correct or wrong, enter manual counts, and get
accuracy computed from your own verdicts. CV-Scope never invents an accuracy
figure.

**Notice what changed.** The Anomaly Assistant learns the normal picture of a
room, stall, vault or bed and reports meaningful change: an object appears,
disappears or moves, someone is present where nobody should be, the camera
is covered. Shadows, lighting flicker and insects are filtered out. An
optional vision-language model (local, or a cloud provider you choose) can
describe each event in words.

**Connect the dots.** A relationship engine links observations into
evidence-backed facts ("approached the vehicle", "entered the vehicle",
"parked in bay 3"), and a location model places cameras on a site plan, so
movements across several cameras become journeys on an interactive,
time-aware graph. Every link carries its evidence and a confidence;
nothing is made up by an AI model.

**Optional: recognise who, not just what.** Two licensed modules add face
recognition of *deliberately enrolled* people and vehicle-plate reading, with
roles, audit logs, encrypted templates and retention limits. They are locked
unless a signed licence is installed.

---

## How it works

1. **Install and let it check your machine.** A first-run wizard inspects the
   CPU, memory and GPU, recommends a detector that fits, and downloads it.
2. **Add a camera.** A USB webcam, a network camera (RTSP/HTTP) or a video
   file.
3. **Draw the scene.** Lines, zones and routes on the frame.
4. **Start an experiment.** Choose what to track and which rules apply;
   watch it live.
5. **Review, verify and export.** Analyse in the app, replay the video with
   overlays, export the data.

![Video review: tracked people, their paths and the events they triggered](docs/screenshots/13-review.png)

---

## Built to be trusted

* **Local-first.** Everything runs on your own computer. Camera footage,
  recordings and data stay on it; nothing is sent anywhere unless you connect
  a cloud AI provider yourself.
* **Private by default.** People are anonymous tracks that restart with
  every run. The core stores no faces or identities, and video recording is
  off unless an experiment turns it on. A settings page lists exactly what the
  installation stores.
* **Honest numbers.** Speeds, frame rates and accuracy come from measurements
  on your machine or from your own verdicts, or they are labelled as
  estimates.
* **Runs on what you have.** CPU-only laptops work; an NVIDIA GPU makes it
  faster. It adapts the detector and settings to the hardware.
* **Open source.** Apache License 2.0. The code, documentation and guides are
  public.

---

## Under the hood

| Area | Technology |
| --- | --- |
| Detection | YOLO11, YOLOv8 and RT-DETR (Ultralytics), SSDLite and Faster R-CNN (torchvision), any exported ONNX model |
| Tracking | ByteTrack, or BoT-SORT with camera-motion compensation and optional appearance matching |
| Backend | Python 3.11, FastAPI, OpenCV, SQLAlchemy with SQLite or PostgreSQL, separate worker processes per camera |
| Frontend | React and TypeScript web app, canvas-based Scene Builder |
| Hardware | CPU, NVIDIA CUDA, Apple Silicon; hardware discovery and a local benchmark |
| Deployment | One command on Windows, Linux or macOS, or Docker images for CPU and GPU |
| Interfaces | Web app, REST API and WebSockets, webhooks, and the `cvscope` command line |

---

## Try it

On Windows, download
[CV-Scope-Setup-Windows-x64.exe](https://github.com/ajm2004/CV-Scope/releases/latest/download/CV-Scope-Setup-Windows-x64.exe)
and follow the setup wizard. It installs everything, including PyTorch for
your graphics card, the detection models you pick and the sample videos; no
Python or administrator rights needed. Then open **CV-Scope** from the Start
menu.

From the source code, on any system:

```bash
git clone https://github.com/ajm2004/CV-Scope.git
cd CV-Scope
bash scripts/setup.sh      # Windows: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
bash scripts/dev.sh        # then open http://localhost:5173
```

Both ways download two short sample videos, so the first experiment works
without a camera. Full instructions, 26 step-by-step guides and the design
documentation are in the repository.

---

**CV-Scope**: open-source computer vision for fixed cameras · Apache-2.0 ·
Detector weights keep their own licences (Ultralytics models are AGPL-3.0).
