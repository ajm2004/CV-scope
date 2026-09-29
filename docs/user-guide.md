# User guide

This guide walks through the first experiment: a route-choice study on a
recorded video. The same steps apply to a live camera and to vehicles.

For hands-on practice, the [guides](guides/README.md) walk through
twenty-three projects from easy to advanced, such as measuring screen time with
a webcam, counting visits to a room, counting people, bicycles and cars, or
checking accuracy. The app shows the same guides under Help, Guides.

## 1. First-run setup

Open http://localhost:5173. The wizard runs through:

1. **System check** – API and database state, installed detector providers.
2. **Hardware** – CPU, memory, GPU and VRAM, CUDA / Metal availability.
3. **Model recommendation** – Fast, Balanced, High accuracy and CPU tiers with
   the reasons for each, based on your hardware.
4. **Detector** – download the recommended detector (or another one).
5. **Camera or video** – upload a video, point to a local file, or enter a USB
   device index or RTSP address (with a connection test).
6. **Project** – name the project and the camera.
7. **Scene Builder** – opens with the first frame.

Everything can be changed later from the Cameras, Models and Settings pages.

## 2. Draw the scene

The Scene Builder shows the frame in the centre, tools on the left and the
inspector on the right. For a recorded video, the slider at the bottom freezes
any moment of the clip to draw over.

For a live camera (USB, RTSP or HTTP) the picture is live and stays on while
the Scene Builder is open. **Freeze frame** (or `F`) holds the current frame
and switches the camera off. **Resume live** turns it back on. When a run
starts, the live view hands the camera to the run by itself. On Windows a
webcam can be used by one app at a time, so close video-call apps first.

| Tool | Key | How to use |
| --- | --- | --- |
| Select | V | Click an object to select it; drag to move; drag a vertex to reshape |
| Pan / zoom | H | Drag to pan; mouse wheel zooms around the pointer |
| Line | L | Two clicks. Counts and records crossings with direction |
| Gate | G | Two clicks. Like a line, and usable as a route start or end |
| Zone | Z | One click per corner, double-click to finish. Measures entries, exits, occupancy and dwell |
| Checkpoint | C | A small polygon used as a waypoint in routes |
| Ignore area | I | Detections inside are dropped (reflections, screens, unrelated traffic) |
| Route | R | Click the start gate, checkpoints in order, then the end gate; press Enter |
| Calibration | K | Click reference points, then enter their real-world coordinates |

The inspector edits the selected object: name, object classes, direction
(with a flip button; the arrow on the canvas shows the forward direction),
what to count or record, and under **Advanced** the confidence, track-age and
debounce thresholds. On a zone, **Ignore exits shorter than** keeps a visit
going when the object steps out for a moment. `Delete` removes, `Ctrl+D`
duplicates, `Ctrl+Z` / `Ctrl+Y` undo and redo, `Ctrl+S` saves.

Objects are placed at the bottom centre of their box. A person cut off by the
frame, like someone sitting close to a webcam, therefore stands on the bottom
edge of the image. A zone meant to catch them has to reach that edge. Corners
dragged close to an edge snap onto it, and **Cover the whole image** in the
zone inspector makes the zone fill the frame. Runs also treat corners within
about 1 % of an edge as on it, so zones drawn before snapping existed reach
the edge too.

For the corridor sample: draw an **Entrance** gate across the middle, an
**Exit Left** gate and an **Exit Right** gate, then two routes: Entrance →
Exit Left = Route A, Entrance → Exit Right = Route B.
(`samples/scenes/corridor_route_choice.json` contains exactly this; use
**Import JSON** in the tool column.)

Save the scene. Once a run has used a scene version, saving creates a new
version instead of changing the old one, so results stay reproducible.

## 3. Create the experiment

Click **New experiment** in the Scene Builder top bar (or use the Experiments
page): name it, choose the objects to track (Person; or Car, Truck, Bus,
Motorcycle for traffic) and add condition notes such as "Route A has
directional signage".

The camera list shows every camera. Cameras of the experiment's own project
come first, and cameras from other projects are listed under
**Other projects**. Such a camera works as it is. **Move camera to this
project** lists it with the project's own cameras. The experiment page also
shows what the chosen camera sees, with the zones, lines and routes of the
chosen scene version drawn over it and named as the rules name them. The
arrow on a line is its **forward** direction, the one a rule's *forward*
means. Point at a name under the picture, or at a rule, to highlight the
objects it uses. With the view off (or before the first picture arrives)
the scene is drawn on the frame's outline.

On the experiment page you can also:

* pick the detector (default: the hardware recommendation) and a preset
  (AUTO, FAST, BALANCED, ACCURATE, CUSTOM),
* pin a scene version,
* build rules in plain terms, for example:
  `WHEN Person CROSSES Entrance THEN CROSSES Route A Gate WITHIN 20 s RECORD AS Route A`
  or `WHEN Person ENTERS Waiting Area AND REMAINS FOR more than 120 s CREATE EVENT Long wait`.

Lines, zones and routes drawn in the scene count and record on their own;
rules are for sequences, dwell thresholds, custom labels and webhooks.

## 4. Run it

Press **Start**. The canvas switches to the live worker output with boxes,
anonymous track ids, trails and, when enabled, confidence, the candidate route
and the current zone. Counters and the latest events appear at the bottom.
Recorded video is processed as fast as the machine allows (choose "pace at the
source frame rate" in the experiment for a real-time feel). **Pause**,
**Resume** and **Stop** are in the top bar; the Live page shows every active
camera.

## 5. Read the results

Every run has a results page (Experiments → run → Results, or the Analysis
page):

* **Routes** – total observations, valid, Unknown, Abandoned and Lost track
  counts, per-route shares of valid observations, durations and speeds, mean
  decision time, route switches, following behaviour and route-group
  occupancy at the moment of choice.
* **Line crossings** per line and direction and per class.
* **Zones** – occupied time (at least one object inside), total time of all
  visits, visits, mean and longest visit, maximum occupancy and flagged long
  visits. For live cameras, occupied time is also split by clock hour.
  A visit ends when the object leaves, when it has not been seen for the
  tracker's lost-object time, or when the run stops.
* **Events over time** and **object classes**.
* **Tracks and heatmap** – sampled trajectory density and tracker statistics.
* **Diagnostics** – frames, pipeline FPS, timings, rule-engine counters and
  the resolved configuration snapshot.

The Analysis page compares experiments side by side (for example with and
without signage). Correlations are presented as observed movement, not as
causes.

## 6. Review the video and validate

**Review** opens the recorded video with the geometry and stored trajectories
drawn over it, event markers on the timeline and an event list; clicking an
event jumps to it. A run on a live camera has video when its experiment turns
on **Video recording** (clips around events, or the whole run; off by
default); the timeline then shades the recorded parts and an event opens the
clip that contains it. See [guide 23](guides/23-record-video.md). In the **Evaluation** tab of the results page you mark
events as correct, incorrect, wrong route, wrong class or tracking error, log
missed events and enter manual counts; the metrics shown are computed only
from those verdicts.

## 7. Export

The Data page filters events by project, experiment, run, class, event type,
route, track, media time and date, and exports the result as CSV, JSON or
Parquet. The same export is one click away on every run row.

## Traffic example

Draw an **Entry** line on the approach and **Left**, **Straight** and
**Right** exit gates; create three routes from Entry to each exit; track Car,
Truck, Bus and Motorcycle. The results page reports vehicles per hour,
turns by route, vehicle type distribution and unknown or incomplete tracks.

## Choosing a tracker

ByteTrack is the default and suits most fixed cameras. Choose BoT-SORT in
the experiment's detection settings when:

* the camera can shake or sway (pole mounts, wind, vibration), or is
  sometimes bumped. BoT-SORT measures and compensates the image motion, and
  the run diagnostics show how much the camera moved;
* people often cross or walk close together. Under advanced settings, turn
  on "Use appearance to keep identities through occlusions". The colour
  histogram needs no download; ResNet-18 features are installed from the
  Models page.

Compare the two on your own footage: duplicate the experiment, change only
the tracker, and compare track counts and route results. Use the Benchmark
button on the Models page to see the extra processing time on your machine.

## Calibration

With the Calibration tool, click four or more points on the ground plane and
enter their real coordinates (metres) in the inspector, or pick a drawn line
and enter its real length. Speeds and distances are then reported in metres;
the inspector states whether the mapping is a full perspective calibration,
a scale-only estimate, or absent (frame units).

## Settings to know

* **Store sampled trajectories** – needed for heatmaps and review overlays.
* **Keep uploaded source videos** and retention days. **Video retention
  (days)** deletes video recorded from live cameras after that many days.
* **Default preset / detector / device** for new experiments.
* **Live preview frame rate** – affects only the browser preview.
* **What this installation stores** – listed on the Settings page.
