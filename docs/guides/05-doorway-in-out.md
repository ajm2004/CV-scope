---
title: Count people in and out of a door
level: Beginner
time: 15 minutes
needs: The corridor sample video, or a webcam that sees a door
summary: Put a gate across a doorway, point its arrow out of the room, and name the two directions Out and In with two small rules.
learn:
  - Draw a gate and set its forward direction
  - Read forward and reverse counts
  - Name directions with single-trigger rules
  - Set up a real door with a webcam
  - Count doors the camera cannot see through
pages: [Cameras, Scene Builder, Experiments, Data, Live]
---

# Count people in and out of a door

A gate is a counting line that also works as the start or end of a route. Put
one across a doorway and CV-Scope separates the people who come in from the
people who go out.

The corridor clip has a doorway on the left. This guide counts the people who
use it.

## Step 1. Draw a gate in front of the door

1. Open **Cameras**, select `Corridor` and click **Open scene builder**. If
   the camera does not exist yet, add it as in
   [guide 02](02-count-a-line.md#step-1-add-the-corridor-video).
2. Press `G`, or click **Gate** in the tool column.
3. Click on the floor at the foot of the back wall, about a sixth of the way
   in from the left edge. Then click at the bottom edge of the picture,
   straight below.
4. In the inspector, set **Name** to `Door` and keep **Person** ticked under
   **Object to track**.
5. Look at the solid arrow on the gate. It should point left, towards the
   door and out of the room. If it points into the room, click
   **Flip forward direction**.
6. Click **Save** in the top bar, or press `Ctrl+S`.

Forward now means out of the room, and reverse means into the room.

## Step 2. Name the two directions

Rules turn the two directions into words. The words then appear in the
counters during a run and in the exported data.

1. Click **New experiment** in the top bar. Set **Name** to `Door counts`,
   keep **Person**, and click **Create experiment**.
2. Click **Edit experiment** in the top bar. The experiment page opens.
3. In the **Rules** panel, click **Add rule**. Keep **Single trigger** and set
   the rule like this:
   * **WHEN:** Person.
   * **CROSSES:** `Door`, and **forward** in the direction list.
   * **COUNT AS:** `Out`.
4. Click **Add rule** again and set the second rule the same way, with
   **reverse** and `In`.
5. Click **Save** at the top of the page.

## Step 3. Run it

1. Click **Start** at the top of the experiment page.
2. While it runs, open **Live** to see the run with its counters, including
   `Out` and `In`.
3. When the run has finished, find it under **Runs** on the experiment page
   and click **Results**.

## Step 4. Read the counts

* **Line crossings** shows `Door` with **Forward** for people going out and
  **Reverse** for people coming in.
* **Events by type** shows **Rule** events, one for each named crossing.
* On the **Events** tab, the **Route / label** column shows `Out` or `In` for
  each rule event. The **CSV** export has the same labels.

With the recommended detector the sample shows 4 crossings, all forward. Four
people left through the door during the clip and nobody came in.

## Set up a real door

* **Camera position.** Mount the camera high and looking down at the doorway.
  Seen from above, people do not hide each other while they pass.
* **Gate position.** Draw the gate across the floor just inside the door,
  where everyone has to pass. Make it a little wider than the doorway.
* **Frame rate.** A person must be seen on both sides of the gate. On the
  experiment page, under **Advanced settings**, keep **Processing FPS** at 10
  or more for a door that people walk through quickly.
* **People inside.** Since the start of the run, the people inside are In
  minus Out, if the room was empty at the start. To count the people in a room
  directly, use a zone, as in [guide 09](09-room-occupancy.md).
* **Live runs.** A run on a live camera continues until you click **Stop**.

## A door the camera cannot see through

Often the camera sees only one side of the door: a hall or landing with the
doors of the rooms around it. Someone walking into a room is hidden by the
door frame before their feet reach a line drawn at the door, and nobody is
ever seen on the far side. A plain line then counts nobody.

1. Draw the line along the door frame on the floor, as far as the feet go
   before the person disappears. Make it a little longer than the opening.
2. Point the solid arrow into the room (**Flip forward direction** if not).
3. In the inspector, under **Doorway**, tick **The camera cannot see past
   this line**. The line's label on the canvas now ends in `(doorway)`.

A person who walks up to the line and disappears there now counts as a
forward crossing, and a person who appears there and walks away counts as a
reverse crossing. The crossing is counted when the tracker gives the person
up, a few seconds after they vanished, and is dated when they were last
seen. On the **Events** tab its direction reads `forward (doorway)`.

Where people come into view right next to a line (for example out of a room
under the camera), their first boxes can be only an arm or a torso. Raise
**Minimum track age** under **Advanced** on that line to 4 so those first
boxes cannot cross it.

## Next

[Guide 06](06-pet-watch.md) watches a pet instead of people.
[Guide 07](07-street-by-class.md) counts people, bicycles and cars separately.
