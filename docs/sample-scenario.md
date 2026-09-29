# Sample scenario: MEVA school campus

A worked example of locations, cross-camera moves, entities and the
relationship graph, built from real multi-camera footage. It lives in the
project **Sample - MEVA school campus** and the location
**Muscatatuck Urban Training Complex › Known Facility KF1**.

## The story

Eight synchronized cameras around a school building, 11 March 2018,
11:20-11:25. The gym is being cleared after a session (chairs are stacked at
the stage end). Meanwhile the next groups arrive: two people walk along the
north walkway and come in through the north doors, then a group of six and a
group of four; they all go up the north staircase and along the upper
hallway to the classrooms. Others cross the plaza and enter the main
entrance. A maroon SUV drives around the parking lots.

## What is real and what was added

| Part | Source |
|---|---|
| Video | MEVA Known Facility (KF1), 5-minute clips of cameras G330, G423, G419, G420, G638, G424, G328, G300 (actors, public research dataset). Stored in `data/videos/meva-kf1-2018-03-11/`, remuxed from AVI to MP4 without re-encoding. |
| Detections, tracks, zone and line events, place relationships, "Walking together", "Parked" | Computed by CV-Scope: one run per camera (YOLO11x, ByteTrack, 10 fps). |
| Times | Each camera's **Recorded at** is the clip's start (11:20:00, 11:20:01, 11:20:04), dated today, so the cameras line up to the second. |
| Site plan | The aerial picture of the MEVA KF1 site map; 0.26 m per pixel. North is to the right. |
| Camera positions | Outdoor cameras from the MEVA camera models (KRTD: position, facing, field of view, GPS). Indoor cameras placed from the site map. |
| Travel times | Measured on the footage (north walkway → north doors about 20 s; north doors → upper hallway 1-9 s). |
| North door contact (sensor) | The door openings annotated in MEVA (`person_opens_facility_door`), replayed as sensor reports. |
| Identities (Visitor A-F, Maroon SUV) | **Manual re-identification** of the footage (clothing, build, timing), checked on crops of the frames. Stored as recognition events marked `method: annotation`; every link says "a reviewer identified", never "face recognition". The SUV's plate is a placeholder. |

## The cast

| Identity | Seen on | Notes |
|---|---|---|
| Visitor A | North walkway (G300) → Entrance stairs (G419) → Entrance doors (G420) → Upper hallway (G423) | 3 moves; the first confirmed by the door sensor |
| Visitor B | North walkway → Entrance doors → Upper hallway | walks with A |
| Visitor C | Entrance doors → Upper hallway | red top, in the group of six |
| Visitor D | Entrance doors → Upper hallway | straw hat, in the group of six |
| Visitor E | Entrance doors → Upper hallway | navy blazer, in the group of four |
| Visitor F | Upper hallway only | already upstairs: raises a *restricted place without an entry* alert |
| Maroon SUV | Parking 2-3 (G424) → Parking 3 (G328) → Parking 2-3 | overlapping views |

Names and the Recognition pages need a recognition token (the identity role
of Relationship settings); without it the same data shows "Recognized
person" and "Registered vehicle".

## A 10-minute tour

1. **Locations › Topology.** The hierarchy on the left (site › school ›
   ground floor / upper floor › gym, entrance hall, stairs...). Click a camera
   to see its facing and field of view; click a link to see its travel time
   and the place on the way. **Check a move**: pick *North walkway (G300)* →
   *Upper hallway (G423)*: "connected through 2 places", 8-100 s.
2. **Locations › Site view.** Set the period to **last 24 h**. The alert on
   the right is Visitor F. *Moves between cameras* lists every move. Zoom
   into the school with the mouse wheel (labels keep their size). Type a
   visitor in *Where was it last seen?*.
3. **Relationships › Journeys**, entity *Visitor A*. The timeline has 4
   sightings and 3 moves; click the first move: *Linked by: Manual
   annotation*, 20 s against 8 s-1 min, *Sensors: North door contact*,
   confirmed 89 %. The location path shows the same steps on the plan.
4. **Relationships › Graph**, around *Visitor A*. Try *Replay* in the time
   bar, *2 steps* depth, and *Path from here / to here* between Visitor A
   and Visitor B.
5. **Relationships › Explorer** and **Timeline**: the per-camera
   relationships behind all this (ENTERED, CROSSED, REMAINED_IN,
   TRAVELLED_WITH, PARKED_IN); open one and click **Evidence**.
6. **Analysis**, run *KF1 school 11:20 - Entrance doors (G420)*, **Video
   review**: the real video with the zones and the *North doors* doorway
   line; click an event to jump to it. The *Crossing North doors reverse*
   events are people coming in (doorway line, "appeared").
7. **Recognition › Recognition events**: the 19 annotation events, with a
   crop of each sighting.

## Things to know

* The site view shows the last 24 hours only; the journey, graph, timeline
  and data pages take a time range (the sample is dated
  23 September 2026, 11:20-11:25).
* Identity links are deleted after 30 days (Relationship settings ›
  retention › identity links). Set it to 0 to keep the sample's identities.
* The upper floor is marked *restricted* and the entrances and parking lots
  are *entry points*; Visitor F's alert comes from these two settings.
* **Also link anonymous tracks by timing alone** is switched on (Topology ›
  Cross-camera settings); with groups arriving together no single candidate
  fits, so no anonymous move was created.

## Removing the sample

Delete the project *Sample - MEVA school campus* (its cameras, experiments,
runs and events go with it), the location *Muscatatuck Urban Training
Complex* (Topology, everything inside it), the people *Visitor A-F* and the
vehicle *KF1SUV01*, the relationship rules noted "Sample scenario (MEVA
school campus)", and the folder `data/videos/meva-kf1-2018-03-11`.

## Attribution

MEVA (Multiview Extended Video with Activities), Known Facility KF1,
Kitware and IARPA DIVA, released under CC BY 4.0: <https://mevadata.org>.
K. Corona et al., "MEVA: A Large-Scale Multiview, Multimodal Video Dataset
for Activity Detection", WACV 2021. Site map v1.3 (2019) and camera models:
<https://gitlab.kitware.com/meva/meva-data-repo>.
