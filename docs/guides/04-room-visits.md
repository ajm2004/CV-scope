---
title: Count visits to a room with a webcam
level: Beginner
time: 15 minutes, then as long as you record
needs: A webcam, built in or USB, that sees the room
summary: Count how many people come into a room, how long each one stays and when they leave, with one zone over the whole picture.
learn:
  - Place a webcam so it sees the people in a room
  - Count real visits instead of flickers at the edge of the picture
  - Choose the minimum visit and the allowance for short exits
  - Read visits, length of stay and the busiest hours
pages: [Cameras, Experiments, Scene Builder, Live, Data, Analysis]
---

# Count visits to a room with a webcam

This guide turns a webcam into a visit counter for a room, such as a bedroom,
a shared office or a common room. For every visit CV-Scope records when
someone came in, how long they stayed and when they left. Over days it adds up
the visits, the time the room was in use and the busiest hours.

CV-Scope counts people, not identities. It cannot tell who came in, and
someone who leaves and comes back starts a new visit. It stores events and
anonymous track summaries, and pictures only if you turn on video recording.
Tell the people who use the room that the camera counts visits.

The setup is close to the screen-time setup in
[guide 03](03-webcam-screen-time.md). The difference is that people walk in
and out of a room, often at the edge of the picture, so the zone needs two
settings that a desk does not.

## Before you start

1. Start CV-Scope and open http://127.0.0.1:8420, as in
   [guide 03](03-webcam-screen-time.md#before-you-start).
2. Close other apps that use the webcam. On Windows only one app can use a
   webcam at a time.

If CV-Scope was already running before an update, stop it with `Ctrl+C` and
start it again, so that the new version is used.

## Step 1. Place the camera

Where the camera sits decides what CV-Scope can count.

* **Aim at the part of the room where people spend time,** such as the bed,
  the sofa or the desk, and at the door if you can.
* **Mount it high,** on a shelf or a wardrobe, tilted down. From there people
  are seen whole and do not hide each other. A webcam at desk height sees
  people close to it only from the waist up, and furniture hides the people
  behind it.
* **Keep windows out of the picture.** Against bright daylight people turn
  into dark shapes that the detector misses.
* **Keep the room lit while you record.** A webcam sees nothing in the dark,
  and people it cannot see are not counted.
* **Keep mirrors, TV screens and pictures of people out of view,** or cover
  them with an ignore area, as in [guide 08](08-ignore-areas.md). The detector
  counts a person on a screen or in a mirror like anyone else.

## Step 2. Add the camera and the experiment

1. Add the webcam on **Cameras**, as in
   [guide 03, step 1](03-webcam-screen-time.md#step-1-add-the-webcam), and
   name it, for example, `ROOM-CAM`. Add it as a new camera even if it is
   already listed, for example from guide 03. Zones belong to a camera, so the
   new entry starts with an empty scene, and the zones of other studies stay
   out of the room results. Only one entry of the same webcam can record at a
   time.
2. Open **Experiments**, click **New experiment**, and fill in these fields:
   * **Name:** `Room visits`.
   * **Project:** the project the webcam belongs to.
   * **Camera:** your webcam.
   * **Objects to track:** **Person** only.
3. Click **Create experiment**.
4. Under **Detection and tracking**, keep **Detector** on
   **Recommended for this system (AUTO)** and **Tracker** on **ByteTrack**.
5. Tick **Advanced settings** and set these values:
   * **Processing FPS:** `10`. Ten frames a second follow people walking
     through a room, with a third of the work of the webcam's 30.
   * **Frames to keep searching for a lost object**, under
     **ByteTrack settings:** `30`. At 10 frames a second that is 3 seconds.
     Someone hidden for a moment behind another person or the door keeps
     their track.
6. Click **Save**.

## Step 3. Draw the room zone

1. On the experiment page, click **Scene builder**. It opens on the live
   picture of the webcam.
2. Press `Z` for the zone tool. Click the four corners of any rectangle, and
   double-click the last corner to finish it.
3. In the inspector on the right, set these fields:
   * **Name:** `Room`.
   * **Object to track:** keep Person ticked.
   * Click **Cover the whole image**. The zone now fills the picture.
   * Under **Measure**, keep all four boxes ticked.
   * **Ignore visits shorter than:** `5` seconds. Someone who looks in
     through the door or walks straight through is not counted.
   * **Ignore exits shorter than:** `2` seconds.
   * **Flag visits longer than:** optional, for example `3600`. Each visit
     longer than an hour then records a *Dwell exceeded* event.
   * **Flag occupancy above:** optional, for example `3`. More than three
     people in the room at once then records an *Occupancy exceeded* event.
4. Click **Save** in the top bar, or press `Ctrl+S`.

**Why the zone must reach the edges of the picture.** CV-Scope places each
person at the bottom centre of their box, where the feet are. A person close
to the camera is cut off by the bottom edge of the picture, so their position
is on that edge. A zone that stops above the edge misses them, or catches them
only for split seconds when their box happens to end a little higher.
**Cover the whole image** puts the zone exactly on the edges. Corners within
about 1 % of an edge count as on it, and corners you drag close to an edge
snap onto it.

**When the camera also sees outside the room,** such as a hallway through the
open door, draw the zone by hand over the room only, and still take it down
to the bottom edge of the picture. People outside then fall outside the zone.

**Why 5 and 2 seconds.** When the detector misses a person for a moment, the
tracker can give them a new track number when it finds them again, and it
keeps the old number for the lost-object time. That time is
**Frames to keep searching for a lost object** divided by the frames per
second CV-Scope really processes: 30 ÷ 10 = 3 seconds here. A minimum visit
longer than that stops one person from counting as two people for a moment.
The 2-second allowance matters for a zone drawn over part of the picture:
someone standing on its border keeps one visit instead of starting a new one
each time they lean out.

## Step 4. Test it

A two-minute test shows whether the camera and the zone work:

1. Click **Start**. After a few seconds of start-up the camera view shows a
   box around each person it sees.
2. Walk in and stay in view for about 30 seconds. Walk out and stay out for
   20 seconds. Come back for a minute, then leave again.
3. Watch the run on **Live**:
   * **Pipeline** shows about `10 fps`. In a dim room some webcams deliver
     fewer frames. If it shows less, raise **Ignore visits shorter than** to
     stay above the lost-object time, for example to `8` seconds at 5 fps.
   * **Zone occupancy** shows `1` from about 5 seconds after you came in
     until about 3 seconds after you left.
   * Under **Recent events**, a *Zone entry* appears 5 to 7 seconds after you
     came in. Its time is the moment you came in, counted in minutes and
     seconds from **Start**. A *Zone exit* appears 3 to 5 seconds after you
     left, with the moment you were last seen.
4. Click **Stop**.

On the experiment page, find the run under **Runs** and click **Results**.
The `Room` zone should show **Visits** 2, a **Longest visit** of about a
minute, a **Mean visit** of about 45 seconds and a **Max occupancy** of 1. If
it shows many short visits instead, see [Troubleshooting](#troubleshooting).

## Step 5. Record

1. Click **Start** and leave CV-Scope running. Closing the browser does not
   stop the run. Closing the CV-Scope window does. While the computer sleeps
   nothing is counted, and a visit can stretch across the gap, so turn off
   sleep in the power settings for long recordings.
2. Click **Stop** when you are done. A visit still open at that moment is
   closed and counted.

One run can last for days. To compare days, start a new run each day, or read
the **occupied time per hour** table described below.

**To keep video of each visit,** turn on **Video recording** on the experiment
page before you click **Start**. Choose **Clips around events** and tick
**Zone entry** and **Zone exit**. Each visit then keeps a short clip of the
person coming in and going out, with the boxes and track numbers drawn in, so
you can check every count. [Guide 23](23-record-video.md) explains the
settings, where the video is kept and how long.

## Step 6. Read the room statistics

Open the run's **Results**. The **Zones (occupancy and dwell)** panel shows
these values for the `Room` zone:

| Column | What it tells you about the room |
| --- | --- |
| **Occupied time** | Time with at least one person in the room. |
| **Total time, all objects** | All visits added up. Two people for an hour count as two hours. |
| **Visits** | Completed visits. |
| **Mean visit** / **Median visit** / **Longest visit** | How long people stayed. One very long stay does not pull up the median. |
| **Max occupancy** | The most people in the room at the same time. |
| **Long visits flagged** | Visits longer than **Flag visits longer than**. |

Below the table, **occupied time per hour** shows how long the room was in
use in each clock hour that had a visit.

Other places to read the results:

* **Each visit:** open **Data** and set **Event type** to **Zone exit**. Each
  row is one visit: **Timestamp** is when the person left and **Duration** is
  how long they stayed. The *Zone entry* rows hold the times people came in.
* **Several runs:** the **Analysis** page adds up the runs of an experiment,
  for example one run per day.
* **A spreadsheet:** the **CSV** button on the **Data** page exports the rows
  you filtered.

The **Speed** column shows *frame widths/s* because the camera is not
calibrated. Speed does not matter for visits.
[Guide 16](16-calibrate-speed.md) explains how to measure it in metres per
second.

## How visits are counted

* A visit starts when a person is first seen in the zone. It is reported once
  it has lasted longer than **Ignore visits shorter than**, and those first
  seconds count.
* Stepping out of the zone for less than **Ignore exits shorter than** keeps
  the visit going.
* When CV-Scope loses sight of a person, for example behind a door or under
  a blanket, the visit waits for the lost-object time. If the tracker finds
  them again in about the same place and shape, the visit goes on. Otherwise
  it ends at the moment they were last seen, so the time they were not seen
  does not count.
* Two people who come in together make two visits, and **Max occupancy**
  shows 2.
* A person can get a new track number when they are hidden for longer than
  the lost-object time, reappear somewhere else or in another posture, such
  as sitting up from under a blanket, or are seen only in part at the edge of
  the picture. That splits one stay into two visits. **Occupied time** is not
  affected, so it is the steadiest figure for how much the room is used.

## Troubleshooting

* **Many visits of less than a second, although someone stayed for minutes.**
  The zone stops above the bottom edge of the picture, so people close to the
  camera are outside it. Select the zone, click **Cover the whole image** and
  save. Check that **Ignore visits shorter than** is `5`.
* **Max occupancy is 2 or 3 with one person in the room.** The detector drew
  two boxes on one person for a moment, or the person got a new track number
  while the old one was still kept. Keep **Ignore visits shorter than** longer
  than the lost-object time, for example 5 seconds against 3. Check the frame
  rate that **Pipeline** shows on **Live**: at 5 fps, 30 frames last 6 seconds.
* **One long stay shows up as several visits.** Raise
  **Frames to keep searching for a lost object**. At 10 frames a second, each
  10 frames add a second. Raise **Ignore visits shorter than** with it, so it
  stays longer than the lost-object time. When people often sit close
  together or cross in front of each other, try the BoT-SORT tracker with the
  **Colour histogram** appearance setting, described in
  [guide 19](19-detectors-and-trackers.md).
* **Nobody is counted in the evening.** The room is too dark for the webcam.
  Turn on a light.
* **No boxes at all, even in daylight.** Check that **Objects to track**
  includes Person, and see the troubleshooting in
  [guide 03](03-webcam-screen-time.md#troubleshooting).
* **People outside the room are counted.** The zone covers the hallway or a
  window. Draw it by hand over the room only, down to the bottom edge.

## Next

* When the camera sees the door, [guide 05](05-doorway-in-out.md) counts
  people going in and out with a gate across the doorway. For the doors of
  rooms around a hall, which the camera cannot see through, see
  [its last section](05-doorway-in-out.md#a-door-the-camera-cannot-see-through).
* [Guide 09](09-room-occupancy.md) adds a crowding alert to an occupancy
  zone.
* [Guide 17](17-check-accuracy.md) shows how to check how accurate the counts
  are.
* [Guide 23](23-record-video.md) keeps video clips of the visits for review.
