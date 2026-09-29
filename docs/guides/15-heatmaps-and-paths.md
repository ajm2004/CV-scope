---
title: See where people walk with heatmaps and paths
level: Intermediate
time: 15 minutes
needs: Any finished run, for example from guide 02
summary: Read the trajectory heatmap of a run, replay the video with paths and event markers, and follow a single anonymous track.
learn:
  - Turn trajectory storage on or off
  - Read the heatmap and track statistics
  - Replay a run with overlays in video review
  - Follow one track and jump to its events
pages: [Settings, Experiments, Scene Builder]
---

# See where people walk with heatmaps and paths

Counts say how many. Paths say where. During a run CV-Scope stores up to ten
positions per second for each tracked object, one per processed frame. They are
anonymous points on the floor, never images. They feed a heatmap and the paths
in video review.

## Step 1. Check that paths are stored

1. Open **Settings**.
2. In the **Storage** panel, **Store sampled trajectories** should be ticked.
   It is on by default.
3. If you change it, click **Save changes**. The setting applies to runs that
   start afterwards.

With trajectory storage off, only events and track summaries are kept. The
heatmap and the paths in video review then stay empty.

## Step 2. Read the heatmap

1. Open a finished run. For example, open the experiment
   `Count the middle line` from [guide 02](02-count-a-line.md) and click
   **Results** in the **Runs** table.
2. Open the **Tracks and heatmap** tab.
3. **Trajectory heatmap (sampled ground positions)** divides the picture into
   a grid and shades each cell by how many positions were recorded there. The
   camera image is not shown under it. The number of samples is shown below
   it.

In the corridor sample, 207 positions were stored. The busiest cells lie
along the foot of the back wall, where people crossed the room, and in the
lower middle, where people walked close to the camera.

**Track statistics** beside it tells how well tracking went:

| Value | Meaning |
| --- | --- |
| **Tracks** | Separate objects the tracker followed. |
| **Mean lifetime** / **Median lifetime** | How long a track lasted. Very short tracks point to flickering detections. |
| **Lost and reacquired** | Objects lost for a moment and found again with the same id. |
| **Still active at end** | Objects still in view when the run ended. |
| **Mean detection confidence** | How sure the detector was, from 0 to 1. |

## Step 3. Replay with paths

1. Click **Video review** at the top of the results page.
2. Click **Play**. The video plays with the scene drawn over it. Use
   **−1 frame** and **+1 frame** to step, and the speed list to slow down.
3. Tick or untick the overlays: **Zones and gates**, **Trajectories**,
   **Track ids** and **Event markers**.
4. The timeline under the video has a mark for each event. Click a mark, or a
   row in the **Events** list on the right, to jump to that moment.

Video review needs the source video, so it works for runs on video files.
CV-Scope does not record video from live cameras. For those runs the page
shows the event list only.

## Step 4. Follow one track

1. In the **Events** list, click a row of the person you want to follow. The
   video jumps to that moment.
2. Click the track number in that row, such as `#3`. Only that track's trail
   is drawn now. Play the video to watch that one person.
3. Click **Show all tracks** to draw every path again.

Track numbers are anonymous. They start again at 1 in every run and cannot
link a person across runs or cameras.

## Paths during a run

The Scene Builder draws a short trail behind each tracked object while a run is
live. In the inspector, the **Overlays** section switches **Trajectories**,
**Boxes**, **Track ids** and other drawings on and off. It changes only what you
see, not what is recorded.

## Next

[Guide 16](16-calibrate-speed.md) turns positions into metres, so paths get a
length and people a walking speed.
