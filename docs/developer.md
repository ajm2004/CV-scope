# Developer guide

## Code layout

```
backend/pathscope/
  main.py               FastAPI app factory, static frontend serving, lifespan
  cli.py                cvscope serve | migrate | hardware | models | benchmark
  config.py             Settings (env / .env), data directories
  settings_store.py     User settings in the database, layered over env defaults
  logging_setup.py      structlog configuration (console or JSON)
  api/                  routers (system, hardware, models, settings, projects, cameras,
                        videos, scenes, experiments, runs, events, analytics, evaluation),
                        schemas, dependencies
  db/                   SQLAlchemy models, session, migration runner
  domain/               Pydantic scene document and rule models
  hardware/             probe.py (CPU/RAM/GPU/runtimes), recommend.py (tiers, load estimate)
  models/               catalog.py, manager.py (install jobs), benchmark.py
  vision/
    types.py            Detection, Track, FramePacket
    classes.py          Label-set mapping to canonical class names
    detectors/          Detector interface; ultralytics, onnxruntime, torchvision providers
    trackers/           Tracker interface; ByteTrack and BoT-SORT (shared association
                        skeleton with hooks), Kalman filters, camera motion (gmc.py),
                        appearance encoders (appearance.py); registry and catalog
    sources/            FrameSource interface; file, usb, network (rtsp/http) sources
    inference/          Runtime probe and AUTO selection with fallback chain
    preprocessing.py    Rotation, crop, preview resize, JPEG encoding
    pipeline.py         Pipeline: source -> preprocess -> detect -> track -> spatial -> rules
  spatial/              geometry.py, calibration.py (homography / scale), engine.py
  rules/                engine.py: implicit rules, route groups, explicit sequence/dwell rules
  analytics/            aggregation.py, evaluation.py, export.py
  workers/              messages.py, camera_worker.py (process entry), supervisor.py
  storage/              writer.py: batched persistence of events, tracks, trajectories
  services/             run_launcher.py: experiment -> WorkerSpec, preset resolution
  domain/entities.py    Entity layer: what a track resolves to (anonymous in the core;
                        enrolled person / plate / registered vehicle with the licensed modules)
  recognition/          Licensed face and plate recognition (see docs/recognition.md):
                        licensing/ (Ed25519 licences), common/ (crypto, access, audit, config),
                        face/, plate/, registry/, events/, api/, runtime.py (EntityResolver
                        driven by the pipeline), service.py (facade used by the core)
backend/alembic/        migrations
backend/tests/          pytest suite
frontend/src/
  api/                  types.ts, client.ts
  components/           ui.tsx primitives, Layout.tsx shell, charts.tsx
  pages/                one file per page
  scene-builder/        store.ts (zustand + undo/redo), SceneCanvas.tsx (react-konva),
                        Inspector.tsx, SceneBuilderPage.tsx, useLiveRun.ts (run WebSocket),
                        useCameraPreview.ts (live picture outside runs)
  rule-builder/         RuleBuilder.tsx
```

## Processing model

Each run is one worker process (`multiprocessing`, spawn context) started by
`RunSupervisor`. The worker builds a `Pipeline`, loops over frames and sends:

* `status` messages (state, fps, counters, tracker stats, timings) once per
  second and on state changes,
* `events` (lists of `EventRecord` dicts) as they occur,
* `track_ended` summaries (with sampled trajectory points) when tracks are
  removed, and for every live track at the end of the run,
* `preview` messages on a bounded queue (dropped when the consumer is behind).

The supervisor drains the queues on threads, persists through `EventWriter`
(batched, retried on transient database errors), keeps the latest status and
preview in memory for the API and WebSocket, dispatches webhook actions, and
restarts crashed workers for live sources up to `worker_restart_limit`.
File-based runs that crash are marked failed.

Commands (pause, resume, stop, seek, set_preview) flow back through a command
queue; the WebSocket endpoint accepts the same commands from the browser.

### Video recording

When the experiment's `recording` setting is on and the camera is live, the
worker feeds every processed frame, with the overlay drawn if asked
(`vision/recording.py: draw_overlay`), to a `RunRecorder`. The recorder encodes
on its own thread behind a bounded queue, so a slow encoder drops frames
instead of stalling the analysis. Clips keep the last `pre_s` seconds plus 30 s
as JPEG in memory and open a file when a matching event arrives; every file is
aligned to media time (frames repeated or skipped) so the review player can
seek to an event. The frame rate is measured from the arriving frames and
capped at `fps`; a pause over 3 s starts a new file. Finished files go to the
supervisor as `recording` messages and become rows in `recordings`
(`storage/recordings.py`), which also runs the hourly retention and orphan
sweep. Writers are tried in order: H.264 through Windows Media Foundation, VP8
WebM through OpenCV's FFmpeg, Motion JPEG; the whole-run mode prefers VP8
because OpenCV gives the Media Foundation encoder about one bit per pixel and
frame. The worker closes the recorder before its final status, so the last
file is stored with the run.

## Live preview outside runs

A USB camera can be opened by one process at a time: a second process opens
it but receives no frames. `services/preview.py` is therefore the only owner
of live cameras in the API process.

* `PreviewManager.acquire(cfg)` returns a shared `PreviewSession`, a thread
  that reads the camera continuously and keeps the latest JPEG (15 fps,
  at most 1280 px wide). Viewers call `release()`, and a reaper closes the
  device `grace_s` (4 s) after the last viewer leaves.
* Viewers are the Scene Builder WebSocket (`/ws/cameras/{id}/preview`: a
  `frame` JSON message followed by the binary JPEG, `status` twice a second,
  `run_active` when a run takes the camera), the MJPEG stream
  (`/api/cameras/{id}/preview.mjpg`, used by `<img>` tags; it switches to the
  run's annotated frames while a run is active), and the `snapshot` and
  `frame-info` endpoints for live cameras.
* A camera is never opened while a run uses it (by camera id or by physical
  device, see `device_key`). `run_launcher` starts the worker inside
  `PreviewManager.handing_over()`, which releases the device and keeps viewers
  from reopening it until the run is registered. A session also stops by
  itself as soon as a run claims its device.
* Video files have no live preview; they are shown as still frames.

## Engines

### Spatial engine

Input: `TrackerUpdate` per processed frame. For every tracked, updated track it
takes the bottom-centre of the box as the ground point (normalized), and:

* detects segment crossings of enabled lines/gates with direction, applying
  per-object class filter, minimum track age, minimum confidence and
  per-track debounce;
* maintains zone presence with an entry delay (`min_dwell_s`) and an
  allowance for short exits (`debounce_s`: a track back inside within that
  time keeps its visit, a longer exit ends it when the track left), and emits
  `zone_entered` / `zone_exited` (with dwell) transitions. Zone and ignore
  polygon corners within 1.2 % of the frame border are snapped onto it;
* samples trajectories (every 0.1 s) and computes distances and speeds through
  the `GroundMapper` (homography, scale or frame units);
* emits `track_started`, `track_lost`, `track_reacquired`, `track_ended`.

Detections whose ground point lies inside an ignore region are dropped
before tracking.

### Rule engine

* Implicit rules: lines with `count`/`record` actions produce `crossing`
  events and counters; zones with measures produce `zone_entry`, `zone_exit`
  (with duration and speed), `dwell_exceeded` and `occupancy_exceeded`.
* Route groups: routes sharing a start object. Per track the group keeps
  progress per route; the first route whose end is reached with all
  checkpoints (or `strict_sequence=false`) wins. Outcomes: the route name,
  `UNKNOWN` (end reached without required checkpoints), `ABANDONED`
  (group timeout), `LOST_TRACK` (track removed while in progress).
  Context records occupancy at decision time, previous route in the group,
  zone occupancy at start, checkpoint times, decision time, switching and
  partial progress.
* Explicit rules: single trigger (`rule` event), sequences (`sequence` event
  with per-step `within_s` and overall timeout) and "remains for" dwell rules
  (`dwell` event), each with count/record/webhook/log actions.

### Analytics

Only reads stored rows. `run_summary` and `experiment_summary` compute route
distribution and behavioural measurements, crossings per line and direction,
zone dwell/occupancy, class distribution, media-time series and hourly
series; `evaluation_metrics` uses only manual verdicts and ground-truth
counts.

## Adding a detector provider

Implement `Detector` (`vision/detectors/base.py`): `load()`, `_detect(frame)`
returning `Detection` objects with canonical class names, and `class_names`.
Register the provider in `vision/detectors/__init__.py`, add catalog entries,
and extend `installed_providers()` if it depends on a new package.

## Adding a source

Implement `FrameSource` (`vision/sources/base.py`): `open()` returning
`SourceInfo`, `read()` returning `FramePacket` or `None`, `close()`, optional
`seek()`. Add it to `create_source()` and `SOURCE_TYPES`.

## Tests

```
.venv/bin/python -m pytest backend/tests -q
```

The suite covers geometry, both trackers (with synthetic camera-jolt and
crossing scenes for BoT-SORT), the spatial and rule engines with
synthetic tracks (route completion, unknown, abandoned, lost), and the API
with a temporary SQLite database. Tests that need model weights are skipped
when the weights are absent.

## Frontend notes

* All scene geometry is normalized; `SceneCanvas` converts to stage pixels
  through the `fit` rectangle and the zoom/pan view transform.
* Editor state lives in a zustand store with snapshot-based undo/redo. Drag
  operations call `beginDrag()` once and then mutate without history.
* Live frames arrive as a JSON meta message followed by a binary JPEG on the
  run WebSocket; `useLiveRun` pairs them and exposes tracks, events and status.
  `useCameraPreview` does the same for the preview WebSocket outside runs.
  Freezing keeps the last frame as the canvas background and disconnects, so
  the server releases the camera.
* `SceneCanvas.toNorm` snaps points within about 1 % of the image border onto
  it, so zones can reach the frame edge exactly.
* Charts use recharts with a fixed categorical palette (`components/charts.tsx`).

## Guides

The step-by-step guides live in `docs/guides` as Markdown with a small YAML
front matter (title, level, time, needs, summary, learn, pages). The app shows
the same files on the Guides page:

* `frontend/src/guides/content.ts` bundles every `NN-name.md` file at build time
  with `import.meta.glob`. The Vite dev server is allowed to read the repository
  root for this (`server.fs.allow` in `vite.config.ts`), and the Docker frontend
  stage copies `docs/guides` next to the frontend.
* `markdown.ts` is a small parser for the subset the guides use: front matter,
  headings with GitHub anchor ids, nested lists, fenced code, pipe tables,
  GitHub alerts (`> [!TIP]`) and inline code, bold, italic and links.
* `GuideArticle.tsx` renders a parsed guide. Top-level numbered lists become
  steps with tick marks. A bold sidebar page name such as `**Cameras**` becomes
  a link to that page, and links to other guides by file name stay in the app.
* `GuidePanel.tsx` docks a guide beside every page (Follow along). Reading
  state (done guides, ticked steps, the open guide) is kept in `localStorage`
  by `state.ts`.
* `content.test.ts` checks that the guides are numbered without gaps, have
  complete front matter, go from beginner to advanced, and that every link and
  anchor between them resolves. Run it with `npm test` in `frontend` after
  editing a guide.

The numbers a guide quotes for the sample videos were measured by running the
described setup. Re-measure them when a detector, tracker or engine change
could move them.

## Conventions

* Python: ruff (line length 100), type hints everywhere, structlog for logs.
* TypeScript: strict mode, no `any` outside API JSON blobs.
* Never present estimates as measurements; label them.
