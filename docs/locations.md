# Location Engine, cross-camera correlation and the visual graph

The relationship engine (`docs/relationships.md`) works inside one camera's
run. This layer places cameras in the real world and connects what several
cameras saw:

* the **Location Engine** knows where cameras, sensors and places are relative
  to each other (a hierarchy, coordinates, links with travel times);
* **cross-camera correlation** turns an identity's sightings on different
  cameras into *transitions*, each scored with its evidence;
* the **visual graph** draws the stored relationships as an interactive,
  time-aware node-edge graph, and the **site view** and **journeys** show the
  same facts on a plan and a timeline.

The source of truth stays the stored entities, observations, relationships
and locations. The graph is a query and drawing layer over them: it stores
nothing and computes nothing that is not stored. A *likely* transition stays
*likely*; nothing turns it into a fact.

## Contents

* [Flow](#flow)
* [The location model](#the-location-model)
* [Location Resolution](#location-resolution)
* [Plausibility of a move](#plausibility-of-a-move)
* [Cross-camera correlation](#cross-camera-correlation)
* [Confidence and provenance](#confidence-and-provenance)
* [What goes into the relationship graph](#what-goes-into-the-relationship-graph)
* [Topology deviations](#topology-deviations)
* [When correlation runs](#when-correlation-runs)
* [The visual graph](#the-visual-graph)
* [Site view and journeys](#site-view-and-journeys)
* [Privacy](#privacy)
* [HTTP API](#http-api)
* [Code](#code)
* [Limitations](#limitations)

## Flow

```
camera / sensor
  → detection, tracking, recognition           (worker, per camera)
  → observations                                (relationship engine, per run)
  → entity resolution (IDENTIFIED_AS ...)       (relationship engine)
  → location resolution (zone → location node)  (Location Engine)
  → relationships                               (relationship engine)
  → cross-camera correlation                    (crosscam, API process)
  → graph, journeys, site view                  (read-only query layer)
  → topology deviations → events of the run     (crosscam)
```

## The location model

Everything is a **location node** (`location_nodes`) with a `kind`:

| Group | Kinds |
|---|---|
| Organization | organization, site |
| Buildings | building, floor |
| Places | area, room, corridor, entrance, gate, zone, parking, loading, stairs, other |
| Roads | road network, road, junction |
| Devices | camera (stands for one CV-Scope camera), sensor (an external sensor id) |

`parent_id` is **INSIDE**: *Organization › Site › Building › Floor › Area ›
Camera*, or *Site › Road network › Junction › Camera*. A node may carry:

* a **layout** — `{mode: plan | schematic | map, width, height, unit: m | units}`,
  optionally a picture (floor plan, site drawing, map screenshot) and, for a
  map, its geographic box. A node with a layout is a **frame**: the nodes
  below it are placed in its coordinates;
* a **position** `x, y` (and size `w, h` or an outline `shape`) in the frame of
  its nearest ancestor with a layout, in metres or plain units;
* **GPS** `lat, lon` (optional). On a map frame with a box, a node with GPS and
  no `x, y` is placed from its GPS;
* a floor **level**;
* for cameras: **facing** (degrees clockwise from the layout's up), **field of
  view**, **reach**;
* flags: **entry point** (journeys start and end here) and **restricted**.

GPS is never required. Offices and warehouses are usually a schematic or a
floor plan in metres; campuses and roads may use a map.

**Links** (`location_links`) connect nodes:

| Link | Meaning | Used for movement |
|---|---|---|
| CONNECTED_TO | one can move between the two (both ways unless one-way) | yes |
| ADJACENT_TO | neighbours with direct passage (adjacent cameras or areas) | yes |
| LEADS_TO | the first leads into the second (a door, a gate, a ramp) | yes |
| VISIBLE_FROM | the place is covered by the camera | coverage |
| ABOVE / BELOW | floors; not a passage by itself | no |

A traversable link may have a **shortest and longest travel time**, a
**distance**, **one-way**, and between two cameras a **via** place (the
corridor between them), a **shared zone** and **overlapping views**.

The **camera topology** is simply the links between camera nodes: *Camera A →
Corridor → Camera B* is a link A–B with via = Corridor and a travel time.
Links between places describe how one can walk or drive; both are used.

## Location Resolution

`location_zone_links` maps a camera's scene zone, line or route to a location
node: `zone:c3.z_gate` (zone *Gate A* of camera 3) → *Gate North*. With it,
"entered Gate A" on camera 3 means "entered Gate North" in the site, and a
camera **covers** the places its zones map to (plus VISIBLE_FROM links; a
camera with neither stands for the area it is placed in).

The relationship pages show the location path of places and cameras, and
every relationship query accepts `location_id` (a site, building, floor...):
it limits the answer to the cameras inside that node.

## Plausibility of a move

`LocationGraph.camera_transition(A, B, from_place, to_place, class)` answers
how the model explains a move from camera A to camera B:

1. **Direct**: a traversable link between the two camera nodes (its travel
   time; overlapping views allow the second camera to see the entity before
   the first loses it).
2. **Path**: the fewest-links path from the place the entity left on A (or
   A's coverage) to the place it entered on B (or B's coverage). Travel times
   add up along the path; a link without times uses its distance (given, or
   measured on a metric plan, or from GPS) with a speed range (people
   0.4–2.5 m/s, vehicles 1–25 m/s); otherwise the time is **unknown**.
3. A path that exists only **against a one-way link** is reported as such.
4. **Unconnected**: both cameras are placed but nothing connects them.
5. **Not in the model**: a camera is not placed.

The topology certainty (the spatial component) is 0.98 for a direct link or
overlapping views, 0.96 minus 0.04 per extra link for a path (at least
0.72), 0.6 when a camera is not placed, 0.35 when unconnected and 0.3 against
a one-way link. **Locations › Topology › Check a move** shows this answer
for any two cameras.

## Cross-camera correlation

A **sighting** is one track on one camera: first and last seen, the place it
entered first and left last, every place event, and what it was identified as
— a recognized person (face), a plate, or a registered vehicle — with the
identity link's confidence. Only identity links of at least the configured
state (default *likely*) count. No continuous tracking between cameras is
assumed.

For every identity the sightings are put in time order and split into
**journeys** where the gap exceeds *New journey after* (default 4 h). Each
sighting on a different camera than the one before it forms a **transition**
from the sighting that was seen last before it started. Its evidence:

* the time between the sightings (`gap_s`) against the **expected travel time**;
* the **topology** answer above, and the places on the way (via);
* the **identity** confidence of both sightings (the weaker counts);
* **sensors** placed on the way (a sensor node inside a via place or on the
  path) that reported presence or movement between the two sightings;
* the detection quality of both tracks.

**Timing** is scored against the expected window `[min, max]`:

| Gap | Temporal component | Flag |
|---|---|---|
| within `[min, max]` (± hand-over tolerance, default 3 s) | 1.0 | – |
| below `min` | 0.5–1.0 | faster than expected |
| below `min × 0.5` (setting) | 0.15 | implausible time |
| above `max` | `max / gap`, at least 0.25 | slower than expected (not a deviation: people stop) |
| negative: seen on B before A lost it, views not overlapping | 0.1 | seen by two cameras at once |

The component is scaled by how the window is known: configured 1.0,
estimated from distances 0.9, partly configured 0.8, unknown 0.7 (then the
window is `[0, default longest travel]`, default 900 s).

**Who identified the sightings.** An identity usually comes from the face
or plate module. It may also come from a person: a recognition event whose
`context.method` is `annotation` (study ground truth, a reviewer's
identification of the footage). Its identity link then has the source
`annotation` and says "A reviewer identified ...", and a move between two
such sightings says "a reviewer identified the same person on both cameras
(manual annotation, not a recognition module)" and keeps
`components.identity_method = "annotation"`. The move card shows *Manual
annotation*. Nothing presents an annotated identity as a recognition result.

**Anonymous tracks** (no identity) are linked only when switched on (*Also
link anonymous tracks by timing alone*), only between **directly connected**
cameras with a **known** travel time, only when **exactly one** candidate
fits on both sides, and never above **possible** (confidence capped at
0.64). Re-identification by appearance is not part of CV-Scope; the
`anonymous` basis is timing and topology only.

## Confidence and provenance

The components are combined by the relationship engine's rule
(`confidence.py`: weighted geometric mean, capped at the weakest component +
0.3, times a support factor; identity-based transitions count 8 supporting
samples, anonymous ones 2). States: **confirmed** ≥ 0.85, **likely** ≥ 0.65,
**possible** ≥ 0.40, else **insufficient**.

Every transition (`crosscam_transitions`) keeps: source and destination
camera, run, track and resolved place; when it left and arrived (wall clock
and each run's media time); the gap; the expected window and where it came
from; the topology kind, path and hops; the identity confidence; sensor
reports; the components, confidence and state; flags; and a plain-language
reason, for example:

```
Cross-camera transition   Employee-017
Gate cam / Gate North  →  Corridor cam / Corridor B
Time 40 s · Expected 30 s–1m 30s (configured on the link)
Linked by face recognition · identity confidence 0.93
Topology: directly connected cameras (Gate cam → Corridor B → Corridor cam)
Sensors: Corridor radar (presence)
Correlation: Confirmed by rule · 91 %
```

(from the verification data of 2026-09-23; see *Verification* below).

Results are recomputed deterministically for the runs concerned. A transition
that the sightings no longer support (a re-analysis with other rules, a
deleted analysis, an identity link that fell below the threshold) is
**withdrawn**: kept with its old reason and a withdrawal note, and hidden from
the default views.

## What goes into the relationship graph

Rule key `crosscam` ("Cross-camera correlation"), always current (no
analysis):

| Relationship | Subject → object | When |
|---|---|---|
| SEEN_AT | identity → camera | every identity sighting (first–last seen) |
| MOVED_FROM | identity → place left (or camera) | every transition |
| MOVED_TO | identity → place entered (or camera) | every transition |
| MOVED_THROUGH | identity → via place | places the model puts on the way; **not observed there** (the reason says so; source `inferred-path`) |
| ENTERED_SITE_AT | identity → entry point | first sighting of a journey at an entry point |
| EXITED_SITE_AT | identity → entry point | last sighting of a journey that left through an entry point |
| CONTINUED_AS | track → track | anonymous transitions only (never above possible) |

Place relationships of the single cameras (ENTERED, PARKED_IN by a rule...)
stay as they are; the identity projection of the graph lifts them to the
identity. Their evidence links point to both identity links, the exit and
entry place relationships, the disappearance and appearance observations and
the sensor observations.

These types cannot be produced by rules (`inferable = False`).

## Topology deviations

Reported as correlated events of kind `deviation` (rule key
`crosscam.<type>`), published as `location_anomaly` events of the run they
anchor to (live when the run is active), and listed on the site view:

| Type | When |
|---|---|
| implausible_time | faster than `too_fast_factor` × the shortest expected time |
| unconnected | a move between placed cameras the model does not connect |
| wrong_way | only possible against a one-way link |
| simultaneous | seen on two cameras at once without overlapping views (one identification may be wrong) |
| restricted_without_entry | seen in a restricted place (or inside one) without an earlier sighting at an entry point in the same journey, in a site that has entry points |
| unusual_sequence | this identity's move A → B appeared in less than `history_rare_share` (default 10 %) of at least `history_min_journeys` (default 5) earlier journeys |

The text never contains a name or plate ("A recognized person was seen on
Corridor cam / Corridor B 10 s after Parking cam / Parking Zone 4; the
expected travel time is 60–125 s."). Deviations describe what was
observed; they say nothing about intent.

## When correlation runs

In the API process, on a background thread (debounced 2 s):

* **live batches** of a run: the identities the batch touched;
* **run finished**, **re-analysis became current**, **analysis or run data
  deleted**: the whole run, plus later runs whose transitions depended on it;
* **on request** (**Locations › Topology › Cross-camera settings › Correlate
  again**, `POST /api/locations/correlate`): the runs of a time range — use it
  after editing the topology, which is not re-applied on its own.

Switching correlation off keeps the stored results as they are.

## The visual graph

`GET /api/relationships/visual` builds the graph around an entity (depth 1–3)
or for a run, an experiment, a location or a time range:

* **nodes** carry a class: tracked object ○, recognized identity ◆, scene
  place ▭, location ▢, camera, sensor △, event ⬡;
* **edges** carry a nature: *observed fact* (built-in place relationships),
  *identity* (recognition), *inferred by a rule*, *across cameras*,
  *external registry*, *location context* (derived: a track SEEN_AT its
  camera, a zone or camera INSIDE its location — computed on request, not
  stored); a flag marks edges supported by sensor observations;
* each edge keeps the **intervals** (start, end, state, confidence, run,
  camera, media time) of the relationships it merges;
* with *Merge tracks into identities* (viewers allowed to see identities) the
  tracks of a recognized person or vehicle become the identity's node.

`GET /api/relationships/visual/path` finds the shortest chain of
relationships (up to 6) between two entities.

The **Relationships › Graph** page draws it: pan (drag the background), zoom
(wheel), drag nodes to pin them, double-click to expand a node in place and
collapse it again, filters for edge kind, relationship type, confidence and
camera, a location scope, a path between two nodes, the evidence of any edge
with a jump to the video, and a time bar: *all time*, *snapshot at T*
(instant relationships stay visible for a configurable afterglow), *time
range*, and *replay* (step or play through the moments the graph changed).
The layout is a deterministic force layout computed once per change of the
node set; nodes placed before move little when something is added.

## Site view and journeys

**Locations › Site view** draws a frame (plan, schematic or map) with the
cameras and their fields of view, places, links and travel times, and every 5
seconds: objects in view per camera (active runs), alerts of the last 24 h
(relationship deviations and Anomaly Assistant anomalies), recent moves
between cameras (red when flagged), who is in view (names only for authorized
viewers), recent events. Clicking a camera opens its run, live feed
(experiment page) and experiments; finding an entity rings the place where it
was last observed.

**Relationships › Journeys** shows one entity's sightings three ways that
stay in step: a timeline (each camera, the places entered and left, and the
moves between them with their expected time and confidence), the location
path on the plan (numbered steps), and the relationship graph. Selecting a
step, a move, a plan marker or a graph edge highlights it in the other two;
a move opens its provenance card and its supporting observations.

## Privacy

* Identity-based transitions reveal that two tracks are the same person or
  vehicle: they are listed only for viewers with the identity role of the
  relationship settings. Everybody else sees anonymous transitions only, and
  identities as "Recognized person" / "Registered vehicle".
* Opening an identity's journey or last sighting is written to the
  relationship audit trail (`identity_viewed`).
* Stored reasons and deviation texts never contain names or plates.
* Retention: transitions and `crosscam` relationships follow the relationship
  retention (days) and, when identity-based, the identity-link period.
* Changing the topology needs the rules role; changing cross-camera settings
  the settings role (or this computer while no recognition token exists).
  Topology edits are audited (`topology_changed`).

## HTTP API

| Method | Path | |
|---|---|---|
| GET | `/api/locations/meta` | node and link kinds, the viewer |
| GET | `/api/locations/graph?root_id=` | nodes (with frame and path), links, INSIDE edges, zone mappings, unplaced cameras |
| POST, PUT, DELETE | `/api/locations/nodes[/{id}]` | a node (delete removes everything inside it) |
| PUT | `/api/locations/positions` | positions dragged in the editor |
| POST, PUT, DELETE | `/api/locations/links[/{id}]` | a link |
| GET, PUT | `/api/locations/cameras/{camera_id}/zones` | scene zones of the camera's latest scene → location nodes |
| POST, GET, DELETE | `/api/locations/nodes/{id}/image` | layout picture (PNG, JPEG, WebP, ≤ 15 MB) |
| GET | `/api/locations/check?from_camera=&to_camera=` | what the model concludes about a move |
| GET, PUT | `/api/locations/settings` | cross-camera settings |
| POST | `/api/locations/correlate` | `{run_ids}` or `{hours}` / `{time_from, time_to}` |
| GET | `/api/locations/transitions` | filters: time, `location_id`, camera, run, `key`, `min_state`, `flagged` |
| GET | `/api/locations/transitions/{id}` | one transition with its deviations |
| GET | `/api/locations/journey?key=` | sightings, transitions, location path |
| GET | `/api/locations/last-seen?key=` | the latest sighting |
| GET | `/api/locations/deviations` | topology deviations |
| GET | `/api/locations/live?root_id=` | the site view's live overlay |
| GET | `/api/relationships/visual` | the visual graph (see above) |
| GET | `/api/relationships/visual/path` | the shortest chain between two entities |

Every `/api/relationships/*` query also accepts `location_id`.

## Code

```
backend/pathscope/location/
  models.py       location_nodes, location_links, location_zone_links, crosscam_transitions
  topology.py     LocationGraph: hierarchy, frames, resolution, coverage, plausibility, travel time
  coordinates.py  plan / GPS distances, local projection
  settings.py     cross-camera settings
  api.py          /api/locations
backend/pathscope/crosscam/
  engine.py       sightings, identity links, time fit, scoring, Correlator.rebuild, deviations
  journey.py      journeys, transitions and last sightings as a viewer may see them
  service.py      queue, background thread, publishing deviations as run events
backend/pathscope/relationships/visual.py   the visual graph and paths
frontend/src/locations/                     graph canvas and model, workbench, journeys, site plan, topology editor, site view
```

Migration `0007_locations`.

## Limitations

* Correlation needs identities (face or plate modules) or, opt-in, a single
  unambiguous candidate between directly connected cameras. Appearance
  re-identification is not included.
* Wall clocks of different cameras are trusted as they are; set the hand-over
  tolerance to cover clock differences. File runs are processed faster than
  real time, so their wall times say when they were analysed, not when the
  video was recorded - unless the camera has a **Recorded at** time (camera
  settings, video files only): a run then dates everything by the recording
  start plus the position in the video, and the files of several cameras
  line up to the second. Otherwise correlate live cameras (or runs whose
  clocks match).
* Topology edits are not re-applied to stored results automatically: use
  *Correlate again*.
* The site view draws one frame at a time; a journey that crosses frames
  (site → floor) is shown frame by frame.
* Maps are drawn from coordinates on a plain background (or your picture):
  CV-Scope loads no map tiles from the internet.
* Verification (2026-09-23, isolated instance): 5 cameras of a synthetic
  campus with stored trajectories and recognition results were re-analysed
  through the real replay path; 19/19 API checks (transitions with provenance,
  radar corroboration, vehicle route with ENTERED_SITE_AT / MOVED_THROUGH /
  PARKED_IN, deviations, privacy, location filters, re-analysis consistency)
  and 33/33 browser checks passed. A real camera run is not part of it: the
  sample videos are single cameras.
