---
title: Choose and benchmark the detector and tracker
level: Advanced
time: 30 minutes
needs: The corridor sample video and one or more installed detectors
summary: See what this computer can run, benchmark detectors on your own footage, pick presets, and switch to BoT-SORT for moving cameras or crowded scenes.
learn:
  - Read the hardware recommendation
  - Install and benchmark detectors
  - Choose presets and advanced inference settings
  - Use BoT-SORT with camera motion and appearance matching
pages: [Hardware, Models, Experiments]
---

# Choose and benchmark the detector and tracker

Two components decide how well CV-Scope sees:

* **The detector** finds objects in each frame. Larger detectors find more,
  especially small or distant objects, but need more computing power.
* **The tracker** links the detections of consecutive frames into one track
  per object. It decides whether a person keeps one track number from
  entering to leaving.

## Step 1. See what this computer can run

1. Open **Hardware**. It lists the processor, memory, graphics card and the
   acceleration CV-Scope can use, such as CUDA on NVIDIA cards or Metal on
   Apple computers.
2. **Recommended detectors for this system** lists four tiers: **Fast**,
   **Balanced**, **High accuracy** and **CPU mode**. The one marked
   **recommended** is used when an experiment is left on automatic.
3. Click **Probe again** after installing a new graphics driver or card.

## Step 2. Install detectors

1. Open **Models**. The **Detector catalog** lists each detector with its size,
   the memory it needs, dots for relative accuracy and speed, and its licence.
2. Click **Install** on the detectors you want to compare. The **Status**
   column shows the download and then **installed**.
3. Click a detector's name for details, including the classes it knows.

> [!NOTE]
> The YOLO detectors come from Ultralytics under the AGPL-3.0 licence. The
> torchvision detectors are BSD licensed. The **Licence** column shows each
> one. Read the notes in the details before you use CV-Scope in a product.

## Step 3. Benchmark on your own footage

A benchmark runs about 120 frames of the most recently added video through the
detector and the tracker, and measures the time each part takes.

1. On **Models**, click **Benchmark** next to an installed detector.
2. Keep **Device** on **Auto**. Leave **Inference size (px)** empty to use the
   detector's default.
3. Choose the **Tracker** you plan to use, and click **Run benchmark**.
4. The result appears under **Benchmarks on this machine**. Compare
   **Pipeline FPS**, the frames per second of the whole chain.

As an example, YOLO11n with ByteTrack ran at about 130 frames per second on a
desktop with a mid-range NVIDIA card. The same detector on a laptop processor
runs far slower.

**Rule of thumb.** Pick the largest detector whose **Pipeline FPS** is at
least twice the processing rate you need for each camera running at the same
time. For three cameras at 5 frames per second each, that is 30 or more.

The same benchmark runs from the command line:

```
.venv\Scripts\python.exe -m pathscope.cli benchmark yolo11n --video samples\videos\people-detection.mp4
```

## Step 4. Set the detector of an experiment

On the experiment page, in **Detection and tracking**:

| Setting | What it does |
| --- | --- |
| **Detector** | **Recommended for this system (AUTO)** follows the hardware recommendation. Or pick an installed detector. |
| **Preset** | With AUTO, picks the tier: **FAST**, **BALANCED** or **ACCURATE**. **CUSTOM** opens every setting. |
| **Tracker** | **ByteTrack** or **BoT-SORT**. |
| **Playback** | Paces a video file at its real speed, for a live feel. Off processes as fast as possible. |

When a preset asks for a detector that is not installed, the run uses another
installed detector from the table on **Hardware**. Its results page says so
under **Diagnostics**, in the **Configuration snapshot**, on the `resolution`
line. If none of those detectors is installed, the run does not start. AUTO
and the presets follow the hardware recommendation only while
**Default detector** on **Settings** is empty.

Tick **Advanced settings** for the details:

| Setting | When to change it |
| --- | --- |
| **Device** | Force the processor or the graphics card. |
| **Inference resolution (px)** | Larger finds small, distant objects, at the cost of speed. When it is empty, the camera's own **Inference resolution (px)** applies, then the detector's default. |
| **Confidence threshold** | Lower finds more but also more false objects. The default is 0.25. |
| **Box overlap threshold (IoU)** | Controls when two overlapping boxes count as one object. |
| **Processing FPS** | Frames analysed per second. Fewer saves processing. |
| **Frame skipping** | Skips frames after each processed frame. |

## Step 5. Choose the tracker

**ByteTrack** is fast and works well for a fixed camera. Keep it unless you see
one of the problems below.

**BoT-SORT** adds two things. Set **Tracker** to **BoT-SORT** and tick
**Advanced settings** to see them under **BoT-SORT settings**:

* **Compensate for camera movement.** For a camera that shakes in the wind or
  gets bumped, it measures how the whole picture moved and corrects the
  tracks. **Optical flow (recommended)** suits most cases. Choose
  **Off (the camera never moves)** for a fixed indoor camera.
* **Use appearance to keep identities through occlusions.** When people cross
  behind each other, appearance helps to keep their track numbers apart:
  * **Colour histogram (fast, no model)** compares clothing colours.
  * **Deep features, ResNet-18 (GPU recommended)** is more reliable. Install
    **ResNet-18 appearance features** on **Models** first.
  * A custom re-identification model in ONNX format can be placed in the
    `reid` folder of the models directory, `data\models\reid` by default. It
    then appears in the list.

Appearance summaries are held in memory only, while an object is tracked. They
are never stored and never compared across runs.

The tracker settings that matter most:

* **Frames to keep searching for a lost object.** Counted in processed frames.
  Raise it when people disappear behind a pillar for a while. Too high and two
  different people can get the same track.
* **Frames before a new object is reported.** Raise it when short false
  detections create tracks that count.
* **Detection confidence to start or continue a track.** The tracker starts a
  track only from a detection at least this confident, 0.5 by default. When
  objects are missed, lower it to about 0.3 together with the detector's
  **Confidence threshold**. BoT-SORT has a separate
  **Detection confidence to start a new track**.

## Step 6. Check the choice

Settings are only better when the results are better. Compare two experiments
that differ only in the detector or tracker, as in
[guide 14](14-compare-conditions.md). Then judge a sample of events for each, as
in [guide 17](17-check-accuracy.md).

## Next

[Guide 20](20-webhooks-and-api.md) sends events to other tools as they
happen, and reads results through the API.
