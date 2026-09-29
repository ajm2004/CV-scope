# Privacy and research data

CV-Scope is built to answer questions about movement without identifying
anyone. The defaults below hold for every installation; the Settings page
shows the same list live for the current configuration
(`GET /api/system/privacy`).

## Stored by default

| Data | Stored | Detail |
| --- | --- | --- |
| Anonymous track ids | yes | Integers assigned by the tracker for one run; they restart at 1 for every run and cannot be linked across runs or cameras |
| Events | yes | Crossings, zone entries/exits, dwell and route outcomes with timestamps, object class, duration, speed and confidence |
| Track summaries | yes | Lifetime, path length, mean speed, final state per anonymous track |
| Sampled trajectories | yes (configurable) | Normalized ground-plane positions, up to 10 per second, used for review overlays and heatmaps |
| Uploaded source video | yes (configurable) | Kept in the data directory for review; never transmitted anywhere |
| Live camera video | no, unless an experiment records it | Frames are processed in memory and discarded. JPEG previews are streamed to the browser while a run or a live view is open, and are not stored. An experiment can turn on video recording (below) |
| Raw frames or crops | no | |
| Appearance summaries (BoT-SORT, optional) | no | When appearance matching is switched on, a short numeric summary of each object's appearance is held in memory only while it is tracked, to keep its anonymous id through occlusions within the run. Never written to disk, never compared across runs or cameras, discarded when the track ends |
| Faces, identities, cross-run re-identification | no | Not part of the open-source core. The licensed recognition modules (below) can match deliberately enrolled identities and registered plates; without a licence they are locked and the row stays "no" |

## Video recording (optional)

An experiment can record video of a live camera during its runs: clips around
events, or the whole run in files of up to an hour. It is off by default and
set per experiment under **Video recording**.

| Data | Where | Detail |
| --- | --- | --- |
| Video files (MP4 or WebM) | `<data>/recordings/run-<id>/` | The frames the run processed, optionally with boxes, anonymous track numbers, the scene objects, the clock time and event names drawn in. Never identities or plates of the recognition modules. A clip can cover one event, one whole visit from entry to exit, or the whole run. Played on the run's Video review page, downloadable, individually deletable |
| Recording rows | `recordings` | Run, kind, file, size, media and clock time span, and the events that started each clip |

**Video retention (days)** in Settings deletes recorded video that many days
after it was recorded (checked every hour); 0 keeps it until you delete it.
Deleting a run deletes its video, and files left behind by a deleted
experiment or project, or by a worker that crashed while writing, are removed
by the same hourly check. The Settings page lists the experiments that record,
the number of files and their size.

## Licensed recognition modules

The optional face and plate recognition modules (`docs/recognition.md`) are
proprietary extensions that stay locked without a signed licence. When
licensed they store, apart from the ordinary data:

| Data | Where | Protection |
| --- | --- | --- |
| Enrolled profiles (name, reference id, notes, validity, enrollment quality) | `recognition_people` | recognition access token (roles viewer / operator / administrator) |
| Face templates of enrolled people | `recognition_face_templates` | encrypted with a key kept in a file outside the database; never returned by an API, never logged |
| Enrollment images | `<data>/recognition/enrollment` | encrypted files; operators only; removed with the profile (immediately or after a configured grace period) |
| Vehicle registry | `recognition_vehicles` | access token |
| Recognition events (identity or plate, similarity, quality, model, camera, track, frame) | `recognition_events` | access token; configurable retention; individually deletable; export restricted to administrators and audited |
| Audit trail | `recognition_audit` | administrators |

Ordinary events of a recognized track carry only an opaque entity reference
(kind and stable id), never a name or a plate number, so the core API and the
ordinary exports stay free of personal data. A browser with a recognition
token can look those ids up (`POST /api/recognition/resolve`) and then sees an
Identity column next to the events and names on the live picture; the stored
event, the CSV, JSON and Parquet exports and every viewer without a token keep
the ids alone. The annotated live frame is produced twice, with and without
names, so an unauthenticated viewer cannot receive the named one. The test
bench (Recognition → Test recognition) reads a camera or a picture to check
whether recognition works and stores nothing by itself. Two operator actions
there do store something, both deliberate and audited: confirming a match
keeps that frame as an enrollment picture of that person (look *Live
confirmations*), and registering an unrecognized person creates a profile
through the ordinary guided capture. Verdicts (*correct*, *wrong*, *not
enrolled*) are written to the audit trail as a record of accuracy; they never
change a threshold or a template by themselves. No attribute such as ethnicity,
emotion, health, religion, age or gender is stored or inferred. The Settings
page's "What this installation stores" list reflects the modules' current
state.

## Relationships (optional)

When an experiment turns relationships on (`docs/relationships.md`),
CV-Scope also stores how tracks, identities and places relate: who stayed
near whom, which place was used next, which vehicle a person was observed
with. These records can reveal routines and associations that single
detections do not, so they have their own policy under **Relationships ›
Settings**:

* who may read them, see identities, export (with or without names), change
  rules and delete data (recognition token roles);
* whether face and plate results may feed the graph, and whether external
  sensors may publish observations;
* retention of relationship data, of identity links (default 30 days), and
  of the audit trail, enforced every hour;
* an audit trail of rule changes, analyses, exports, deletions, settings,
  and every view of an identity's relationships or history.

Identities are stored as opaque keys (enrolled id, vehicle id, a keyed hash
of the plate); names and plates are shown only to viewers with the identity
role. Relationships describe observable behaviour only; personal or
ownership relations are never inferred and can only be imported by an
administrator from an authorized registry. A language model is never used to
form relationships; if allowed, it may reword an anonymous summary.

Cross-camera correlation (`docs/locations.md`) joins sightings of the same
recognized person or plate on several cameras into journeys. A journey shows
where someone went, so moves based on identities are listed only for viewers
with the identity role, opening a journey or a last sighting is audited, and
stored texts never hold names or plates. Anonymous tracks are linked only if
you switch it on, by timing alone and never above *possible*. The location
model itself (plans, cameras, links) holds no personal data; floor plan
pictures stay in `<data>/locations/`, and no map tiles are loaded from the
internet.

## Configuration

* **Store sampled trajectories** (Settings → Storage, or
  `PATHSCOPE_STORE_TRAJECTORIES`): off means only events and summaries are
  kept; heatmaps and trajectory overlays are then unavailable.
* **Keep uploaded source videos** (`PATHSCOPE_KEEP_SOURCE_VIDEO`) is
  recorded, but not enforced yet: uploaded videos stay in the data directory
  until you delete them. **Video retention (days)** applies to video recorded
  from live cameras only.
* **Event retention (days)** (`PATHSCOPE_RETENTION_DAYS`) is recorded, but not
  enforced yet: events stay until you delete their runs, experiments or
  projects.
* **Webhooks** can be disabled globally; when enabled, only the event record
  (no image data) is posted to the configured URL.

## Exports

CSV, JSON and Parquet exports contain the event columns listed in
`docs/data-model.md`. They contain no images and no identifiers other than the
per-run anonymous track ids, which makes them suitable for sharing as
anonymized datasets.

## Interpretation

The platform records and analyses observable movement. Measurements such as
decision time, route switching, following a previous choice or route
occupancy at the moment of choice describe what happened in the scene; they
are not evidence of intent or psychological causes. Interpretation is the
researcher's responsibility, and the analysis pages say so.
