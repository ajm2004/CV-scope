# CV-Scope guides

26 hands-on guides, from a first count to a full study. Each one
says exactly what to click, and most can be practised with the two sample
videos that come with CV-Scope.

## How to use them

* **In the app.** Open **Guides** under **Help** in the sidebar. A guide can
  be read as a page, or opened with **Follow along**. It then stays beside the
  app while you move between pages, and you can tick off each step.
* **Here.** Each guide is a Markdown file in this folder, shown in the table
  below.
* **Sample videos.** If `samples/videos` is empty, download the clips once:

  ```
  .venv\Scripts\python.exe scripts\download_samples.py
  ```

Guides later in the list build on scenes and experiments from earlier ones.
The **You need** column says which.

## Beginner

One camera or clip and one kind of drawing. Results in minutes.

| # | Guide | You need | Time |
| --- | --- | --- | --- |
| 01 | [Take the tour and set up CV-Scope](01-tour-and-setup.md) | CV-Scope installed on this computer | 15 minutes |
| 02 | [Count people crossing a line](02-count-a-line.md) | The corridor sample video | 15 minutes |
| 03 | [Measure screen time with a webcam](03-webcam-screen-time.md) | A webcam, built in or USB | 10 minutes, then as long as you record |
| 04 | [Count visits to a room with a webcam](04-room-visits.md) | A webcam, built in or USB, that sees the room | 15 minutes, then as long as you record |
| 05 | [Count people in and out of a door](05-doorway-in-out.md) | The corridor sample video, or a webcam that sees a door | 15 minutes |
| 06 | [Watch how long a pet spends on the sofa](06-pet-watch.md) | A webcam that sees the sofa, and a cat or a dog | 10 minutes, then a few hours of recording |
| 07 | [Count pedestrians, bicycles and cars](07-street-by-class.md) | The street sample video | 15 minutes |
| 08 | [Leave part of the picture out with an ignore area](08-ignore-areas.md) | The street scene from guide 07 | 10 minutes |

## Intermediate

Several scene objects, rules, routes and comparisons.

| # | Guide | You need | Time |
| --- | --- | --- | --- |
| 09 | [Measure room occupancy with a crowding alert](09-room-occupancy.md) | The corridor sample video | 15 minutes |
| 10 | [Measure waiting time in a queue](10-queue-waiting-time.md) | The corridor scene from guide 09 | 15 minutes |
| 11 | [Which way do people go? A route-choice study](11-route-choice.md) | The corridor sample video and the sample scene file | 20 minutes |
| 12 | [Compare how much each area is used](12-space-usage.md) | The corridor sample video | 20 minutes |
| 13 | [Record sequences with rules](13-sequences.md) | The route scene from guide 11 | 20 minutes |
| 14 | [Compare two conditions side by side](14-compare-conditions.md) | The route scene from guide 11 | 25 minutes |
| 15 | [See where people walk with heatmaps and paths](15-heatmaps-and-paths.md) | Any finished run, for example from guide 02 | 15 minutes |

## Advanced

Calibration, accuracy, network cameras, integrations, deployment,
recognition, video recording, the Anomaly Assistant and relationships.

| # | Guide | You need | Time |
| --- | --- | --- | --- |
| 16 | [Measure walking speed with calibration](16-calibrate-speed.md) | The route scene from guide 11, and a tape measure for a real camera | 25 minutes |
| 17 | [Check the accuracy of your counts](17-check-accuracy.md) | The run from guide 02, or any run on a video file | 30 minutes |
| 18 | [Monitor a place with a network camera](18-network-cameras.md) | An IP camera with an RTSP or HTTP video stream on your network | 30 minutes, then days or weeks of monitoring |
| 19 | [Choose and benchmark the detector and tracker](19-detectors-and-trackers.md) | The corridor sample video and one or more installed detectors | 30 minutes |
| 20 | [Send events to other tools with webhooks and the API](20-webhooks-and-api.md) | The scene from guide 02 and a terminal | 30 minutes |
| 21 | [Run a real study from start to finish](21-deploy-a-study.md) | A computer for the study, and permission to record where you record | 1 to 2 hours of preparation |
| 22 | [Recognize an enrolled person and a registered vehicle](22-recognition-rules.md) | A recognition licence, a camera that sees faces at close range, and the sample clips | 45 minutes |
| 23 | [Record video of events for review](23-record-video.md) | A live camera, such as a webcam, and some free disk space | 15 minutes |
| 24 | [Watch a room for changes with the Anomaly Assistant](24-anomaly-assistant.md) | A camera on a place that should stay as it is (a webcam on a room works), and optionally a vision language model | 30 minutes |
| 25 | [Connect people, vehicles and places with relationships](25-relationships.md) | The route scene from guide 11 (corridor sample video) | 40 minutes |
| 26 | [Follow people and vehicles across cameras](26-cameras-and-locations.md) | Two or more cameras on one site with relationships turned on (guide 25); the face or plate module for identity-based moves (guide 22) | 45 minutes |

## Writing a guide

Guides are plain Markdown with a short header of front matter:

```
---
title: Count people crossing a line
level: Beginner
time: 15 minutes
needs: The corridor sample video
summary: One sentence for the guide list.
learn:
  - What the reader will be able to do
pages: [Cameras, Scene Builder, Experiments]
---
```

* **File name.** Two digits and a short name, such as `24-my-guide.md`. The
  number sets the order in the app.
* **Steps.** Every top-level numbered list becomes a list of steps that can be
  ticked off in the app.
* **Page links.** A page name in bold, such as `**Cameras**`, becomes a link to
  that page in the app.
* **Links between guides.** Use the file name, such as `[guide 02](02-count-a-line.md)`.
* **Callouts.** `> [!TIP]`, `> [!NOTE]`, `> [!WARNING]` and `> [!CAUTION]`
  render as boxes on GitHub and in the app.

The app bundles this folder when the frontend is built. Rebuild the frontend
(`npm run build` in `frontend`) after adding or editing a guide.
