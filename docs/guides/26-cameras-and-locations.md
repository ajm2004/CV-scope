---
title: Follow people and vehicles across cameras
level: Advanced
time: 45 minutes
needs: Two or more cameras on one site with relationships turned on (guide 25); the face or plate module for identity-based moves (guide 22)
summary: Describe where your cameras are and how one can move between them, then follow a person or a vehicle from camera to camera - with the time each move took, the expected time, the evidence and the confidence - on a timeline, a site plan and an interactive relationship graph.
learn:
  - Build a location model - site, buildings, floors, areas, roads - with or without GPS
  - Connect cameras - adjacent cameras, the place between them, travel time, one-way passages
  - Map scene zones to places so "entered Gate A" means "entered Gate North"
  - Read a journey across cameras and the provenance of each move
  - Explore the relationship graph over time and find the path between two entities
  - Watch a site live and understand topology deviations
pages: [Topology, Site view, Journeys, Relationship graph, Experiments, Relationship settings]
---

# Follow people and vehicles across cameras

One camera tells you what happened in its view. With several cameras you want
to know **where** things happened and **how an entity moved between
cameras**:

```
Employee-017
09:12  Gate cam       Entered Gate North
09:14  Corridor cam   Entered Corridor B        moved in 40 s (expected 30 s-1m 30s)
09:16  Parking cam    Entered Parking Zone 4    moved in 2 min (expected 1-2 min)
```

CV-Scope does not follow anyone continuously between cameras. It connects
two sightings when the same **recognized person or plate** appears on two
cameras and your **location model** says the move is plausible, and it gives
every move a confidence and its evidence. A *likely* move is shown as
likely, never as a fact.

> [!NOTE]
> Without the face or plate module, moves can only be linked by timing (Step
> 7), between directly connected cameras, when a single candidate fits, and
> never above *possible*.

## Step 1. Describe the site

1. Open **Topology** (sidebar, **Locations › Topology**).
2. Click **+ Site** and name it, for example *North Campus*. In the
   properties on the right, open **Layout**: choose **Floor plan**,
   **Schematic** or **Map**, give the width and height and the unit. Use
   **metres** when the plan is to scale: travel times can then be estimated
   from distances.
3. Optional: **Upload floor plan / map picture**. CV-Scope stretches it over
   the layout; it loads no map tiles from the internet.
4. Select the site and add what is inside it with **+ Add inside**: a
   building with floors (give each floor its own layout), areas, rooms,
   corridors, gates, parking areas - or a road network with roads and
   junctions.
5. Drag each place to where it is on the plan. Give areas a **Width** and
   **Depth** to draw them as rectangles.
6. Tick **Entry point** on gates and entrances, and **Restricted** on places
   people should only reach through an entry point.

GPS is optional. A node with a latitude and longitude on a **Map** layout
with a geographic box is placed from its GPS.

## Step 2. Place the cameras

1. Under **Cameras not placed yet**, select the place a camera is in (in the
   hierarchy), then click **Place in …** next to the camera.
2. Drag the camera on the plan and set **Facing** (0 = up, 90 = right),
   **Field of view** and **Reach**. The plan draws the view as a cone.
3. Under **Scene zones → locations** map each zone of the camera's scene to
   the place it is, for example zone *Gate A* → *Gate North*, and click
   **Save mapping**. A camera covers the places its zones are mapped to.

## Step 3. Connect the cameras

1. Click **Link** above the plan, choose **CONNECTED_TO** (or ADJACENT_TO,
   LEADS_TO), then click the first camera and the second camera.
2. In the link's properties set **Shortest travel** and **Longest travel**,
   for example 30 and 90 s for a corridor walk.
3. Choose the place between them under **Via**, for example *Corridor B*.
   Moves then also record that the entity passed there (MOVED_THROUGH, marked
   as inferred from the model, not observed).
4. Tick **One way** for passages used in one direction only, **Views overlap**
   when both cameras see the same spot.
5. Repeat for every pair of neighbouring cameras. Links between places (for
   example *Gate North* LEADS_TO *Corridor B*) help where cameras are not
   directly linked.
6. Open the **Check a move** tab, choose two cameras, and read what the
   correlation will conclude: *Directly connected*, *Connected through 2
   links*, *Not connected*, the way, and the expected travel time.

## Step 4. Run the cameras

1. In **Experiments**, turn on **Relationships** for the experiment of every
   camera (guide 25). Rules are optional; place relationships and identity
   links need none.
2. With the licensed modules, turn on face or plate recognition for the
   experiments (guide 22).
3. Start the runs. Correlation across cameras runs by itself a few seconds
   after each batch of results and again when a run ends.

> [!TIP]
> The cameras' clocks must agree: moves are timed by wall clock. Video files
> are analysed faster than real time: give each file camera its **Recorded
> at** time (Cameras, edit the camera) so its runs are dated by the
> recording, and the videos of several cameras line up. The sample project
> *Sample - MEVA school campus* is built this way (see
> `docs/sample-scenario.md`).

## Step 5. Follow a journey

1. Open **Journeys** (sidebar, **Relationships › Journeys**) and choose a
   recognized person, a registered vehicle, a plate or a track.
2. The **Timeline** lists every sighting (camera, places entered and left)
   and between them each move: *moved from Gate cam in 40 s (expected 30 s-1m
   30s) · confirmed by rule 91 %*.
3. Click a move. The **Move** card gives its provenance: from and to (camera
   and place), the time it took, the expected time and where it comes from,
   the identity confidence, the topology, sensors on the way, and the final
   confidence with its components. **Supporting observations** opens the
   evidence; the **From** / **To** buttons open the video of each camera at
   that moment.
4. The **Location path** draws the same journey on the plan with numbered
   steps; the **Relationship graph** below shows the entity and everything it
   is related to. Click a step, a marker or a graph edge: the other two views
   highlight the same thing.

## Step 6. Explore the relationship graph

1. Open **Relationship graph** (sidebar, **Relationships › Graph**) and
   choose what to show: around an entity, a run, an experiment, a site or
   location, or a time range.
2. Read the drawing: circles are tracked objects, diamonds recognized
   identities, rectangles places, framed rectangles locations, camera icons
   cameras. Grey edges are observed facts, blue ones inferred by a rule,
   purple ones identity links, orange ones moves across cameras, dotted grey
   ones location context. Solid means confirmed or likely, dashed possible,
   dotted insufficient; **S** marks sensor-supported edges.
3. Drag the background to pan, use the wheel to zoom, drag a node to pin it.
   Double-click a node to **expand** it in place; select it and click
   **Collapse** to fold it again.
4. Use **Show** on the left to filter by kind of edge, relationship type,
   confidence and camera.
5. In the time bar choose **Replay (how it grew)** and press **Play** or ▶:
   the graph builds up in the order things happened. **Snapshot at time T**
   shows only what held at that moment; **Time range** a period.
6. Select a node and click **Path from here**, select another and click
   **Path to here**: the shortest chain of relationships between them is
   highlighted.
7. Click an edge to list the stored relationships it stands for; **Evidence**
   explains each one, with a jump to the video.

## Step 7. Watch the site and read deviations

1. Open **Site view** (sidebar, **Locations › Site view**). Cameras with an
   active run are highlighted, a blue badge counts the objects in view, a red
   dot marks alerts of the last 24 hours, orange lines are recent moves
   between cameras (red when flagged).
2. Click a camera for its run, its **Live feed** and its experiments.
3. Under **Where was it last seen?** choose an entity: the place is ringed on
   the plan.
4. **Alerts** lists topology deviations: a move faster than possible (*seen
   10 s after Parking cam; the expected travel time is 60-125 s*), a move
   between cameras the model does not connect, a one-way passage used
   backwards, a restricted place reached without passing an entry point, and
   a camera sequence unusual for this identity. They are also recorded as
   events of the run. They describe what was observed, never intent - a
   wrong identification is often the reason.
5. In **Topology › Cross-camera settings** you can change the tolerances,
   report fewer deviations, or tick **Also link anonymous tracks by timing
   alone**. After editing the location model, click **Correlate again** to
   apply it to recent runs.

> [!CAUTION]
> Moves based on recognized identities reveal that two tracks are the same
> person or vehicle. They are shown only to viewers with the identity role of
> **Relationship settings**, and opening a journey is written to the audit
> trail.

The full reference is `docs/locations.md`.
