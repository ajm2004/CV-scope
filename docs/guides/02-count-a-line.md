---
title: Count people crossing a line
level: Beginner
time: 15 minutes
needs: The corridor sample video
summary: Draw one counting line over the corridor clip, run an experiment, and read how many people crossed it in each direction.
learn:
  - Add a video file as a camera
  - Pick a frame and draw a counting line
  - Create an experiment and start a run
  - Read line crossings and the event list
pages: [Cameras, Scene Builder, Experiments, Data]
---

# Count people crossing a line

A counting line is the simplest measurement in CV-Scope. Each time a tracked
person crosses the line, CV-Scope counts the crossing and records its
direction and time.

CV-Scope places each object at the bottom centre of its box, about where the
feet touch the floor. Draw lines on the floor where people walk, not at head
height.

## Step 1. Add the corridor video

Skip this step if you did guide 01. The camera `Corridor` then exists
already. Open it from **Cameras** and click **Open scene builder**.

1. Open **Cameras** and click **Add camera**.
2. Set **Camera name** to `Corridor` and pick a **Project**. If the list is
   empty, create a project on the **Projects** page first.
3. Set **Connection type** to **Video file**.
4. In **Or use a file already on this computer**, type the full path of
   `samples\videos\people-detection.mp4` and click **Use file**. To copy the
   file into CV-Scope's data folder instead, use **Upload a video file**.
5. Click **Add camera**. The first frame of the clip appears on the right.
6. Click **Open scene builder**.

## Step 2. Draw the counting line

1. Drag the slider at the bottom of the Scene Builder to about `00:03` and
   release it. The frame shows a person walking across the room. A frame with
   people in it shows where they walk. Any frame works for drawing.
2. Press `L`, or click **Line** in the tool column on the left.
3. Click on the floor at the foot of the back wall, halfway across the
   picture. Then click at the bottom edge of the picture, straight below the
   first point. A point close to the edge snaps onto it.
4. The inspector on the right now shows the new line. Set **Name** to
   `Middle line`.
5. Under **Object to track**, keep **Person** ticked.
6. Under **Direction**, keep **Both**. The solid arrow on the line points
   forward. The short, faint arrow points in reverse.
7. Under **When an object crosses**, keep both boxes ticked: **Count the
   crossing** and **Record an event with time, direction and track**.
8. Click **Save** in the top bar, or press `Ctrl+S`.

## Step 3. Create the experiment and run it

1. Click **New experiment** in the top bar of the Scene Builder.
2. Set **Name** to `Count the middle line`. The project and the camera are
   already filled in. Under **Objects to track**, keep **Person**. Click
   **Create experiment**.
3. The new experiment is now selected in the top bar. Click **Start**.
4. The picture switches to the run. You see a box around each person, their
   anonymous track number and a short trail. Counters such as
   `Middle line forward` and the newest events appear in the bottom bar.
5. Wait for the run to finish. A video file is processed as fast as the
   computer allows, so the 50-second clip takes from a few seconds to a few
   minutes. The status in the top bar then reads **stopped**, and the bottom
   bar shows **Last run … completed** with a **Results** link.

## Step 4. Read the counts

1. Click **Results** at the bottom of the Scene Builder.
2. On the **Summary** tab, the **Line crossings** panel lists
   **Middle line**.
3. Open the **Events** tab. It lists every crossing with its **Media time**,
   **Direction** and **Track** number. Click a row to see all its fields, and
   **Jump to video** to watch that moment.

| Column | Meaning |
| --- | --- |
| **Total** | All crossings of the line. |
| **Forward** | Crossings in the direction of the solid arrow. For this line that is right to left. |
| **Reverse** | Crossings the other way. |
| **By class** | Crossings for each kind of object. |

With the recommended detector we counted 3 crossings on the sample: 2 forward
and 1 reverse. Another detector can differ by one or two.

## Why someone was not counted

* The person walked along the line rather than across it.
* The person was hidden behind someone else while crossing. The tracker must
  see a person on both sides of the line.
* The person appeared right on the line. A track has to be 2 frames old
  before it can count. You can change this under **Advanced** in the
  inspector, as **Minimum track age (frames)**.
* The same person crossed back within a second. **Debounce (seconds)** under
  **Advanced** ignores such repeats.

## Next

[Guide 05](05-doorway-in-out.md) uses the direction to count people coming in
and going out. [Guide 17](17-check-accuracy.md) checks the counts against your
own.
