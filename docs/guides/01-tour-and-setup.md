---
title: Take the tour and set up CV-Scope
level: Beginner
time: 15 minutes
needs: CV-Scope installed on this computer
summary: Start CV-Scope, run the first-run setup with a sample video, and learn where projects, cameras, experiments, runs and data live.
learn:
  - Start the server and open the app
  - Run the seven setup steps
  - Tell projects, cameras, scenes, experiments and runs apart
  - Find every page in the sidebar
pages: [Projects, Cameras, Experiments, Live, Data, Analysis, Models, Hardware, Settings]
---

# Take the tour and set up CV-Scope

CV-Scope turns a fixed camera or a recorded video into measurements. You
draw lines and zones over the picture. CV-Scope then records every time a
person, bicycle or vehicle crosses a line or spends time in a zone.

This guide starts the app, runs the first-run setup with a sample video and
shows where everything is. The other guides build on it.

## Start CV-Scope

**Installed with the Windows installer:** open **CV-Scope** from the Start
menu. A small CV-Scope window appears, and the browser opens
http://127.0.0.1:8420 when the server is ready (the first start can take a
minute). Keep that window open while you work: closing it stops CV-Scope and
any run in progress. The installer already downloaded the sample videos if
you kept **Sample videos** ticked.

**From the source folder:**

1. Open a terminal in the CV-Scope folder.
2. Start the server:

   ```
   .venv\Scripts\python.exe -m pathscope.cli serve
   ```

   On Linux and macOS the command is `.venv/bin/python -m pathscope.cli serve`.
3. Open http://127.0.0.1:8420 in the browser.
4. Keep the terminal window open while you work. Closing it stops CV-Scope
   and any run in progress.

The sample videos live in the `samples\videos` folder. If that folder is
empty, download them once:

```
.venv\Scripts\python.exe scripts\download_samples.py
```

## Run the first-run setup

A new installation opens the setup wizard by itself. You can open it again
later at http://127.0.0.1:8420/setup. A second pass only adds another project
and camera.

1. **System check.** It confirms that the API and the database are ready and
   lists the detector packages. Click **Continue**.
2. **Hardware.** It shows the processor, memory, graphics card and free disk
   space CV-Scope found. Click **Continue**.
3. **Model recommendation.** It lists four tiers for this computer: Fast,
   Balanced, High accuracy and CPU mode. The recommended one is marked. Click
   **Continue**.
4. **Detector.** The recommended detector is already selected. Click its
   **Download** button and wait until it shows **Installed**. Then click
   **Continue**.
5. **Camera or video.** Keep **Video file (upload or local file)**. Under
   **Or start with a sample clip**, click **people-detection.mp4** (the
   corridor sample). If no sample clip is listed, type its full path in
   **Or use a file already on this computer**, for example
   `C:\Users\you\CV-Scope\samples\videos\people-detection.mp4`, and click
   **Use file**. The size and frame rate of the clip appear below. Click
   **Continue**.
6. **Project.** Set **Project name** to `CV-Scope practice` and
   **Camera name** to `Corridor`. Click **Continue**.
7. **Scene Builder.** Check the summary and click
   **Create and open Scene Builder**.

The Scene Builder opens on the first frame of the corridor clip. Guide 02
starts from here.

> [!TIP]
> Setup can be skipped with **Skip setup** at the top right. Everything it
> does can also be done on the **Projects**, **Cameras** and **Models** pages.

## How the pieces fit together

* **Project.** One study or one monitored place. It groups cameras and
  experiments.
* **Camera.** A video file, a USB or built-in webcam, or a network stream.
  Each camera belongs to one project and has its own scene.
* **Scene.** What you draw over the camera picture: counting lines, gates,
  zones, checkpoints, ignore areas, routes and an optional calibration. Once a
  run has used a scene, saving it creates a new version, so old results stay
  reproducible.
* **Experiment.** What to measure: the camera, the scene version, the objects
  to track, the detector, the tracker and optional rules. Duplicate an
  experiment to change one condition.
* **Run.** One execution of an experiment. A run on a video file stops at the
  end of the file. A run on a live camera continues until you click **Stop**.
* **Events.** What a run records: line crossings, zone entries and exits with
  their duration, route outcomes and rule events. Each event carries an
  anonymous track id that is only valid within its run.

## Where everything is

The sidebar has three groups. In the app, a bold page name in a guide is a
link to that page.

| Page | What it is for |
| --- | --- |
| **Projects** | All projects. A project page has tabs for its overview, scenes, experiments, data and analysis. |
| **Live** | Every run in progress, with its picture, counters, newest events and the load on this computer. |
| **Experiments** | All experiments, with **Start** and **Stop** for each one. |
| **Data** | Every recorded event. Filter the list and export it as CSV, JSON or Parquet. |
| **Analysis** | Totals for one experiment across all its runs, and a side-by-side comparison of experiments. |
| **Cameras** | Video files, webcams and network streams, with a live view or a still frame of each. |
| **Models** | Detectors to download, benchmarks on this computer, and the trackers. |
| **Hardware** | What CV-Scope found on this computer and which detectors suit it. |
| **Settings** | Defaults, storage and retention, and a list of what this installation stores. |
| **Guides** | These guides. **Follow along** opens a guide beside the app. |

The top bar shows **API connected** while the server answers, and how many
runs are active. **API unreachable** means the server has stopped. Start it
again in the terminal.

## Next

[Guide 02](02-count-a-line.md) draws a counting line over the corridor clip
you just added and counts the people who cross it.
