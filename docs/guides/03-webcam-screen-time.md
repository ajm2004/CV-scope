---
title: Measure screen time with a webcam
level: Beginner
time: 10 minutes, then as long as you record
needs: A webcam, built in or USB
summary: Measure how long someone sits at a desk, using the computer's own webcam, one zone and the dwell time CV-Scope records for it.
learn:
  - Add a USB or built-in webcam
  - Move a camera into the experiment's project
  - Cover the whole picture with one zone
  - Read occupied time and time per clock hour
pages: [Cameras, Experiments, Scene Builder, Data]
---

# Measure screen time with a webcam

This guide sets up CV-Scope to measure how long someone sits in front of a
computer, using the computer's own webcam (built-in or USB). It takes about ten
minutes.

CV-Scope measures presence in front of the camera. It does not know whether
the person looks at the screen, so time spent reading a book at the desk
counts too.

Nothing is recorded while you set up. The live view is processed in memory
only. A run stores events, such as visit start, visit end and duration, a
summary of each anonymous track, and sampled positions unless you switch
those off. It stores no pictures unless you turn on video recording, as in
[guide 23](23-record-video.md). **Settings** lists everything this
installation stores.

## Before you start

1. Start CV-Scope from the project folder and leave the window open:

   ```
   .venv\Scripts\python.exe -m pathscope.cli serve
   ```

2. Open http://127.0.0.1:8420 in the browser.
3. Close other apps that use the webcam, such as Teams, Zoom, the Camera app or
   a browser tab in a video call. On Windows only one app can use a webcam
   at a time.

If CV-Scope was already running before an update, stop it with `Ctrl+C` and
start it again, so that the new version is used.

## Step 1. Add the webcam

Skip this step if the camera is already listed on the **Cameras** page.

1. Open **Cameras** and click **Add camera**.
2. Name it, for example `HOME-CAM`, and pick the project it belongs to.
3. Set **Connection type** to **USB / built-in camera**.
4. Set **Camera device** to **Device 0**. Laptops list the built-in camera
   first. A second camera is usually Device 1.
5. Click **Test connection**. The result should say the camera delivers
   frames.
6. Click **Add camera**, then select the camera in the list. Its live picture
   appears on the right and stays on while the page shows it.

The camera's default resolution, often 640 × 480, is enough for a person at a
desk. The detector looks at a 640-pixel-wide copy of the picture anyway. A
higher resolution only helps for people far from the camera, together with a
higher **Inference resolution (px)**, as explained in
[guide 19](19-detectors-and-trackers.md).

## Step 2. Choose the experiment and the camera

An experiment holds the settings of the measurement. Each time you press
Start, it records one run.

**To create a new experiment**, open **Experiments**, click
**New experiment**, and fill in these fields:

* **Name:** `Screen time`.
* **Project:** the project you want, for example `HOME Room Dwell`.
* **Camera:** your webcam. A camera that belongs to another project is listed
  under **Other projects**. CV-Scope then offers to move it into this project.
  Leave that box ticked.
* **Objects to track:** **Person** only.

Click **Create experiment**.

**To use an existing experiment**, open it and pick the webcam in the
**Camera** list. If the camera is listed under **Other projects**, click
**Move camera to this project**, then **Save**.

The experiment page now shows the camera's live picture under the camera
settings. That confirms CV-Scope can see the camera.

## Step 3. Draw the desk zone

1. On the experiment page, click **Scene builder**. It opens on the live
   picture of the webcam.
2. Press `Z` for the zone tool. Click the four corners of any rectangle, and
   double-click the last corner to finish it.
3. In the inspector on the right, set these fields:
   * **Name:** `Desk`.
   * **Object to track:** keep Person ticked.
   * Click **Cover the whole image**. The zone now fills the picture.
   * Under **Measure**, keep all four boxes ticked.
   * **Ignore visits shorter than:** `5` seconds. Someone walking past the
     desk is then not counted.
   * **Flag visits longer than:** optional, for example `3600`. After an hour
     without a break, a *Dwell exceeded* event is recorded.
4. Click **Save** in the top bar, or press `Ctrl+S`.

**Why the zone must reach the bottom edge.** CV-Scope places each person at
the bottom centre of their box, where the feet would be. At a desk the webcam
sees your head and shoulders, so your box is cut off by the bottom edge of the
picture. Your position is on that edge. A zone that stops a little above the
edge misses you entirely. **Cover the whole image** takes care of this.
Hand-drawn corners dragged close to an edge snap onto it.

**When other seats are in view,** such as a sofa behind the desk, draw the zone
only over the lower part of the picture, still down to the bottom edge. A
person close to the camera is cut off at the bottom edge. Someone farther away
has their feet higher up in the picture and falls outside the zone.

**To draw over a still picture,** press `F` or click **Freeze frame**. This also
switches the camera off. **Resume live** turns it back on.

## Step 4. Tune the experiment

Go back to the experiment page with **Edit experiment** in the Scene Builder
top bar.

1. Keep **Detector** on **Recommended for this system (AUTO)**. Even the
   smallest detector, YOLO11n, finds one person close to the camera, so on a
   slow computer you can pick it instead.
2. Set **Tracker** to **ByteTrack**.
3. Tick **Advanced settings** and set these values:
   * **Processing FPS:** `5`. A seated person moves little, and 5 frames per
     second uses a fraction of the processor time of 30.
   * **Frames to keep searching for a lost object:** `50`. At 5 frames per
     second that is 10 seconds. Looking away or leaning out of view for a few
     seconds then does not end the visit.
4. Optionally, add a reminder rule. Under **Rules**, click **Add rule** and
   choose **Remains in zone for…**. Pick **Desk**, enter `1800` seconds, and
   type `Long session` after **CREATE EVENT**. Each sitting longer than 30
   minutes then records a *Long session* event.
5. Click **Save**.

## Step 5. Record

1. Click **Start**. The camera view switches to the run's picture, with a box
   around each person it sees, after a few seconds of start-up. The live view
   hands the camera to the run by itself.
2. Sit down normally and check that a box appears around you. If no box
   appears, see [Troubleshooting](#troubleshooting).
3. Leave it running. Closing the browser does not stop the run. Closing the
   CV-Scope window does.
4. Click **Stop** when you are done. The button is on the experiment page, in
   the Scene Builder and on the **Live** page. A visit still open at that
   moment is closed and counted.

**Two-minute test before a long recording:** start, sit for a minute, leave
the room for 20 seconds, come back for another minute, then stop. The results
should show two visits and about two minutes of occupied time.

## Step 6. Read the screen time

Open the experiment, find the run under **Runs**, and click **Results**. The
**Zones (occupancy and dwell)** panel shows these values:

| Column | Meaning |
| --- | --- |
| **Occupied time** | Time with at least one person in the zone. This is the screen time. |
| **Total time, all objects** | All visits added up. Two people for one minute count as two minutes. |
| **Visits** | Completed sittings. |
| **Mean visit** / **Median visit** / **Longest visit** | Length of the sittings. |
| **Long visits flagged** | Visits longer than **Flag visits longer than**. |

Below the table, **occupied time per hour** shows a bar for each clock hour of
the run.

Other places to read the results:

* **Several runs:** the **Analysis** page adds up the runs of an experiment,
  for example one run per evening.
* **Each visit:** the **Data** page, filtered to the event type **Zone exit**.
  It lists every sitting with its end time and **Duration**.
* **Export:** the **CSV** button on a run, or the export on the Data page,
  gives you the same rows for a spreadsheet.

## How the time is counted

* A visit starts when you are first seen in the zone. It is only reported
  after **Ignore visits shorter than** has passed, but those first seconds are
  counted.
* A visit ends when you leave the zone, when the run stops, or when CV-Scope
  has not seen you for the lost-object time. With the settings above that is
  50 frames, or 10 seconds. The visit then ends at the moment you were last
  seen. Time in which you were not seen is not counted, and a new visit starts
  when you come back.
* Brief misses shorter than the lost-object time are bridged and stay part of
  the same visit.
* The detector needs to see a head and shoulders. A dark room, a camera
  pointed at the ceiling, or a face filling the whole picture can make it miss
  you, and that time is then not counted. Check the run view once in each new
  setup.

## Troubleshooting

* **"Connecting to the camera…" does not go away, or "The camera could not be
  opened".** Another app is using the webcam. Close it, and CV-Scope connects
  on its own within a few seconds.
* **The camera is missing from the experiment's camera list.** It belongs to
  another project. Look under **Other projects** in the same list and move it.
* **The run starts but shows no boxes.** Check that **Objects to track**
  includes Person, and turn on a light. In **Advanced settings**, under
  **ByteTrack settings**, lower **Detection confidence to start or continue a
  track** from 0.5 to about 0.3. The tracker only starts a track from a
  detection at least that confident.
* **One sitting is split into many short visits.** Raise **Frames to keep
  searching for a lost object**. At 5 fps, each 5 frames adds one second.
* **The picture is sideways or upside down.** On the **Cameras** page, select
  the camera, tick **Advanced settings**, set **Rotation** and click
  **Save camera**.
* **The run failed with "The camera stopped delivering frames".** The webcam
  was unplugged, or another app took it over during the run. Reconnect it and
  press **Start** again. The earlier runs keep their results.

## Next

[Guide 04](04-room-visits.md) counts visits to a whole room, with several
people coming and going. [Guide 05](05-doorway-in-out.md) counts people going
in and out of a door with a direction-aware gate.
[Guide 06](06-pet-watch.md) uses the same zone technique to watch a pet
instead of a person.
