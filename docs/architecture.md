# CV-Scope architecture

CV-Scope is a configurable computer-vision monitoring and research platform for
fixed cameras. This document records the architecture assessment, the technology
decisions, the folder layout, the domain model and the phased plan the code base
follows. It is written for contributors.

## 1. Assessment of the starting point

The repository started empty apart from the product specification. The machine
used for the first implementation is Windows 11 with an Intel i7-14700KF
(20 cores / 28 threads), 32 GB RAM and an NVIDIA RTX 4070 SUPER (12 GB VRAM).
Python 3.11, Node 22 and Docker are available. Everything below is designed to
run unchanged on Linux and macOS, and in CPU-only mode.

## 2. Technology decisions

| Concern | Decision | Reason |
| --- | --- | --- |
| Backend | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | Mature, typed, well documented, and the vision ecosystem is Python. |
| Database | SQLite (default, WAL mode) or PostgreSQL via `PATHSCOPE_DATABASE_URL` | Local-first single-machine installs need zero setup; the ORM and migrations are dialect-neutral so server deployments can use PostgreSQL. |
| Detection | Provider interface with three implementations: Ultralytics (YOLO11 / YOLOv8 / RT-DETR), ONNX Runtime (exported detectors), torchvision (SSDLite, Faster R-CNN) | Ultralytics is the most practical maintained YOLO ecosystem but is AGPL-3.0, so it is an optional extra and its licence is shown in the model catalog. ONNX Runtime and torchvision give permissively licensed paths. |
| Tracking | In-house ByteTrack (default) and BoT-SORT (camera motion compensation, optional appearance matching) behind a `Tracker` interface | The ByteTrack algorithm is simple, MIT-licensed in its reference form, robust for people and vehicles, and an in-house implementation exposes the track states and statistics the research UI needs. Other trackers can be registered. |
| Inference runtime | Provider probe (PyTorch CUDA / MPS / CPU, ONNX Runtime CPU / CUDA / TensorRT execution providers) with AUTO selection and graceful fallback | Hardware-aware recommendation is a core requirement; no single runtime is available everywhere. |
| Video I/O | OpenCV `VideoCapture` for files, USB and RTSP/HTTP | Cross-platform and mature. Sources implement a small `FrameSource` interface so more can be added. |
| Workers | One `multiprocessing` process per running camera, supervised by the API process | A GPU or decoder crash must not take the API down; separate processes also avoid the GIL for decoding and inference. |
| Frontend | React 19, TypeScript 5.9, Vite 7, react-router 7, TanStack Query 5, Zustand 5, Konva 10 / react-konva, Recharts 3 | Mature, maintained, permissively licensed. Konva is a proper canvas scene graph with hit testing, which the editor needs. |
| Styling | Hand-written CSS with design tokens, system font stack, no component framework | Restrained industrial/scientific look, information density, no external requests at runtime. |
| Packaging | `pyproject.toml`, setup scripts, Dockerfile (CPU and CUDA), docker-compose with optional PostgreSQL | Reproducible installs without cloud services. |

Versions are pinned as ranges in `backend/pyproject.toml` and
`frontend/package.json`; see `docs/installation.md`.

## 3. Folder structure

```
backend/
  pathscope/
    api/            FastAPI routers and request/response schemas
    db/             SQLAlchemy models, session management
    domain/         Pydantic domain models (scene config, rules, geometry)
    hardware/       Hardware probe and recommendation engine
    models/         Model catalog, installation, benchmarking
    vision/
      detectors/    Detector providers (ultralytics, onnxruntime, torchvision)
      trackers/     Tracker interface, ByteTrack, BoT-SORT, camera motion, appearance encoders
      sources/      Frame sources (file, usb, rtsp/http)
      inference/    Runtime/device probing and selection
      pipeline.py   Frame -> detector -> tracker -> spatial -> rules
    spatial/        Geometry, spatial engine, calibration
    rules/          Rule engine, route state machine, actions
    analytics/      Aggregation, behaviour metrics, export
    workers/        Camera worker process, supervisor, message types
    storage/        Event writer and retention
    recognition/    Licensed modules (locked without a licence): common/, licensing/,
                    face/ (detector, alignment, quality, embeddings, matcher, enrollment),
                    plate/ (detector, preprocessing, ocr, parser, temporal), registry/,
                    events/, api/, runtime.py, service.py, catalog.py
    relationships/  Relationship & Event Correlation Engine: entities, observations,
                    relation registry, spatial, temporal, confidence, rules, correlation,
                    engine, replay, graph, visual (interactive graph queries), patterns,
                    summary, access, service, api
    location/       Location Engine: site hierarchy, layouts, camera topology, zone mapping,
                    plausibility and travel time, cross-camera settings, /api/locations
    crosscam/       Cross-camera correlation: sightings, transitions, journeys, topology deviations
  alembic/          Database migrations
  tests/            Unit and integration tests
frontend/
  src/
    api/            Typed API client
    components/     Reusable UI primitives
    pages/          Projects, Live, Experiments, Data, Analysis, Cameras, Models, Hardware, Settings, Setup
    scene-builder/  Canvas editor, tools, inspector, editor store (undo/redo)
    rule-builder/   Structured rule editor (subject and HAS RELATIONSHIP clauses)
    relationships/  Relationship explorer, timeline, search, rule editor, settings
    locations/      Interactive graph (canvas, model, workbench), journeys, site plan,
                    topology editor, site view
docs/               Architecture, installation, models, data model, privacy, developer guide
samples/            Sample scene and experiment configurations
scripts/            Setup and development scripts
```

## 4. Domain model

Configuration, events, aggregates and media metadata are kept in separate
tables. Raw frames are never stored in the database.

* **Project** -> **Site** (optional) -> **Camera** -> **SceneConfig** (versioned) ->
  **Experiment** -> **Run** -> **Event** / **TrackSummary** / **Trajectory**.
* **Camera** holds the source definition (file, usb, rtsp, http), requested and
  processing FPS, rotation, crop, inference resolution and reconnect policy.
* **SceneConfig** stores normalized geometry (0..1 relative to the source frame),
  routes and calibration as JSON. Saving a scene that is referenced by a
  finished or running run creates a new version rather than mutating the old one.
* **Experiment** pins a scene config version, the object classes, model,
  tracker, inference preset and rules, plus research notes, condition notes and
  tags. Experiments can be duplicated.
* **Run** is one execution of an experiment (a session). It records start/end,
  status, the model/tracker snapshot and live statistics.
* **Event** is the research record: run, camera, anonymous track id, object
  class, event type, rule, route, timestamps, duration, speed, confidence and a
  context object (occupancy at decision time, previous route choice, direction).
* **TrackSummary** stores one row per anonymous track (lifetime, path length,
  mean speed, final route result, final state) and **Trajectory** optionally
  stores sampled ground-plane points.
* **Evaluation** stores manual verdicts on events for accuracy validation.
* **InstalledModel**, **Benchmark** and **Setting** support the model manager and
  the settings pages.

See `docs/data-model.md` for column-level detail.

## 5. Hardware detection strategy

`pathscope.hardware.probe` gathers, without failing when a library is missing:

* OS, Python, CPU brand (py-cpuinfo), physical/logical cores and frequency
  (psutil), total/available RAM, disk space of the data directory.
* NVIDIA GPUs through NVML (`nvidia-ml-py`): name, VRAM total/used, driver and
  the CUDA version supported by the driver; `torch.cuda` for the CUDA build of
  the runtime and the compute capability; ROCm through `torch.version.hip`;
  Apple MPS through `torch.backends.mps`; any other adapters (including
  integrated GPUs) through WMI on Windows, `lspci` on Linux and
  `system_profiler` on macOS.
* Runtimes: PyTorch (version, CUDA/MPS availability), ONNX Runtime (available
  execution providers), TensorRT, OpenVINO, Ultralytics.

`pathscope.hardware.recommend` turns the probe into a tiered recommendation
(Fast / Balanced / Accurate / CPU) with reasons, and selects the inference
runtime for AUTO mode. Recommendations are labelled as estimates until a
benchmark has been run on the machine.

## 6. Inference and model abstraction

```
Detector (interface)          Tracker (interface)        FrameSource (interface)
  |- UltralyticsDetector        |- ByteTrack                |- FileSource
  |                             |- BoT-SORT                 |
  |- OnnxRuntimeDetector                                    |- UsbSource
  |- TorchvisionDetector                                    |- NetworkSource (rtsp/http)
```

* A detector receives a BGR frame and returns `Detection` records
  (class name, confidence, box). It knows nothing about lines, zones or routes.
* The model catalog (`pathscope.models.catalog`) describes each model: family,
  task, classes, size, memory and compute needs, CPU/GPU suitability, relative
  accuracy/speed, runtimes, licence, source and installation state.
* The runtime selector maps AUTO/FAST/BALANCED/ACCURATE/CUSTOM presets plus the
  hardware probe to a concrete provider, device, image size and thresholds, and
  records the fallback chain that was actually used.

## 7. Scene Builder architecture

The Scene Builder is a canvas editor, not a form.

* The video frame is drawn on a Konva stage; all geometry is stored normalized
  (0..1) and converted to display pixels only for rendering, so a configuration
  keeps working at any display size or when the source resolution changes.
* An editor store (Zustand) holds the scene document, selection, active tool
  and an undo/redo history of document snapshots.
* Tools: select, pan, line, gate, zone, route, checkpoint, ignore region,
  calibration. Objects support move, vertex editing, rename, duplicate,
  delete, enable/disable, lock and visibility.
* The inspector on the right edits the selected object; routes are edited as an
  ordered sequence of gates/checkpoints. The rule builder produces structured
  rules (WHEN class / CROSSES gate / THEN CROSSES gate / WITHIN n s / RECORD AS).
* While a run is active the same canvas renders detections, tracks and
  trajectories streamed over a WebSocket, with toggleable debug overlays.

## 8. Processing pipeline and separation of concerns

```
frame -> preprocessing -> detector -> tracker -> spatial engine -> rule engine -> events -> storage
```

* The **spatial engine** understands only geometry: it converts each track
  movement into interactions (line crossed with direction, zone entered/exited,
  dwell ticks, checkpoint passed, occupancy).
* The **rule engine** consumes interactions and track lifecycle changes and runs
  per-track state machines: crossing counts, zone entry/exit, dwell rules and
  multi-stage sequences. Routes compile into sequence rules with outcomes
  ROUTE_<name>, UNKNOWN, LOST_TRACK and ABANDONED, and the engine never forces
  a track into a route when the evidence is incomplete.
* The **analytics** package only reads stored events.
* The **entity layer** (`domain/entities.py`) says what a track resolves to:
  an anonymous person or vehicle in the core, an enrolled person, a
  recognized plate or a registered vehicle when the licensed recognition
  modules are active. The rule engine evaluates a rule's subject clause
  against that entity through the `EntityResolver` interface only; the core
  never imports recognition code, and rules that need an inactive module stay
  inactive. The recognition runtime runs after the tracker and before the
  spatial engine inside the same pipeline step. See `docs/recognition.md`.
* The **relationship engine** (`relationships/engine.py`) runs after the rule
  engine on every processed frame when an experiment turns it on. It reads the
  tracked boxes, the interactions, the rule events and the entity resolver,
  and publishes normalized observations, time-bounded relationships with a
  confidence and their evidence, and correlated events. The same engine
  replays stored trajectories to analyse a run again with other rule
  versions. It knows no detector, tracker or recognition model. The rule
  engine asks it for the HAS RELATIONSHIP clause. See `docs/relationships.md`.
* The **Location Engine** (`location/`) places cameras, sensors and places in a
  hierarchy with logical or GPS coordinates and links with travel times.
  **Cross-camera correlation** (`crosscam/`) runs in the API process after the
  relationship engine stored a batch or a run: it joins an identity's sightings
  on different cameras into transitions scored by identity, timing, topology
  and sensors, mirrors them into the relationship graph and reports topology
  deviations as run events. The interactive graph, journeys and site view are
  read-only queries over the stored data. See `docs/locations.md`.

## 9. Phased plan

1. Project structure, hardware detection, model manager, video input, detector
   and tracker providers, basic frontend.
2. Scene Builder with lines, zones and gates; crossing and counting events.
3. Routes, route state machine, sequence rules, unknown/lost handling.
4. Experiments, storage, analytics, CSV/JSON/Parquet export.
5. Perspective calibration, speed, distance, dwell time, occupancy.
6. Research analysis (following, crowd influence, switching), evaluation tools.
7. RTSP reliability, multi-camera supervision, performance monitoring.

Features that are not implemented yet are labelled as such in the UI rather
than simulated.
