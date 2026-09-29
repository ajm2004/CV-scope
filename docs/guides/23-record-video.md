---
title: Record video of events for review
level: Advanced
time: 20 minutes
needs: A live camera, such as a webcam, and some free disk space
summary: Keep a clip around each event, one clip per visit from entry to exit, or the whole run, and watch why each event fired on the Video review page.
learn:
  - Choose between a clip per event, a clip per visit and the whole run
  - Record a whole visit, so the dwell between entry and exit is in the picture
  - Pick the events that start a clip and the seconds around them
  - Watch the clip of an event and step through it frame by frame
  - Keep disk use and the people you record under control
pages: [Experiments, Live, Settings]
---

# Record video of events for review

By default CV-Scope keeps no pictures of a live camera. It analyses each frame
in memory and stores only the events. When you need to see what happened, for
example to check a count, to show why an event fired or to keep a visual audit
trail, turn on video recording for the experiment. It works with USB, built-in
and network cameras. A run on an uploaded video needs no recording, because
that video is kept already.

> [!CAUTION]
> Video shows people. Tell everyone who can appear in the picture, follow the
> rules that apply where you record, and keep the video only as long as you
> need it.

## Step 1. Choose what to record

On the experiment page, the **Video recording** panel sits under
**Detection and tracking**. **Record video** offers four choices:

| Choice | What it keeps | Size at 640 × 480 and 10 frames per second |
| --- | --- | --- |
| **No video (default)** | Nothing | None |
| **A clip around each event** | Each event with the seconds before and after it | About 7 MB for a 20-second clip |
| **From entry to exit (one clip per visit)** | The whole stay of an object, entry, dwell and exit in one file | About 20 MB per minute of visit |
| **The whole run** | Everything the camera sees, in files of 10 minutes | About 0.6 GB per hour |

A clip per event suits an audit of events: every event keeps the seconds that
explain it, and quiet hours take no space. **From entry to exit** suits a
visit you want to watch as a whole: with a clip per event you would get an
entry clip and an exit clip with a hole where the person stood in the room,
and with this mode you get one file that runs from the entry to the exit.
Record the whole run when you also need the time in which nothing was counted,
for example to look for people the detector missed.

## Step 2. Set up clips around events

1. Set **Record video** to **A clip around each event**.
2. **Seconds before the event:** `5`. The clip starts this long before the
   moment the event describes, so it shows how the person got there.
3. **Seconds after the last event:** `10`. Events close together share one
   clip. Each new event moves the end out, up to 5 minutes per clip.
4. **Events that start a clip:** tick the events you want to see, for example
   **Zone entry** and **Zone exit** for the room of
   [guide 04](04-room-visits.md). With none ticked, every recorded event
   starts a clip.
5. Keep **Draw boxes, track numbers, zones, lines and the time into the video**
   ticked. The video then shows what CV-Scope saw: the box and number of each
   person, the zones and lines, the clock time, and the name of each event as
   it happens.
6. **Video frame rate (frames per second):** `10` is enough to follow people
   walking. Lower values make smaller files. The video never has more frames
   per second than the run processes.
7. Click **Save**.

An event can describe an earlier moment. A zone entry is reported only after
**Ignore visits shorter than**, and a zone exit when the tracker gives up on a
person. Their clips still start before that moment, as long as the event is
reported within 30 seconds.

## Step 2b. Or record whole visits

1. Set **Record video** to **From entry to exit (one clip per visit)**.
2. **Seconds before the event** and **Seconds after the exit** work as before:
   the file starts that long before the entry and ends that long after the
   exit.
3. **Out of sight before a visit counts as over (s):** `3`. A visit also ends
   when the object leaves the picture and no exit event ever arrives, for
   example when the tracker loses someone at the edge of the frame. Raise it
   for a scene with pillars or furniture people disappear behind.
4. **Events that start a visit:** leave empty to let any recorded event start
   one, or tick **Zone entry** for a room. A **Zone exit** or a finished
   **Route** for the same object ends it.
5. Several people share one file: it runs from the first entry until the last
   one has left. A visit longer than five minutes continues in the next file,
   which starts where the previous one ended, so nothing of the stay is lost.

In the test that covers this mode, a visit from 8 s to 40 s produced a single
39-second file (3 s before the entry, 4 s after the exit). The same run with a
clip per event produced two clips of about 7 seconds, with the 27 seconds of
dwell missing between them.

## Step 3. Record

1. Click **Start**. On **Live**, the run shows **Video on**, or **Recording**
   while a file is being written, followed by the number of files saved.
2. Click **Stop** when you are done. A clip that is still being written is
   finished and saved.

Recording changes nothing else: the counts, events and results are the same as
without video.

## Step 4. Watch an event

1. On the experiment page, find the run under **Runs**. Its button reads
   **Video** with the number of files. Click it. On the run's **Results**,
   **Video review** opens the same page.
2. The timeline covers the whole run. Its shaded parts have video, and a red
   dot in the event list marks each event with video.
3. Click an event. The player opens the file that contains it, 1.5 seconds
   before the event. Use **Play**, **−1 frame**, **+1 frame** and the speed
   list to look closely.
4. If you click a moment without video, a note says so.

Under the player, **Recorded video** lists each file with the time it was
recorded, its length, the event that started it and its size:

* **Play** starts the file from its beginning.
* **Download** saves it as MP4 or WebM, which common video players open.
* **Delete** removes one file. **Delete all video of this run** removes every
  file of the run and keeps its events and results.

## Step 5. Keep disk use and the video under control

* **Retention.** In **Settings**, **Video retention (days)** deletes recorded
  video that many days after it was recorded. CV-Scope checks once an hour.
  `0`, the default, keeps video until you delete it. Uploaded videos are not
  affected.
* **Deleting a run** deletes its video too.
* **What is stored.** **Settings** lists recorded video under
  **What this installation stores**, with the experiments that record, the
  number of files and their total size.
* **Where the files are.** In the data folder, under `recordings`, with one
  folder per run. Back them up with the rest of the data folder, as in
  [guide 21](21-deploy-a-study.md).
* **No identities.** The video shows anonymous track numbers only. Names and
  plates from the licensed recognition modules are never drawn into it.

## How recording works

* The video is made of the frames the run analyses, so every box in it belongs
  to that very frame. Its frame rate is at most **Video frame rate** and at
  most the rate at which the run processes frames.
* The video is written in the background. When the computer cannot keep up, a
  frame is skipped rather than slowing down the analysis.
* The video follows the run's clock, so a point in the video is the same
  moment as the event time. After a pause of more than 3 seconds, for example
  while a network camera reconnects, a new file starts.
* Clips are saved as H.264 MP4 on Windows. The whole run is saved as WebM,
  about a third of the size, which takes more processor time to write.

## Troubleshooting

* **The panel shows a note instead of the choices.** The camera plays an
  uploaded video. Its video is kept already: open **Video review** from the
  run's **Results**.
* **The run has no video.** The setting applies to runs started after you
  click **Save**. With clips, only the ticked event types start one.
* **Live shows Video failed.** CV-Scope could not write a file, for example
  because the disk is full. The analysis goes on without video. Point at the
  label to see the reason.
* **The files are too large.** Lower **Video frame rate**, record clips
  instead of the whole run, or set **Video retention (days)**.

## Next

* [Guide 17](17-check-accuracy.md) judges events one by one. With recorded
  video it works for live cameras too.
* [Guide 21](21-deploy-a-study.md) plans disk space, backups and privacy for a
  long study.
