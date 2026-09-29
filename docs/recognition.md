# Licensed recognition modules: enrolled faces and vehicle plates

CV-Scope's open-source core tracks people and vehicles anonymously. Two
optional, proprietary modules extend it for authorised deployments:

* **Face recognition of enrolled identities.** Only people who were
  deliberately enrolled can be recognized. Everyone else stays an anonymous
  track. There is no unrestricted face search, no internet matching, no
  demographic or other attribute inference.
* **Vehicle plate recognition.** Plates are read with local models, combined
  over several frames, normalised through a configurable plate-format layer
  and optionally matched against a vehicle registry.

Both modules feed the existing rule engine through one entity layer, so a
rule can say *"Recognized Person is Employee-017 ENTERS Server Room AND
REMAINS FOR more than 5 minutes"* or *"Vehicle Plate equals ABC12345 CROSSES
Gate 2"* without any recognition-specific workflow logic.

The code lives in the repository (`backend/pathscope/recognition/`) so that the
core is built and tested with it, but **nothing runs without a valid
licence**. Everything is local: camera footage never leaves the machine and
model weights are downloaded once and cached.

## 1. Licensing and status

Status of each module, shown on Recognition → Settings and in `GET
/api/recognition/status`:

| Status | Meaning |
| --- | --- |
| Not licensed | No licence, an invalid or untrusted licence, or the module is not part of the licence. Nothing is recognized; rules with a recognition condition stay inactive. |
| Licensed | A valid licence includes the module and it is switched on. |
| Expired | The licence signature is valid but the expiry date has passed. Registries and events stay readable and deletable; enrollment and recognition stop. |
| Disabled | Licensed but switched off by an administrator (Recognition settings). |

### How a licence works

A licence is a small JSON file: a payload (licensee, issuer, issue and expiry
dates, modules, optional maximum number of cameras, optional machine binding)
plus an Ed25519 signature made with the issuer's private key. An installation
accepts a licence only when the signature verifies under one of its **trusted
issuer public keys**:

* `PATHSCOPE_RECOGNITION_ISSUER_KEYS` (comma-separated hex public keys), set
  at packaging time by whoever distributes the licensed build, or
* `*.pub` files in `<data>/recognition/issuers/`.

No key or secret is hard-coded. The open-source build trusts nobody, so the
modules are locked. Validation is fully offline; it fails closed on any
problem (malformed file, unknown issuer, tampered payload, wrong machine).

### Issuing a licence (vendor side, after reviewing a request)

```
cvscope recognition keygen --out issuer.key          # once; keep the file private
cvscope recognition issue --key issuer.key --licensee "Example Lab" \
    --modules face,plate --expires 2027-12-31 --max-cameras 4 \
    [--hardware-id <id from the customer>] --out example-lab.json
```

The customer sends the licensee name and, for a machine-bound licence, the
output of `cvscope recognition hardware-id`. Requests are reviewed for a
legitimate, authorised use case before a licence is issued.

### Installing a licence (customer side)

Recognition → Settings → Licence → paste the JSON, or
`cvscope recognition install example-lab.json`. If the issuer key is not
configured through the environment, register it first
(`cvscope recognition trust <public key hex>` or the *Trust key* form).
`cvscope recognition inspect FILE` shows what an installation thinks of a
file without installing it.

## 2. Access control, audit, encryption, retention

Recognition data is more sensitive than anonymous movement data, so the
modules bring stronger controls than the core:

* **Roles and tokens.** Every recognition endpoint except the public status
  needs a bearer token with a role: *viewer* (read events, registries and
  diagnostics), *operator* (viewer plus enroll, register, view enrollment
  images), *administrator* (everything: delete, settings, licence, tokens,
  exports, audit). Tokens are stored hashed and shown once. The first
  administrator token is created from the computer running CV-Scope
  (Recognition → Settings) or with `cvscope recognition token --role admin`.
  The browser keeps the token in local storage and sends it as
  `X-Recognition-Token`; WebSocket and image URLs use `?rtoken=`.
* **Audit trail.** Profile created, updated, re-enrolled, disabled, deleted;
  enrollment images added or removed; enrollment finalised; vehicles created,
  updated, deleted; licence installed or removed; settings changed; exports
  created; tokens created or revoked; events deleted; retention sweeps.
  Viewing images is deliberately not logged.
* **Encryption at rest.** Face templates (embeddings) are sealed with a key
  stored in a file outside the database (`<data>/recognition/keys`, or
  `PATHSCOPE_RECOGNITION_KEY_DIR` for another volume). Enrollment images and
  optional event crops are encrypted files. The construction is
  HKDF-SHA256 for key derivation, HMAC-SHA256 in counter mode as the
  keystream and an HMAC-SHA256 tag (encrypt-then-MAC), all from the Python
  standard library so the core needs no extra dependency to report status.
* **Templates stay put.** Raw embeddings are never returned by any API, never
  logged and never sent to the browser. Workers receive them in memory only.
* **Separate tables and API.** Recognition events are stored in
  `recognition_events`, apart from the ordinary `events` table. Ordinary
  events of a recognized track carry only an opaque reference
  (`context.entity = {"kind": "enrolled_person", "identity_id": ...}`),
  never a name or a plate number, so the unauthenticated core API and the CSV
  export of ordinary events stay free of personal data.
* **Retention** (Recognition settings): recognition events, unregistered
  plate reads and audit rows are removed after the configured number of days
  (0 keeps them); a background sweep runs at start and every six hours.
  Deleting a profile removes its templates immediately and its enrollment
  images immediately or after a grace period (quarantine). Individual
  recognition events can be deleted, as can whole runs or filters.
* **Restricted export.** Recognition events export (CSV or JSON) needs the
  administrator role and is audited.
* **Live overlays** show identities and plates only to viewers whose browser
  presents a recognition token; the MJPEG streams never carry them.

## 3. Face recognition

```
Frame -> Person detection (core) -> Face detection -> Face quality -> Face
alignment -> Embedding model -> Match against enrolled identities ->
Confidence / similarity check -> Recognition event
```

The face pipeline is separate from the object detector and tracker. It looks
at the head region of person tracks at a throttled rate (a few attempts per
second per track), scores every face for size, sharpness, exposure, contrast,
pose and obstruction, keeps the best observations of each track in a buffer,
and matches the quality-weighted aggregate embedding once enough usable
observations exist. Recognition is never recomputed every frame: once an
identity is associated with a track it is re-validated periodically, sooner
while a disagreement is open, and switched or cleared after two consecutive
contradictions (a tracker id switch). Tracks without a usable face are
settled as *Insufficient quality* after a timeout and keep being retried.

Outcomes: **Recognized** (similarity at or above the threshold and a margin
to the runner-up), **Possible match** (between the two thresholds, or the
margin is too small; rules do not act on it), **Unknown**, **Insufficient
quality**. Thresholds, the margin, minimum face size, quality, observation
counts, intervals and timeouts are central settings (Recognition → Settings,
advanced). Every decision records similarity, runner-up similarity, image
quality, number of observations, best frame, model version, timestamp,
camera, track id and frame.

### Model stacks

| Stack | Detector | Embedding | Licence | Runs on |
| --- | --- | --- | --- | --- |
| `opencv` (default) | YuNet 2023mar (OpenCV Zoo) | SFace 2021dec, 128-d (OpenCV Zoo) | MIT / Apache-2.0 | CPU through OpenCV DNN; no extra package |
| `insightface` | SCRFD-10G (InsightFace) | ArcFace ResNet-50 WebFace600K, 512-d (InsightFace) | code MIT, **weights for non-commercial research use only** | ONNX Runtime, GPU recommended |

The stack is chosen centrally and the components (detector, quality
estimator, alignment, embedding model, matcher) are separate interfaces
(`face/detector`, `face/quality`, `face/alignment`, `face/embeddings`,
`face/matcher`), so a model can be replaced later. Alignment is a five-point
similarity transform onto the ArcFace template; nothing is generated, and no
restoration or upscaling is applied before recognition, so no invented detail
can become identity evidence.

Measured on the development machine (CPU) with the public-domain sample
photo: YuNet 10 to 14 ms per 512 px image, SFace 7 ms per embedding;
same-person similarity 0.83 to 0.98 under blur, JPEG quality 30, darkening or
mirroring, against about 0 for a random texture. The default Recognized
threshold for SFace is 0.46 (OpenCV documents 0.363 for verification);
calibrate on your own site. Faces below the minimum size (40 px by default)
are not identified; on the sample corridor clip faces are about 20 px and stay
*Insufficient quality*.

### Enrollment

Views: front (required), left angle, right angle, from slightly above, from
slightly below, different lighting, and an optional rear view kept only as an
appearance reference (no face, no template). Every picture is checked before
it is accepted and the operator gets plain guidance: *Turn slightly left*,
*Move closer to the camera*, *Lighting too low*, *Hold still; the picture is
blurred*, *Face partially obstructed or cut off by the frame*, *More than one
face is visible*. Finalising computes the enrollment quality from view
coverage, image quality and the consistency between the person's own
embeddings; inconsistent or poor enrollments are refused. Profiles have an
internal id, display name, reference id, notes, active flag, optional
validity period, enrollment date, quality and model version, and can be
re-enrolled, disabled or deleted.

**Guided live capture** (Recognition → People → profile → *Guided*) is the
normal way to enroll at a live camera, and works like enrolling a face on a
phone: the picture appears in a circle with a ring of view segments around
it, the person follows one short instruction at a time, and each view is
stored the moment the pose and the picture are good enough. Nobody presses a
button per picture.

* The server analyses the shared camera preview about eight times a second
  (`/ws/recognition/enrollment/{person}`, operator role). It sends the
  picture, the instruction and the direction to point at; the browser only
  draws them.
* Instructions in order of what is in the way: *Look at the camera*, *Only
  one person in front of the camera, please*, *Move into the circle*, *Move a
  little closer*, *Move back a little*, *More light on the face, please*,
  *Too bright: move away from the light*, the pose instruction for the
  requested view, *Hold still*.
* A view is kept after three consecutive good observations spanning at least
  0.45 s, and the sharpest frame of that moment is the one stored, not the
  last one.
* **Pose is measured against the person's own front view.** The left, right,
  chin-down and chin-up views need a turn of roughly 25° or a nod of roughly
  12° *relative to that baseline*, so a camera mounted off to one side, or a
  model whose neutral pose reads differently (YuNet reports a pitch near 0
  where SCRFD reports about +0.3 for the same face), does not spoil the
  views. A front view stored earlier with the same model stack is used as the
  baseline when a session starts.
* Each captured view is compared with the front view before it is kept; a
  different face halfway through the session is refused with *This does not
  look like the same person as the front view*. The bar is the same minimum
  consistency the finished enrollment must reach, because a turned view of
  one person scores lower than a frontal one.
* The camera is opened only while the capture runs, through the same shared
  preview as the rest of the app; if an experiment is running on that camera,
  its frames are used instead of opening the device twice.
**Looks: the same person enrolled again.** One session captures the person as
they are that day. Glasses, a hard hat, a beard, a uniform or a very different
light can change the picture enough that one session misses them later, so a
profile may hold several *looks*: give the look a name (*Glasses*, *Night
shift*) and run the guided capture again. The new pictures are **added**, never
swapped in:

* Each look keeps its own set of views, so the guided plan starts again at the
  front view for a new look. The stored pictures and templates carry the look
  as a label (`variant`).
* Every template of every look is matched at run time, so the person is
  recognized whichever way they turn up. Matching uses the best template, so
  more looks can only help.
* Consistency is judged **inside** a look, because two looks of one face score
  lower against each other than two pictures of the same look. A later look
  must still match the first enrollment on its best pair, which is what stops a
  second person from being added by mistake; the enrollment summary reports
  that link per look.
* A look can be deleted on its own (Recognition → People → *Delete "Glasses"*).
  The first enrollment can only be removed by starting over (*Re-enroll*),
  which clears the whole profile.

* The **Single pictures** tab keeps the earlier flow: choose a view, capture
  one frame or upload a file, read the same guidance. Use it for cameras
  where nobody can see the screen, or to enroll from existing photographs.

## 4. Vehicle plate recognition

```
Vehicle detection (core) -> Plate detection -> Plate crop -> Preprocessing
-> OCR -> Character confidence -> Temporal consensus -> Plate normalisation
-> Validation -> Plate event
```

Works for cars, trucks, buses and motorcycles whose plate is visible. The
plate detector runs on the vehicle crop (small, distant plates are therefore
upscaled by the letterbox), the crop is scored for size, sharpness,
exposure and contrast, and the OCR returns every character with its own
confidence. Characters below the confidence floor are shown as `?` and are
never invented. Reads of a track vote per character position in a **temporal
consensus** (`DUB4?67`, `DUB4567`, `DUB4567` → `DUB4567`); only a complete,
confident consensus becomes a plate. Preprocessing is limited to cropping and
optional contrast normalisation (CLAHE); no generative enhancement.

| Component | Model | Licence |
| --- | --- | --- |
| Plate detector | YOLOv9-t 384 px end-to-end (open-image-models); 640 px and YOLOv9-s 608 px variants for distant plates | MIT |
| OCR | CCT-S v2 global (fast-plate-ocr): 10 character slots, per-character confidence, region head over 65 countries; CCT-XS v1 as a smaller option | MIT |

Any ONNX plate detector with an Ultralytics-style or end-to-end output and any
slot-classification OCR with a `plate_config.yaml` can be dropped in.
Measured on the development machine (CPU): detector 8 ms per vehicle crop,
OCR 2 to 5 ms per plate. Plates about 10 px tall in the sample street clip are
detected but stay below the 14 px minimum and are not read.

### Plate formats

`Raw OCR -> normalise characters -> candidate generation -> region-specific
parser -> validation`. A format is a regular expression with named groups
(country, emirate / state, category, series, number, prefix, suffix) plus
country and region metadata. Candidate generation swaps visually confusable
characters (O/0, I/1, B/8, S/5, Z/2, G/6, D/0, Q/0) in at most two positions
where the format's positional character class demands it: raw `DXB 12S67`
becomes `DXB12567` for the UAE format. Both the raw and the normalized text
are stored with the recognition event.

Built in: `generic`, `uae`, `uk`, `eu_generic`, `us_generic`. The enabled
formats and their order are a setting (`recognition.plate.formats`); keep the
formats of your site and put `generic` last, because an earlier format may
repair a text that a later one would accept as read. A plate registered
exactly as read always wins over a repair. Custom formats are a JSON list in
`<data>/recognition/plate_formats.json` (`id`, `name`, `country`, `pattern`,
optional `region`, `description`); an id equal to a built-in one overrides
it. Recognition → Vehicles has a tester for the format layer.

### Vehicle registry

Recognition → Vehicles: vehicle id, normalized plate, country, region,
vehicle type, description (the label shown in events), optional owner or
reference name, groups, active flag, notes. Registration is optional: plates
are read either way. Unregistered plates are recorded as plate observations
only when the deployment policy setting *Record plates that are not
registered* allows it, and are removed after their own retention period.

## 5. Entity layer and rules

Every track resolves to one entity (`backend/pathscope/domain/entities.py`):

```
Track #382   Object: person   Identity: Employee-017        enrolled_person
Track #917   Object: car      Plate: ABC12345               recognized_plate
                              Vehicle: Delivery Van 04      registered_vehicle
Track #204   Object: person   (nobody recognized)           anonymous_person
```

The core defines the interface (`EntityRef`, `EntityResolver`) and a null
resolver that keeps everything anonymous; the recognition runtime implements
it. Rules gained a **subject** clause (`RuleSubject`):

| Mode | People | Vehicles |
| --- | --- | --- |
| any | any person (the default) | any plate |
| anonymous | nobody recognized | no plate read / not registered |
| recognized | any enrolled identity | any plate read confidently |
| registered | – | plate of a registered vehicle, optionally in given groups |
| specific | listed identities | listed plates or registered vehicles |

The rule engine evaluates the subject when the event would be emitted
(single trigger, end of a THEN sequence, or when a *remains for* threshold
is reached). Recognition often arrives a little after the geometric trigger,
so an undecided event waits up to *Wait for recognition after a trigger*
(5 s by default) and is then emitted with its original timestamps or dropped;
*anonymous* fires when nobody was recognized by then. Rules whose module is
not active stay inactive (the run snapshot lists them) instead of matching
everyone: recognition fails closed. Events of recognized tracks, implicit or
explicit, carry the opaque entity reference in their context.

In the rule builder the clause appears under WHEN as **RECOGNITION** (Any
person / Anonymous person / Recognized person / Specific enrolled person) or
**PLATE** (Any plate / Recognized plate / Registered vehicle / Specific plate).
Examples:

```
WHEN Person  RECOGNITION is Employee-017  ENTERS Server Room  AND REMAINS FOR more than 300 s
     CREATE EVENT Extended Server Room Presence
WHEN Car     PLATE equals ABC12345         CROSSES Gate 2       RECORD AS Vehicle Arrival
WHEN Car     PLATE Registered vehicle, group Delivery Fleet  ENTERS Loading Area
WHEN Person  RECOGNITION is Person X       CROSSES Checkpoint A  THEN CROSSES Checkpoint B  RECORD AS Configured Route
```

## 6. Testing recognition, and where names are shown

### Test bench (Recognition → Test recognition, operator)

Recognition is only as good as the enrollment and the camera, so the modules
ship with a bench that answers three questions and stores nothing:

* **Live camera** — the camera picture with a box and a label over every face,
  refreshed about four times a second (`/ws/recognition/test/live`). Each face
  shows the verdict (*Recognized*, *Possible match*, *Unknown*, *Insufficient
  quality*), the best candidate and its similarity, the runner-up, the face
  size in pixels and the thresholds in force, so a wrong answer can be traced
  to the camera, the picture or the enrollment.
* **A picture** — the same for an uploaded photograph or one frame taken from
  any camera, including a video file's camera.
* **Enrollment check** — every profile compared with its own pictures and with
  everyone else: templates, views, looks, how well the person's own pictures
  agree, the nearest other person and a verdict (*Healthy*, *Needs more*,
  *Mix-up risk*, *Not matched*) with what would help. Two people above the
  Possible-match threshold are flagged, because those are the two who can be
  confused for each other.

The bench runs the same detector, quality gate, alignment, embedding and
matcher a run uses. By itself it stores nothing and returns no embedding; only
an answer from the operator writes anything.

### Answering the bench: confirm, correct, register

While the live test runs it asks about the face on screen, at most once every
20 seconds per person:

* **Is this <name>?** → *Yes, correct* records the verdict and, with the tick
  box left on, keeps that frame as an enrollment picture of that person under
  the look **Live confirmations**. The profile is finalised again at once, so
  the new picture counts from the next run on. This is how a profile grows
  into the light, angle and clothing the camera really sees.
* **No** → the verdict is recorded and the operator can say who it really was
  (that person gets the picture instead), or that the person is not enrolled.
* **Not recognized. Register this person?** appears for a good face nobody
  matches. It creates the profile and runs the guided capture (front, left,
  right, chin down, chin up) in place, on the same camera, and the test
  continues against the new profile immediately.

A picture is only added when the operator says so, it passes the ordinary
enrollment gate, and it is compared with that person's own templates first: a
face below the enrollment consistency is refused with the reason, and can only
be added by confirming again, which is recorded as `forced` in the audit trail.
Nothing here is model training: no threshold moves by itself, and the verdicts
are a record of how often this installation is right on this site. `GET
/test/feedback` returns those counts and the recent answers.

Registration from the bench is as deliberate as any other enrollment: an
operator types the person's name and the person poses for the camera. The
module still cannot search for anyone who was not enrolled.

### Where a recognized name appears

Names are shown to a browser that holds a recognition access token, and
nowhere else. The stored data does not change:

| Place | What a viewer without a token sees | With a token |
| --- | --- | --- |
| Live page video (MJPEG) | box and `#id class` | the label also carries `= Name` or `? Name` for a possible match |
| Live page, *Recognized now* | nothing | track, class, name or plate and confidence (`GET /live/{run}/tracks`) |
| Scene Builder live overlay | anonymous track | `= Name` (unchanged) |
| Data, run analysis events, video review, clips | the event's opaque `context.entity` | an **Identity** column, resolved through `POST /resolve` |
| CSV / JSON / Parquet export | ids only | ids only — exports never carry names |
| Recognition events page | (needs a token anyway) | name, similarity, quality, camera, track, frame |

The annotated live frame is cached twice per preview frame, once plain and
once with names, so an unauthenticated viewer can never receive the named one.
`POST /resolve` maps the ids in stored events to names for the current viewer;
it reads the registry only and adds nothing to the event.

## 7. Diagnostics

Recognition → Recognition events shows, for every active run and track:
faces: face detected, quality (and why it was rejected), observations seen /
usable / kept, best frame, candidate, similarity and runner-up, result,
identity, model; plates: plate detected, last raw OCR, temporal consensus
(text, reads, complete or not), normalized plate, confidence, vehicle, result.
The run's counters (attempts, usable observations, decisions, recognized,
unknown, insufficient) are recorded with the run statistics. Timings of the
models on this machine: Recognition → Settings → Benchmark.

## 8. Hardware and Model Manager

The recognition models appear on the Models page with task, module, backend,
VRAM and RAM needs, CPU and GPU suitability, size, licence and install
state, and are downloaded on demand into `<models>/recognition`. The
InsightFace pack (275 MB) is cached under `<models>/_archives` so both of its
models come from one download; only the detector and the embedding model are
extracted, never the pack's gender/age model. The installer rejects Git LFS
pointer files.

The Hardware page estimates the effect of enabling the modules on the number
of camera streams (full pipeline: person detector + tracker + face detector +
face quality + face embedding + matcher, or vehicle detector + tracker +
plate detector + OCR + consensus) and warns when the capacity drops
substantially. The estimate uses the hardware class until a benchmark exists.
Presets AUTO / FAST / BALANCED / ACCURATE / CUSTOM keep working unchanged;
the modules add their own cost on top of the chosen detector. With the
`opencv` face stack the face models always run on the CPU; the ONNX stacks
use the GPU when ONNX Runtime has a CUDA provider.

## 9. Installation notes

* The `opencv` face stack needs nothing beyond the core. The plate models and
  the `insightface` stack need ONNX Runtime (`onnx-cpu` or `onnx-gpu` extra).
* Set `PATHSCOPE_RECOGNITION_ISSUER_KEYS` in the licensed build (or register
  the key on the installation), install the licence, create the first
  administrator token, install the models, adjust the settings, enroll.
* Deployment stays fully local; model weights are downloaded from the
  projects' GitHub releases (OpenCV Zoo, open-image-models, fast-plate-ocr,
  InsightFace) once. Check the licence column before distributing a product:
  the InsightFace weights are for non-commercial research only.

## 10. API summary (`/api/recognition`)

| Endpoint | Role | Purpose |
| --- | --- | --- |
| `GET /status` | public | module states, licence summary, access bootstrap state, model readiness |
| `POST/DELETE /license`, `POST /license/trusted-keys` | admin | install or remove a licence, trust an issuer key |
| `POST /access/bootstrap` | loopback, no tokens yet | first administrator token |
| `GET /access/me`, `GET/POST/DELETE /access/tokens` | viewer / admin | tokens |
| `GET/PUT /settings` | operator / admin | central settings and definitions |
| `GET/POST /people`, `GET/PUT/DELETE /people/{id}`, `/disable`, `/enable`, `/reenroll` | viewer / operator / admin | profiles |
| `POST /people/{id}/enrollment/analyze`, `/images`, `/capture`, `/finalize`, `GET/DELETE .../images/{id}[/file]` | operator | enrollment from single pictures |
| `WS /ws/recognition/enrollment/{id}?camera_id=&rtoken=&variant=` | operator | guided live capture: `ready`, `frame`, `analysis`, `captured`, `note`; `variant` is the look |
| `DELETE /people/{id}/enrollment/looks/{look}` | operator | remove one look with its pictures and templates |
| `POST /resolve` | viewer | names for the opaque entity ids in ordinary events |
| `GET /live/{run_id}/tracks` | viewer | what an active run recognizes right now, per track |
| `POST /test/identify`, `POST /test/identify/camera` | operator | try a picture or one camera frame; nothing is stored |
| `GET /test/enrollment` | operator | strength of every enrolled profile and what would improve it |
| `POST /test/teach` | operator | add a confirmed picture to a profile (look *Live confirmations*) |
| `GET/POST /test/feedback` | operator | the operator's verdicts on what the bench showed, and their counts |
| `WS /ws/recognition/test/live?camera_id=&rtoken=` | operator | live test: `ready`, `frame`, `result`; commands `feedback`, `confirm`, `reload` |
| `GET/POST /vehicles`, `GET/PUT/DELETE /vehicles/{id}`, `GET /vehicles/groups`, `POST /plates/parse` | viewer / operator / admin | registry and format tester |
| `GET /events`, `GET /events/{id}[/crop]`, `DELETE /events/{id}`, `POST /events/delete`, `GET /events/export` | viewer / admin | recognition events |
| `GET /diagnostics/active`, `GET /diagnostics/runs/{id}` | viewer | live diagnostics |
| `GET /audit` | admin | audit trail |
| `POST /benchmark` | admin | local model timing |

## 11. Module boundaries

```
backend/pathscope/recognition/
  common/       types, quality measures, observation buffer, crypto, config, access, audit, onnx
  licensing/    ed25519.py (pure Python), license.py (files, trusted issuers, status)
  face/         detector/ (yunet, scrfd) alignment/ quality/ embeddings/ (sface, arcface_onnx) matcher/
                enrollment/ (guidance.py: instructions and relative pose; live.py: the guided
                session state machine) pipeline.py stack.py
  plate/        detector/ (onnx_yolo) preprocessing/ ocr/ (onnx_slots) parser/ (formats, registry) temporal/ (consensus) pipeline.py stack.py
  registry/     models.py (tables) store.py (encryption) people.py vehicles.py
  events/       recorder.py (events, export, retention) retention.py (background sweep)
  api/          routes.py schemas.py live.py (the guided-capture WebSocket)
  runtime.py    the per-run runtime; implements EntityResolver for the rule engine
  service.py    the facade the core calls (status, run payload, privacy rows, capacity)
  catalog.py    model catalog entries
```

The open-source core touches the modules only through: the model catalog
(`recognition_models()`), the run payload (`service.build_run_payload`), the
pipeline hook (`Pipeline` builds the runtime from the payload), the event
recorder (`events.recorder.record_events`), the API router, the privacy rows
and the capacity estimate. The rule engine knows only the entity interface
in `domain/entities.py`.

## 12. Limits

The face module is for deliberately enrolled identities in authorised
deployments. It does not and will not search public spaces for unknown
people, match against the internet, infer ethnicity, emotion, health,
religion, age, gender or any other attribute, or discover identities
automatically. Unknown people remain anonymous tracks, and the
privacy-preserving defaults of the open-source core are unchanged.
