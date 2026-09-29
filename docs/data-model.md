# Data model

The database (SQLite by default, PostgreSQL optional) separates configuration,
execution, research records, validation and platform state. Raw frames are
never stored.

## Configuration

| Table | Purpose | Key columns |
| --- | --- | --- |
| `projects` | A study or a monitored location | name, description, tags |
| `sites` | Optional environment inside a project | project_id, name |
| `videos` | Uploaded or registered video files | filename, path, duration_s, fps, width, height, frame_count |
| `cameras` | Source definition and per-camera processing settings | project_id, site_id, source_type (file/usb/rtsp/http), source_uri, video_id, width, height, requested_fps, processing_fps, rotation, crop, inference_size, reconnect, enabled, recorded_at (video files: when the recording started; a run then dates its results by start + position in the video) |
| `scene_configs` | Versioned scene documents | camera_id, version, name, document (JSON), frozen, created_from_id |
| `experiments` | Research configuration | project_id, camera_id, scene_config_id, name, description, notes, condition_notes, tags, object_classes, model_id, tracker_id, inference (JSON), tracker_settings, rules (JSON), status |

A scene version that has been used by a run is `frozen`; saving the scene
again creates the next version so earlier runs keep their exact geometry.

### Scene document (JSON)

```
{
  "version": 1,
  "frame_width": 1920, "frame_height": 1080,
  "objects": [
    {"id": "gate_1", "type": "gate", "name": "Entrance",
     "points": [{"x": 0.5, "y": 0.45}, {"x": 0.5, "y": 1.0}],
     "classes": ["person"], "direction": "both", "actions": ["count", "record"],
     "min_confidence": 0.0, "min_track_age": 2, "debounce_s": 1.0, "doorway": false,
     "enabled": true, "locked": false, "visible": true, "color": null, "notes": ""},
    {"id": "zone_1", "type": "zone", "name": "Waiting area",
     "points": [{"x": 0.3, "y": 0.5}, ...],
     "measures": ["entry", "exit", "occupancy", "dwell"],
     "min_dwell_s": 0, "max_dwell_s": 120, "max_objects": null, "debounce_s": 0.5, ...}
  ],
  "routes": [
    {"id": "route_a", "name": "Route A", "start": "gate_1", "sequence": ["cp_1"], "end": "gate_2",
     "classes": ["person"], "timeout_s": 60, "strict_sequence": true, "enabled": true}
  ],
  "calibration": {"unit": "m", "points": [{"image": {"x": 0.1, "y": 0.9}, "ground_x": 0, "ground_y": 0}, ...],
                  "known_distance": {"a": {...}, "b": {...}, "distance": 5.0}}
}
```

Coordinates are normalized (0..1) to the preprocessed source frame (after
rotation and crop). Object types: `line`, `gate` (two points), `zone`,
`checkpoint`, `ignore` (polygons). `forward` on a line is the crossing
direction along the left-hand normal of A→B, shown as an arrow in the editor.

`debounce_s` means two things. On a line or gate it ignores repeated crossings
by the same track within that time. On a zone or checkpoint it is the
allowance for short exits (*Ignore exits shorter than* in the editor): a track
that leaves and comes back within `debounce_s` keeps its visit, and a longer
exit ends the visit at the moment the track left. Polygon corners within 1.2 %
of the frame border count as on the border, because the bottom-centre point
of a person cut off by the frame lies on it.

A line crossing is the track's bottom-centre point moving from one side of
the line to the other. The move counts only if the track was at least
`min_track_age` frames old where the move started, so the first boxes of a
person stepping into view (often only an arm or a torso, whose bottom is not
their feet) cannot cross a line.

`doorway: true` is for a line the camera cannot see past, such as a door into
a room or the edge of a wall. The door frame hides a person from the side they
walk into, so the bottom-centre point stops about half a body width short of
the line and the detections end. On a doorway line a track also crosses when:

* it **disappears** (the tracker gives it up, or it is out of view when the
  run stops) while the bottom edge of its last box reaches the line (within
  2.5 % of the longer frame side) and its point had moved at least 1 % of the
  longer side towards the line during its last second, without having got
  across. The crossing is dated when the track was last seen;
* it **appears** with the bottom edge of its box at the line and has moved at
  least 1 % away from it when checked between 1 and 2 s later. The crossing is
  dated when it appeared;
* it is **found again** after more than 1 s out of view: the time out of view
  counts as a disappearance at the line followed by an appearance.

Only a track seen for at least 1 s (and 5 frames) counts a passage this way:
a detector flicker on a curtain or a door leaf beside the line lives a few
frames. A passage is counted once when the tracker loses the person at the door and
reports them as a new track on the other side. Such events carry
`context.inferred` = `disappeared` or `appeared` (also on sequence events that
such a crossing completes).

## Execution

| Table | Purpose | Key columns |
| --- | --- | --- |
| `runs` | One execution of an experiment | experiment_id, camera_id, scene_config_id, status (queued/starting/running/paused/completed/stopped/failed), started_at, ended_at, error, snapshot (resolved model, device, tracker, source, calibration), stats (frames, fps, counters, tracker stats, timings) |

## Research records

### `events`

One row per semantic event.

| Column | Meaning |
| --- | --- |
| run_id, experiment_id, camera_id | Context |
| track_id | Anonymous session-scoped track id |
| object_class | person, car, ... |
| event_type | crossing, zone_entry, zone_exit, dwell, dwell_exceeded, occupancy_exceeded, route, sequence, rule |
| rule_id, rule_name | Rule or route that produced the event |
| route | Route name, or UNKNOWN / ABANDONED / LOST_TRACK for route events; record_as label for sequence rules |
| object_id, object_name | Scene object involved (line, gate, zone; for routes the end object) |
| direction | forward / reverse for crossings |
| frame_index, media_time_s | Position in the source |
| wall_time | UTC timestamp |
| entered_at_s, completed_at_s, duration_s | Start and end of the observation (routes, zone visits, sequences) |
| avg_speed, speed_unit | Mean speed over the observation; `m/s` with calibration, `frame/s` otherwise (frame widths per second, shown as *frame widths/s* in the app) |
| confidence | Mean detection confidence of the track |
| context | JSON: for routes `occupancy_at_decision`, `previous_route`, `zone_occupancy_at_start`, `checkpoints`, `checkpoint_times`, `decision_time_s`, `switched_from`, `missed_checkpoints`, `partial_progress`, `restarts`; for zones `zone_occupancy`; plus `label` |

### `track_summaries`

One row per anonymous track: first/last seen (media and wall time), frames,
path length and unit, mean speed, mean confidence, final state (`removed` or
`active_at_end`), route result and number of lost/reacquired episodes.

### `trajectories`

Optional. `points` is a list of `[media_time_s, x, y]` samples (about 10 per
second) in normalized frame coordinates. Disable with the
"Store sampled trajectories" setting.

### `recordings`

Video files recorded from live cameras when the experiment's `recording`
setting is on (`mode` `events`, `presence` or `continuous`, `pre_s`, `post_s`,
`event_types`, `presence_grace_s`, `overlay`, `fps`, `segment_minutes`,
`max_clip_s`; see
`pathscope/domain/recording.py`). One row per finished file:

| Column | Meaning |
| --- | --- |
| run_id, experiment_id, camera_id | Where the video comes from |
| kind | `event` (a clip around events), `presence` (one visit, from the entry of an object to its exit, dwell included) or `continuous` (a segment of the whole run) |
| path, mime, codec | The file under `<data>/recordings/run-<id>/`: H.264 MP4 or VP8 WebM, which browsers play, or Motion JPEG AVI as a fallback |
| width, height, fps, frames | Video size and rate; the rate is at most the processing rate |
| media_start_s, media_end_s | Run media time covered: an event at media time t is at t - media_start_s in the file |
| started_at, ended_at | Clock time covered (UTC) |
| size_bytes, overlay | File size; whether boxes, track numbers, scene objects and the time are drawn in |
| triggers, trigger_count | The events that started or extended a clip (type, label, track id, media time; at most 100 listed) |

Rows and files are deleted together: one by one, per run, with the run, and
by the hourly retention check ("Video retention (days)").

## Validation

| Table | Purpose |
| --- | --- |
| `evaluations` | Manual verdicts on events: correct, incorrect, missed, wrong_route, wrong_class, tracking_error, with optional expected label and note |
| `ground_truth_counts` | Manual counts per scene object for a run |

## Platform state

| Table | Purpose |
| --- | --- |
| `installed_models` | Reserved for registry entries of installed weights (install state is currently derived from the models directory) |
| `benchmarks` | Local benchmark results per model, device and resolution |
| `settings` | Key/value user settings layered over `.env` defaults |

## Licensed recognition modules

Separate tables, created by the same migrations, used only when the modules
are licensed (`docs/recognition.md`):

| Table | Purpose |
| --- | --- |
| `recognition_people` | Enrolled profiles: display name, reference id, notes, active, validity period, enrollment status / quality / summary, model version |
| `recognition_enrollment_images` | Enrollment images (encrypted files on disk) with view, look (`variant`), quality and whether they are biometric (the rear view is not) |
| `recognition_face_templates` | Sealed (encrypted) face embeddings per profile, view and look; never returned by the API |
| `recognition_vehicles` | Vehicle registry: normalized plate, country, region, type, description, owner reference, groups, active |
| `recognition_events` | Recognition decisions: module, kind, status, person or vehicle, raw and normalized plate with format and fields, similarity and runner-up, confidence, quality, observations, best frame, model version, run, camera, track, frame, time, context, optional encrypted crop |
| `recognition_audit` | Sensitive operations with actor, role, action, target and detail |
| `recognition_access_tokens` | Hashed access tokens with role, validity and last use |

Ordinary `events` of a recognized track carry `context.entity`
(`kind`, `identity_id` or `vehicle_id`, `confidence`, `status`,
`recognition_event_id`), never a name or a plate.

## Relationship graph

Created by migration `0006_relationships`, used when an experiment turns
relationships on (`experiments.relations`), or when a run is analysed again
(`docs/relationships.md`):

| Table | Purpose |
| --- | --- |
| `relation_entities` | Nodes, one per key (`person_track:r12.t182`, `zone:c3.zone_park`, `recognized_person:<id>`, `license_plate:<keyed hash>`...): type, safe label, sensitive label (plate text, shown only with identity access), run, camera, experiment, first and last seen, metadata |
| `relation_observations` | Normalized observations (appeared, entered, crossed, recognized, plate read, sensor...) with entity, object entity, media time, time, source and confidence |
| `relation_relationships` | Edges: subject, type, object, start and end (media time and time), open/closed, confidence, state, evidence components, rule key and version, reason, zone, sources, calibration, measurements |
| `relation_correlated` | Correlated events and deviations: roles, temporal links between the supporting facts, description, rule version, published |
| `relation_support` | Evidence links from a relationship or correlated event to observations and supporting relationships |
| `relation_analyses` | One interpretation of one run (live or re-analysis) with its rule versions, settings and calibration; one per run is current |
| `relation_rules` | Relationship rules, immutable per (key, version) |
| `relation_audit` | Audit trail of the relationship graph |

Deleting a run deletes its analyses and, with them, its observations,
relationships and correlated events.

## Locations and cross-camera correlation

Created by migration `0007_locations` (`docs/locations.md`):

| Table | Purpose |
| --- | --- |
| `location_nodes` | The place hierarchy (`parent_id` = inside): organization, site, building, floor, area, room, corridor, gate, parking, road network, road, junction... and camera (`camera_id`) and sensor (`sensor_id`) nodes; layout (plan, schematic or map: size, unit, picture, geographic box), position in the parent frame, size or outline, GPS, floor level, camera facing / field of view / reach, entry point and restricted flags |
| `location_links` | CONNECTED_TO, ADJACENT_TO, LEADS_TO (traversable, optional one-way, travel time, distance, via place, shared zone, overlapping views), VISIBLE_FROM, ABOVE, BELOW |
| `location_zone_links` | A camera's scene zone, line or route → the location node it is |
| `crosscam_transitions` | One move between two cameras: subject (identity, or the track for an anonymous move), basis (face, plate, registered, anonymous), both tracks, cameras, runs and resolved places, left / arrived (time and media time), gap, expected travel time and its source, topology kind and path, identity confidence, components, confidence, state, sensor evidence, flags, reason, active or withdrawn |

Transitions are mirrored in `relation_relationships` with rule key
`crosscam` (SEEN_AT, MOVED_FROM, MOVED_TO, MOVED_THROUGH, ENTERED_SITE_AT,
EXITED_SITE_AT, CONTINUED_AS) and topology deviations in
`relation_correlated` (rule key `crosscam.<type>`). Layout pictures are files
in `<data>/locations/`.

## Export formats

`GET /api/events/export?format=csv|json|parquet` writes every event column;
`context` is serialized as JSON text in CSV and Parquet. Parquet needs the
`pyarrow` package (`export` extra).
