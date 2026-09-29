# Relationship & Event Correlation Engine

CV-Scope's relationship engine connects what the cameras observe into
time-bounded, confidence-scored relationships, and correlates them into
higher-level events:

```
Person track #92   IDENTIFIED_AS         Recognized person (Employee-017)
Vehicle track #51  IDENTIFIED_BY_PLATE   License plate
License plate      REGISTERED_AS         Registered vehicle (Delivery Van 04)
Vehicle track #51  PARKED_IN             Parking Zone        0:12 - 3:40
Person track #92   APPROACHED            Vehicle track #51   1:05 - 1:14
Person track #92   ASSOCIATED_WITH       Vehicle track #51   1:14 - 1:32  (likely, 88 %)
Person track #92   ENTERED_VEHICLE       Vehicle track #51   1:33
Vehicle track #51  CROSSED               Gate West           1:58
=> correlated event "Departed with vehicle" (supported by the four facts above)
```

It is not an alert system. It builds a structured record of *who or what*
was *where*, *with what*, *when*, with the evidence for every link. Alerts,
webhooks and recorded events are optional actions of the rules.

**Design principle.** Every relationship comes from a deterministic rule, a
measurement, a recognition result, a sensor observation or a configured
pattern. A language model never creates one. It may only reword a summary
of facts the engine already stored, if an administrator allows it.

Across several cameras - the location model, cross-camera correlation,
journeys, the site view and the interactive time-aware graph - see
`docs/locations.md`.

## Contents

1. [Concepts](#concepts)
2. [Pipeline](#pipeline)
3. [Entities and identity resolution](#entities-and-identity-resolution)
4. [Relationship types](#relationship-types)
5. [Rules](#rules)
6. [Measurements: calibrated and uncalibrated](#measurements-calibrated-and-uncalibrated)
7. [Confidence](#confidence)
8. [Correlation and time](#correlation-and-time)
9. [Patterns and deviations](#patterns-and-deviations)
10. [Versioning and re-analysis](#versioning-and-re-analysis)
11. [Storage and the graph API](#storage-and-the-graph-api)
12. [Privacy and access control](#privacy-and-access-control)
13. [Sensors and external registries](#sensors-and-external-registries)
14. [HTTP API](#http-api)
15. [Limitations](#limitations)

## Concepts

| Term | Meaning |
| --- | --- |
| **Entity** | A node: a track, an identity (recognized person, license plate, registered vehicle), a place (zone, gate, route), a camera, sensor, experiment or event |
| **Observation** | A normalized fact about one entity at one time, from one source: appeared, entered, crossed, recognized, plate read, sensor measurement... |
| **Relationship** | A typed, directed, time-bounded edge between two entities with a confidence, a state, the rule version that formed it and its supporting observations |
| **Correlated event** | A higher-level event made from several relationships and observations by a sequence rule; it links its evidence, it never replaces it |
| **Deviation** | A correlated event of kind `deviation`: an observed departure from a configured expectation or from an identity's own history |
| **Analysis** | One interpretation of one run: the live one, and any later re-analysis with other rules. One is *current* |

## Pipeline

```
camera / video / sensor
  -> detector + tracker                       (vision)
  -> recognition modules (licensed)           (face, plate)
  -> spatial engine: zones, lines, routes     (interactions)
  -> rule engine: ordinary events             (counts, routes, dwell)
  -> relationship engine                      (pathscope/relationships/engine.py)
       observations -> identity resolution -> relationship rules
       -> relationships -> correlation rules -> correlated events
  -> relationship service (API process)       storage, pattern deviations, actions
  -> graph API, explorer, timeline, search, rule clauses, exports
```

The engine runs inside the camera worker for live runs (in step with the
frames, so rules can use it immediately), and in the API process when a
stored run is analysed again. It depends only on the normalized inputs:
tracked boxes, the spatial engine's interactions, the rule engine's events
and the `EntityResolver` interface of the recognition modules. It never
imports a detector, tracker or recognition model.

Code layout (`backend/pathscope/relationships/`):

| Module | Role |
| --- | --- |
| `entities.py` | Entity types (registry) and keys |
| `observations.py` | Observation types (registry) and the `Observation` record |
| `relations.py` | Relationship-type registry; refuses non-observable types |
| `spatial.py` | Distances (metres or frame widths), footprints, motion history |
| `temporal.py` | Interval relations: PRECEDED, FOLLOWED_WITHIN, OVERLAPPED_WITH... |
| `confidence.py` | Evidence components, score, state |
| `rules.py` | Rule format, experiment settings, templates |
| `correlation.py` | Sequence matcher; following through checkpoints |
| `engine.py` | The per-run engine (no database) |
| `replay.py` | Re-analysis of stored runs |
| `models.py`, `store.py` | Tables and persistence |
| `graph.py` | Graph API: neighbours, subgraph, timeline, history, search; the presenter that applies access rules |
| `patterns.py` | Deviations from expectations and history |
| `summary.py` | Deterministic summaries; optional model rewording |
| `access.py` | Roles, identity visibility, audit, settings |
| `service.py`, `api.py` | CV-Scope wiring and the HTTP API |

## Entities and identity resolution

Entity keys are `<type>:<reference>`. Tracks are `person_track:r12.t182`
(run 12, track 182). Identities never carry a name or plate in their key:

| Type | Key | Label for viewers without identity access |
| --- | --- | --- |
| `recognized_person` | enrolled identity id | Recognized person |
| `license_plate` | keyed hash of the normalized plate (key in `<data>/relationships/plate.key`) | License plate |
| `registered_vehicle` | vehicle registry id | Registered vehicle |

Recognition does not replace the track. The track stays an entity and gets
an identity link:

```
Person track #182   IDENTIFIED_AS        recognized_person:<id>     (face module, confidence)
Vehicle track #91   IDENTIFIED_BY_PLATE  license_plate:<hash>       (plate module)
license_plate:<h>   REGISTERED_AS        registered_vehicle:<id>    (vehicle registry)
```

A face *possible match* is never an identity (as everywhere in CV-Scope).
When the recognized identity of a track changes, the old link is closed and
a new one opened.

An identity can also come from a person rather than a module: a stored
recognition event with `context.method = "annotation"` (a reviewer's
identification, for example the ground truth of a study). Re-analysing the
run turns it into the same identity link, with the source `annotation` and
the reason "A reviewer identified ... (manual annotation, not face
recognition)"; cross-camera moves built on it say so too (`docs/locations.md`).

Graph queries on an identity are *projected*: the identity's neighbourhood
is the union of the neighbourhoods of its tracks (identity links of at least
`likely`), and the other side is lifted to its identity too. Every projected
relationship says which track it came through (`via`). Only viewers allowed
to see identities get projections.

New entity, observation and relationship types can be registered in code;
user-defined relationship types are managed in **Relationship settings**.

## Relationship types

| Category | Types |
| --- | --- |
| Identity | IDENTIFIED_AS, IDENTIFIED_BY_PLATE, REGISTERED_AS (recognition results only) |
| Spatial | NEAR, APPROACHED, MOVED_AWAY_FROM, STOPPED_NEAR |
| Movement | FOLLOWED, TRAVELLED_WITH, ARRIVED_WITH, DEPARTED_WITH |
| Person and vehicle | ENTERED_VEHICLE, EXITED_VEHICLE, ASSOCIATED_WITH |
| Places | ENTERED, EXITED, CROSSED, OCCUPIED, REMAINED_IN, MOVED_FROM, MOVED_TO, USED_ROUTE, PARKED_IN |
| Time | PRECEDED, PRECEDED_BY, FOLLOWED_AFTER, FOLLOWED_WITHIN, OVERLAPPED_WITH, STARTED_AFTER, ENDED_BEFORE |

The engine describes observable behaviour only. Personal, social and
ownership relations (FRIEND, FAMILY, PARTNER, COWORKER, OWNS, OWNER_OF,
EMPLOYEE_OF...) are refused as rule outputs. They can exist only as
*external only* types imported from an authorized registry by an
administrator (see [Sensors and external registries](#sensors-and-external-registries)).
`ASSOCIATED_WITH` means "observed together by a configured rule", never
ownership.

**Built in** (no rules needed, per experiment):

* *Places*: ENTERED / EXITED / CROSSED from the scene's zones, checkpoints
  and lines; USED_ROUTE from completed routes; REMAINED_IN once a visit lasts
  `remained_min_s`; MOVED_FROM + MOVED_TO when the next place is reached
  within `transition_s` (also for adjacent zones, where the next entry is
  reported before the last exit); optionally OCCUPIED for every visit.
* *Identities*: the identity links above, when a recognition module is
  licensed and allowed for the graph.

## Rules

Rules are built on **Relationships › Rules** with structured form controls
(or as JSON under *Advanced*). Four kinds:

| Kind | Reads as | Default output |
| --- | --- | --- |
| `pair` | WHEN *subject* is within / approaches / moves away from / moves together with / follows / stops near / disappears beside / appears beside *object* DISTANCE *d* FOR *t* [AND conditions] | NEAR, APPROACHED, ... ENTERED_VEHICLE, EXITED_VEHICLE |
| `place` | WHEN *subject* enters / exits / crosses / completes route / remains in / stands still in / moves from .. to *places* [FOR *t*] | ENTERED ... PARKED_IN, MOVED_TO |
| `follow_route` | WHEN *subject* follows *object* through *n* checkpoints within *T*, each at most *lag* behind | FOLLOWED |
| `sequence` | WHEN step 1 THEN step 2 WITHIN *s* THEN ... (roles A and B) | a relationship A -> B and/or a correlated event |

Subjects and objects are *role filters*: object classes plus the same
recognition clause the rule builder uses (any, anonymous, recognized,
registered with groups, specific identities, plates or vehicles). A rule
whose recognition module is not active for the run stays inactive (the run
says why).

Example (JSON, the *Advanced* tab):

```json
{
  "kind": "pair",
  "name": "Person beside vehicle",
  "subject": {"classes": ["person"]},
  "object": {"classes": ["car", "truck", "bus", "motorcycle"]},
  "condition": "near",
  "distance": {"value": 2.0, "unit": "m", "fallback_fw": 0.06},
  "for_s": 5,
  "gap_s": 1.0,
  "conditions": [{"kind": "in_zone", "role": "both", "zone_ids": ["zone_parking"]}],
  "relation": "ASSOCIATED_WITH",
  "event_label": "Beside a vehicle",
  "act_min_state": "likely",
  "actions": [{"kind": "record_event"}]
}
```

A sequence rule ("departed with vehicle"):

```json
{
  "kind": "sequence", "name": "Departed with vehicle", "window_s": 180,
  "subject": {"classes": ["person"]}, "object": {"classes": ["car", "truck"]},
  "steps": [
    {"role": "A", "what": "relation", "relation": "ASSOCIATED_WITH", "min_state": "likely"},
    {"role": "A", "what": "relation", "relation": "ENTERED_VEHICLE", "within_s": 120},
    {"role": "B", "what": "place", "place_event": "crosses", "places": ["gate_west"], "within_s": 60}
  ],
  "relation": "DEPARTED_WITH", "event_label": "Departed with vehicle"
}
```

Step kinds: `relation` (A and B have a relationship, either direction unless
`any_direction` is false, at least `min_state`), `place` (enters, exits,
crosses, uses route; `places` empty = any), `appears`, `disappears`, `event`
(an ordinary event type such as `anomaly`). A step with role `both` needs A
and B within `together_s` of each other.

Templates cover common cases: person beside a vehicle, person approaches a
vehicle, people near each other, walking together, following, getting into
and out of a vehicle, vehicles travelling together, parking, departed with,
arrived with, shared route movement.

**Actions** (record an ordinary run event, send a webhook) run once, when a
relationship or correlated event first reaches `act_min_state` (default
`likely`). Published events have type `relationship`, `correlated` or
`relation_deviation` and carry ids, never names.

**In the ordinary rule builder** a rule can require a relationship:

```
WHEN car ENTERS Restricted Parking
AND HAS RELATIONSHIP ASSOCIATED_WITH  with person (Recognized person is Employee-017)
    at least likely, holding or ended at most 300 s ago
CREATE EVENT Restricted Vehicle Association
```

The clause is evaluated when the event would be emitted. A relationship
that forms a moment later (often from the same crossing that triggers the
rule) is waited for during the recognition grace period (5 s). The rule
stays inactive when relationships are off for the experiment.

## Measurements: calibrated and uncalibrated

Distances use the scene calibration:

* **Calibrated** (four ground points, or one known distance): ground-plane
  distance in metres, marked `physical`.
* **Not calibrated**: image distance in *frame widths* (pixels / frame
  width), marked `scene-relative`. It is never shown as metres. A rule gives
  its distance in metres plus an optional fallback in frame widths; without
  the fallback it does not run on an uncalibrated camera, and the run says
  why.

People are measured by their ground point (bottom centre of the box).
Vehicles are measured by the bottom edge of their box, so a person at a
car's side is near the car even though its centre is metres away. Speeds and
headings come from the last second of ground positions.

Each spatial relationship records its calibration (mode, unit, scene
version, how vehicles were measured) and its measurements (closest, mean
and farthest distance, samples meeting the condition, duration, lag).

## Confidence

Every inferred relationship has a confidence in 0..1 built from evidence
components:

| Component | From |
| --- | --- |
| tracking | detection confidence of the tracks, lowered when a track was lost and found again |
| recognition | the recognition confidence, when the rule needed an identity |
| spatial | calibration certainty (homography 1.0, known distance 0.85, none 0.65) and how clearly the distance met the threshold |
| temporal | share of samples in the interval that met the condition |
| sensor | agreement of other sensors that reported on the same pair or entity |
| support | number of samples or observations (1 sample: x0.6, rising towards x1) |

The score is a weighted geometric mean of the components that apply, capped
at the weakest component + 0.3, times the support factor.

| State | Confidence | Meaning |
| --- | --- | --- |
| Confirmed by rule | >= 0.85 | the rule's conditions were met with strong evidence |
| Likely | >= 0.65 | default minimum for actions and identity projection |
| Possible | >= 0.40 | shown, filterable, never acted on by default |
| Insufficient evidence | < 0.40 | kept for review only |

On an uncalibrated camera a relationship can reach *likely* but rarely
*confirmed*: the measurement is less certain, and the state says so.

## Correlation and time

Sequence rules match steps in order, each at most `within_s` after the
previous one, all within `window_s`. A match stores the correlated event,
its roles, and the explicit temporal relations between consecutive
supporting facts (`FOLLOWED_AFTER`, `OVERLAPPED_WITH`, `STARTED_AFTER` with
the gap). Recognition that arrives after the steps (a face matched two
seconds later) is waited for; a role that turns out not to match drops the
match.

`follow_route` rules watch places only: B reaches the same zones or lines
as A, in the same order, each at most `max_lag_s` later, `min_checkpoints`
times within `window_s`.

## Patterns and deviations

Per experiment (**Experiments › Relationships**):

* **Expectations**: "vehicles of group Delivery are expected in Loading Zone
  only" or "people are not expected in the Centre floor". A matching entity
  that ENTERS (CROSSES, PARKS IN, REMAINS IN, USES ROUTE) a place outside the
  expectation gives a deviation.
* **Learned history**: after `pattern_min_sessions` earlier sessions of an
  identity, a place it used in fewer than `pattern_rare_share` of them, or a
  partner (vehicle, person) it was never observed with, gives a deviation,
  for example "Recognized person entered Gate C; in 12 earlier sessions it did
  so in 0 (usually Gate A, 11 of 12)".

Deviations describe what was observed, never intent. Their text never
contains a name; names appear only for authorized viewers through the
linked entities. With *Record deviations as run events* they appear in the
run's live event list, its events table and its webhooks.

## Versioning and re-analysis

* Rules are stored per (key, version). Editing stores the next version with
  a note; nothing is overwritten.
* An experiment uses a rule's *latest* version (picked up from the next run)
  or a *pinned* version.
* A run records the versions it used (run snapshot and analysis).
* **Analyse again** (run analysis page, Relationships tab) replays the
  stored trajectories through the run's own scene version, with the same
  spatial and rule engines a live run uses, and the rules chosen now. The new
  analysis becomes current when it finishes; earlier ones stay available
  (**Make current** switches back). Re-analysis needs stored trajectories
  (**Settings › Store sampled trajectories**).

## Storage and the graph API

Relational tables (migration `0006_relationships`), indexed for the graph
questions CV-Scope asks:

| Table | Content |
| --- | --- |
| `relation_entities` | nodes: key, type, safe label, sensitive label (plates), run, camera, experiment, first/last seen, metadata |
| `relation_observations` | evidence: type, entity, object entity, media time, time, source, confidence, value |
| `relation_relationships` | edges: subject, type, object, start/end (media time and time), status, confidence, state, components, rule key and version, reason, calibration, measurements, sources |
| `relation_correlated` | correlated events and deviations: roles, temporal links, description, rule version |
| `relation_support` | links from a relationship or correlated event to its observations and supporting relationships |
| `relation_analyses` | one interpretation of one run; `current` flag |
| `relation_rules` | rule versions |
| `relation_audit` | audit trail |

A graph database was not introduced: the questions (neighbours, two-step
subgraphs, timelines, histories, time and place filters) are one or two
indexed joins, the data lives next to the runs it came from (deleting a run
deletes its relationships), and SQLite and PostgreSQL both serve it. `graph.py`
defines the `GraphBackend` contract that the API uses; a graph database can
be added behind it if traversal depth or scale require it.

## Privacy and access control

Relationship data can reveal routines and associations, so it has its own
policy (**Relationships › Settings**):

* **Roles** come from the recognition access tokens (viewer < operator <
  admin). Each action has a minimum role: read the graph (default: anyone on
  this computer, like the rest of CV-Scope), see identities (viewer),
  export (anyone), export with names and plates (admin), change rules and
  analyse (anyone), delete (anyone), change the settings (admin; while no
  token exists, the local user on this computer).
* **Identities** are shown by name only with the identity role. Everyone else
  sees "Recognized person", "License plate" or "Registered vehicle" with no
  key: it cannot be opened, searched or exported by name.
* **Modules**: face-derived and plate-derived links can be switched off for
  the graph (hidden everywhere, not created by new runs), as can external
  sensor observations.
* **Retention** (hourly): relationship data after *n* days, identity links
  (and deviations about identities) after *n* days (default 30, as for
  recognition events), audit records after *n* days.
* **Audit**: rule creation and versions, archive/restore, analyses, which
  analysis is current, deletions, exports, settings changes, registry
  imports, sensor observations, model-written summaries, and every
  identity-level view (entity, neighbours, graph, history, timeline, search).
* **Language models**: optional, off by default, for rewording summaries
  only. The model receives the anonymous deterministic summary (no names,
  no plates, no pictures). Summaries of an identity are never sent.

## Sensors and external registries

External sensors publish observations through the API (the *sensors* module
must be on; the rules role is needed):

```http
POST /api/relationships/observations
{
  "sensor_id": "depth-01", "sensor_type": "depth", "run_id": 12, "media_time_s": 75.2,
  "subject": {"track_id": 1}, "object": {"track_id": 2},
  "measurement": {"kind": "distance", "value": 0.9, "unit": "m"}, "confidence": 0.95
}
```

Kinds: `distance` (compared with a relationship's metre threshold),
`presence` (thermal: confirms or not), `movement` (radar speed in m/s:
confirms moving or standing-still relationships). The observation is linked
to each relationship of the pair that holds at that time, the sensor type is
added to its sources ("RGB, DEPTH") and its confidence is recomputed with the
sensor component (agreeing 1.0, contradicting 0.3 or 0.4).

Personal or organisational relations can only be imported by an
administrator, and only for types defined as *external only*:

```http
POST /api/relationships/registry
{"source": "HR registry", "items": [{"relation": "COWORKER", "subject": "recognized_person:<id>", "object": "recognized_person:<id>"}]}
```

They are marked as supplied by the registry, not inferred, and can be
withdrawn (`DELETE /api/relationships/relationship/{id}`).

## HTTP API

All under `/api/relationships`. Send the recognition token
(`X-Recognition-Token`) to be recognized as a viewer.

| Method and path | Purpose |
| --- | --- |
| `GET /meta` | Entity, relationship and observation types; states; templates; what this viewer may do |
| `GET, PUT /settings`, `GET /audit` | Access, modules, retention, custom types; audit trail |
| `GET, POST /rules`, `GET, PUT /rules/{key}`, `POST /rules/{key}/archive`, `POST /rules/validate`, `GET /templates` | Rule library and versions |
| `GET /analyses`, `GET /analyses/{id}`, `POST /runs/{run}/analyse`, `POST /analyses/{id}/current`, `DELETE /analyses/{id}`, `DELETE /runs/{run}` | Analyses |
| `GET /entities`, `GET /entity?key=`, `GET /entity/neighbors?key=`, `GET /entity/graph?key=&depth=`, `GET /entity/history?key=` | Graph |
| `GET /list`, `GET /relationship/{id}`, `GET /correlated`, `GET /correlated/{id}` | Relationships and correlated events with provenance |
| `GET /timeline`, `POST /summary` | Timeline and deterministic summary (optional model rewording) |
| `GET /search?kind=events\|associated\|near\|entered_after\|routes\|correlated` | Structured search |
| `POST /observations`, `POST /registry`, `DELETE /relationship/{id}` | Sensors and registry |
| `GET /export?format=csv\|json&identities=` | Export |
| `GET /overview` | Counts |

Common filters: `types` (comma-separated), `time_from`, `time_to`,
`last_hours`, `camera_id`, `experiment_id`, `run_id`, `zone_id`,
`min_state`, `analysis_id`, `include_superseded`.

## Limitations

* Relationships are formed within a run (one camera). Across cameras and
  sessions, entities connect through identities (history, projected
  neighbourhoods), not through anonymous tracks.
* Re-analysis measures vehicles as points unless a live analysis of the same
  run stored their box width; the provenance says which.
* A run on a video file is analysed faster than real time. Durations and
  summaries use the video's own clock (media time); the wall-clock times of
  such runs are processing times.
* Detection and tracking errors carry through: two people merged into one
  track cannot be NEAR each other. Check a sample of relationships against
  the video (every one links to it).
* The recognition modules decide identities; the graph only records them.
  A face possible match is never an identity.
