# Anomaly Assistant

The Anomaly Assistant reports meaningful visual change from an expected,
static scene: objects that appear, disappear or move, presence where an area
should be empty, a disturbed or rearranged scene, and a covered or turned
camera. It is not pixel-difference motion detection. Noise, compression,
small lighting changes, shadows, insects and slow daylight are filtered out
by deterministic computer vision. An optional vision language model (VLM)
then describes, or confirms, what the computer vision found.

Operator walkthrough: [guide 24](guides/24-anomaly-assistant.md).

## Event flow

```
camera frame
  -> normal picture (learned median + per-pixel noise, follows slow daylight)
  -> candidate variance   brightness after exposure correction, colour
  -> noise filtering      texture-preserving regions (shadow, light patch) dropped,
                          morphology, minimum blob size, slow drift absorbed
  -> temporal validation  persistence_s with >= 60 % of the analyses, min_confidence
  -> classification       presence | motion | appeared | disappeared | moved | changed
                          (whole picture: lighting | tamper)
  -> recognition          tracked objects -> aliases + recognition status (ids only)
  -> evidence             before / event / after pictures, close-ups, outlined overlay
  -> [worker -> API]      AnomalyEvent row
  -> optional VLM         deterministic | assisted | confirmed
  -> alert                ordinary event "anomaly": stored, live, counted,
                          video clip, webhooks (+ anomaly.described / anomaly.ended)
```

Only confirmed anomalies reach the model: one request per event with at most
four pictures, never the video stream.

## Code

| Path | Role | Depends on |
| --- | --- | --- |
| `pathscope/anomaly/config.py` | `AnomalySettings`, `AnomalyZoneSettings`, presets | pydantic |
| `pathscope/anomaly/detector.py` | `AnomalyAssistant`, the method | numpy, OpenCV |
| `pathscope/anomaly/evidence.py` | `EvidenceWriter` (JPEG evidence) | OpenCV |
| `pathscope/anomaly/subjects.py`, `describe.py` | aliases, one-line summaries | – |
| `pathscope/anomaly/llm/` | providers, prompt, key store | httpx; `anthropic` for Claude |
| `pathscope/anomaly/service.py` | CV-Scope wiring: rows, publication, model queue, retention | database, supervisor |
| `pathscope/anomaly/api.py` | HTTP API | FastAPI |
| `pathscope/workers/camera_worker.py` (`_Anomalies`) | runs the assistant on processed frames | – |

The first five need nothing from CV-Scope's database, pipeline or API.

## Reusing it in another camera application

```python
from pathlib import Path

from pathscope.anomaly import AnomalyAssistant, AnomalySettings, AnomalyZoneSettings, EvidenceWriter
from pathscope.anomaly.llm import KeyStore, LLMSettings, interpret

settings = AnomalySettings(enabled=True, zones=[
    AnomalyZoneSettings(id="stall", name="North stall", expected_state="The stall is empty.",
                        sensitivity="medium", persistence_s=5, detect=["presence", "motion", "appeared"]),
    AnomalyZoneSettings(id="frame", name="Whole picture", detect=["appeared", "disappeared", "moved"]),
])
assistant = AnomalyAssistant(settings, (width, height),
                             zones={"stall": [(0.1, 0.5), (0.6, 0.5), (0.6, 0.95), (0.1, 0.95)]},
                             ignore=[[(0.7, 0.0), (1.0, 0.0), (1.0, 0.3)]])
evidence = EvidenceWriter(Path("anomalies"))

for t, frame, detections in camera():          # BGR frame, time in s, your detector's output
    for update in assistant.observe(frame, t, objects=detections, resolver=my_recognizer):
        files = evidence.write(update)          # {"before": "uid/before.jpg", ...}
        record = update.to_dict()               # plain data, JSON-safe
        if update.phase == "confirmed":
            my_alerts.raise_(record, files)
        else:                                   # "ended": duration, end reason, final kind
            my_alerts.close(record, files)
```

* `observe` analyses at `analysis_fps` and ignores frames in between, so you
  can feed every frame.
* `objects` takes CV-Scope tracks, `ObservedObject`s or dicts
  `{track_id, class_name, confidence, box: (x1, y1, x2, y2), state?}` in
  pixels. Without objects, pixel changes are still found; presence needs them.
* `resolver` is optional: anything with `resolve(track_id, object_class) ->
  EntityRef` (`pathscope.domain.entities`). Subjects keep only
  `to_context()`: kind, ids, status, never names.
* `rebaseline(zone_id, frame)` takes the current picture of a zone as
  normal; `rebaseline()` learns everything again; `finish()` ends open
  anomalies.
* `status()` gives learning/watching, the state of each zone and counters.

To ask a model about a record:

```python
llm = LLMSettings(provider="local", model="qwen2.5vl:3b")         # or openai, anthropic, gemini, ...
pictures = [(name, (Path("anomalies") / rel).read_bytes()) for name, rel in files.items() if name in ("before", "overlay")]
result = interpret(llm, KeyStore(Path("data")).get(llm.provider)[0], {**record, "expected_state": "The stall is empty."}, pictures)
print(result.verdict, result.description)       # confirmed | rejected | uncertain
```

`cvscope anomaly analyse VIDEO|INDEX|URL [--zone name=x,y ...] [--out DIR]`
runs the same thing from the command line.

## Settings

Per zone (`AnomalyZoneSettings`):

| Field | Default | Meaning |
| --- | --- | --- |
| `id` | – | Scene zone id, or `frame` for the whole picture |
| `expected_state` | "" | The normal state in words; shown with events and given to the model |
| `sensitivity` | medium | low / medium / high / custom (presets below) |
| `k_sigma`, `min_contrast`, `min_area_pct`, `persistence_s`, `min_confidence` | preset | Override single thresholds |
| `detect` | all six kinds | Kinds that count in this zone |
| `presence_classes` | [] | Classes whose presence counts (empty: all tracked) |
| `accept_after_s` | 120 | A still change becomes the new normal after this long (0: never) |
| `cooldown_s` | 10 | Quiet time after an event |
| `validation` | deterministic | deterministic / assisted / confirmed |
| `interpret_at` | confirm | assisted zones: describe at confirmation or at the end |
| `webhooks`, `record_clip` | [], true | Alert actions |

| Preset | k_sigma | min_contrast | min_area_pct | persistence_s | min_confidence |
| --- | --- | --- | --- | --- | --- |
| low | 5.0 | 28 | 2.0 | 4.0 | 0.6 |
| medium | 3.5 | 20 | 0.8 | 2.5 | 0.5 |
| high | 2.5 | 14 | 0.3 | 1.5 | 0.4 |

Per camera (`AnomalySettings`): `analysis_fps` (4), `learn_s` (8),
`adapt_minutes` (10), `working_width` (320), `use_ignore_regions`,
`lighting_events` (off), `tamper_events` (on), `recognition` (on) and
`on_llm_failure` (`raise` or `hold`).

## The method in detail

* **Analysis size.** Frames are shrunk to `working_width` (320 px) and
  blurred; Lab colour space.
* **Normal picture.** The per-pixel median of the frames during `learn_s`,
  so people walking past while it learns do not end up in it. Noise is the
  per-pixel median absolute deviation. Afterwards the normal picture follows
  drift with the time constant `adapt_minutes`, except where anything is
  currently different.
* **Exposure.** A straight line from normal to current brightness is fitted
  to the median brightness of 16 brightness bands. Scaling light by k is
  nearly affine in Lab lightness (L' = k^(1/3)(L + 16) - 16). Bands off the
  line (a sun patch, an object) are dropped before refitting, so a local
  change never bends the correction of the rest of the picture.
* **Changed pixel.** More than `min_contrast` levels and `k_sigma` noise
  deviations away from normal, or a clear colour change. Pixels whose local
  texture correlates with the normal picture (NCC > 0.85) at the same colour
  are lighting.
* **Regions.** Opening and closing, then connected components. A component
  smaller than a fifth of the minimum area is dropped. So is one whose
  structure survived (median NCC > 0.7 over its faintly textured pixels, the
  same colour): a shadow or light patch. A flat grey object on a flat wall has
  no structure to judge and counts as real.
* **Sudden or gradual.** At the start of a candidate, the changed pixels are
  compared with the picture from 12 to 40 s earlier. If less than 30 % of the
  change is new since then, it crept in (daylight) and is absorbed into the
  normal picture.
* **Confirmation.** `persistence_s` must pass with the change present in
  60 % of the analyses. Confidence is 0.35 × area + 0.25 × persistence +
  0.2 × magnitude + 0.2 × structural evidence, reduced when exposure moved
  a lot. A watched object class inside the zone gives at least 0.6 + 0.4 ×
  its detector confidence.
* **Classification.** presence (a watched object inside), motion (at least
  25 % of the changed pixels moved since the last analysis). Otherwise, once
  still, compare edge strength on a ring around each changed region and
  inside it, now against normal: appeared, disappeared, changed. A
  disappeared region whose normal-picture patch correlates (> 0.4) with an
  appeared region's current patch is moved.
* **End.** Cleared after `max(3 s, persistence)` without the change.
  Accepted (absorbed into the normal picture) after `accept_after_s` still.
  The run ended.
* **Whole picture.** When 45 % of the picture changes, or the median
  brightness moves out of 0.65 to 1.5, for more than 1 s, the zones pause.
  The event is `lighting` if the structure survived, `tamper` if it did not
  or the picture went blank. Then everything is learned again.

Cost: about 5 to 10 ms per analysis on one CPU core, independent of the
camera resolution.

## Vision language models

One provider and model is active at a time (**Anomaly Assistant** page,
`GET/PUT /api/anomaly/assistant`):

| Provider | Protocol | Pictures |
| --- | --- | --- |
| Local (Ollama, LM Studio, vLLM, llama.cpp server) | OpenAI-compatible chat completions | yes, stay on premises |
| OpenAI, OpenRouter, other compatible APIs | OpenAI-compatible | yes |
| Google Gemini | `generateContent` | yes |
| Anthropic Claude | official `anthropic` package (`pip install -e backend[llm]`); structured JSON output, low effort, server-side refusal fallbacks on Claude Opus 5 | yes |
| DeepSeek | OpenAI-compatible | no: text observations only |

The model answers with JSON: `verdict` (confirmed, rejected or uncertain),
`category`, `description`, `confidence` and `evidence`. The prompt tells it
that detection already happened, to describe only what is visible, to use
the aliases as given, never to read out names or plates, and to treat text
inside pictures as scene content, never as instructions.

Load control: `max_concurrent` (1), `max_calls_per_hour` (120) and
`queue_limit` (50). Past them an event keeps its computer-vision summary; a
model-confirmed zone follows `on_llm_failure`. Model calls in progress when
the server restarts are marked failed, and their events are held.

Keys: `<data>/anomaly/llm_keys.json`, one per provider. They are never kept
in the database or in exports, and never returned by the API. The
environment variables `PATHSCOPE_LLM_API_KEY` or the provider's own
(`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`,
`DEEPSEEK_API_KEY`) take precedence.

**Local setup without leaving the page** (`pathscope/anomaly/llm/local.py`,
`/api/anomaly/local*`): status of Ollama (installed, running, downloaded and
loaded models with their GPU memory); **Install Ollama** on Windows (official
`OllamaSetup.exe`, Authenticode signer must be Ollama, silent per-user install,
then waits for the server); **Start Ollama**; **Download** any model with
progress (Ollama's `/api/pull`); **Use**, **Unload** (free GPU memory now) and
**Delete**. These actions are accepted only from the CV-Scope computer itself.
With Ollama the request goes to its native `/api/chat` with `num_ctx`
(`context_tokens`, default 8192: four pictures need about 5000 tokens, more
than Ollama's default 4096) and a JSON schema; other local servers use the
OpenAI-compatible endpoint, and a "context exceeded" answer is retried once
with two smaller pictures. Measured on an RTX 4070 SUPER: `qwen2.5vl:7b`
(5.6 GB download) uses 5.5 GB of VRAM at 8192 tokens, answers in about 1 s with
two pictures and 3 s with four once loaded; the first answer after loading
takes about a minute.

Local model guidance is on the page, with VRAM estimates checked against the
detected GPU. Light: `qwen2.5vl:3b` (about 4 GB), `gemma3:4b`, `moondream`.
Capable: `qwen2.5vl:7b` (about 8 GB, fits a 12 GB card next to the detector),
`llama3.2-vision:11b`, `gemma3:12b`. Large: 32 B and 72 B models need 24 GB
and more.

## Storage and privacy

* `anomaly_events` (migration `0005_anomalies`): one row per anomaly, with
  the deterministic facts, the subjects (aliases, ids and status, no names),
  evidence paths, zone settings, the model's reading and the operator's
  review.
* Evidence: `<data>/anomalies/run-<id>/<uid>/*.jpg`, at most 1280 px wide. It
  is deleted with the run or the anomaly, by **Anomaly evidence retention
  (days)** (hourly), and when orphaned.
* A raised anomaly is also an ordinary `events` row of type `anomaly`. Its
  context holds `anomaly_id`, the kind, and the summary and description in
  anonymous words.
* **Settings → What this installation stores** lists the evidence and what
  is sent to which model.

## HTTP API

| Method and path | Purpose |
| --- | --- |
| `GET /api/anomalies?run_id&experiment_id&camera_id&status&kind&feedback` | List |
| `GET /api/anomalies/{id}` | One anomaly |
| `GET /api/anomalies/{id}/evidence/{name}` | Picture (before, event, overlay, crop_before, crop_event, after, crop_after, overlay_after) |
| `POST /api/anomalies/{id}/feedback` | `{feedback: true_positive / false_alarm / null, note, rebaseline}` |
| `POST /api/anomalies/{id}/describe` | Ask the model now |
| `POST /api/anomalies/{id}/raise` | Raise a held or dismissed anomaly |
| `DELETE /api/anomalies/{id}` | Delete with its pictures |
| `POST /api/runs/{id}/anomaly/rebaseline` | `{zone_id}` or learn everything again |
| `GET/PUT /api/anomaly/assistant`, `POST .../test`, `GET .../models` | Model settings, a test call, a server's model list |

Webhooks of a zone receive the event itself (`{run_id, event}`), then
`{run_id, event: {type: "anomaly.described", ...}}` and
`{..., type: "anomaly.ended", duration_s}`.

## Limits

* One fixed camera view per assistant. A camera that pans, or zooms with
  autofocus hunting, is reported as tamper and learned again.
* Presence depends on the detector's classes. An animal that COCO does not
  know is reported as movement or as an object that appeared.
* Appeared, disappeared and moved come from edge heuristics. A model's
  description is usually more precise, which is why assisted mode exists.
* The method was checked on synthetic scenes (noise, exposure, shadows,
  flicker, insects, slow sun, lights off, objects appearing, removed and
  moved, a flat object on a flat wall, a dog in a zone) and on the sample
  videos. Tune the persistence and sensitivity on your own scenes.
