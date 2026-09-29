---
title: Compare two conditions side by side
level: Intermediate
time: 25 minutes
needs: The route scene from guide 11
summary: Duplicate an experiment, change exactly one condition, run both, and compare them on the Analysis page. The practice compares two detectors.
learn:
  - Duplicate an experiment and change one condition
  - Record conditions in notes and tags
  - Reuse a scene on a second camera
  - Compare experiments on the Analysis page
pages: [Experiments, Analysis, Models, Scene Builder]
---

# Compare two conditions side by side

Most studies compare conditions: with and without signage, morning and
evening, before and after a change to the layout. In CV-Scope each condition
is its own experiment. Duplicate the first one and change only the condition,
so everything else stays identical.

The practice compares two detectors on the same clip. That is also how you
check whether a result depends on the detector.

## Step 1. The first condition

1. Open **Experiments** and open `Corridor route choice` from
   [guide 11](11-route-choice.md).
2. In **Environmental condition notes**, type `Recommended detector`. The
   notes are stored with the experiment and shown in the comparison.
3. In **Tags (comma separated)**, type `detector-test`.
4. Click **Save**.

## Step 2. The second condition

1. Click **Duplicate** at the top of the page. The copy opens, named
   `Corridor route choice (copy)`.
2. Change **Name** to `Corridor route choice, YOLO11n`.
3. Change **Environmental condition notes** to `Detector YOLO11n`.
4. In **Detector**, choose **YOLO11n**. If it is not in the list, click
   **Save** first, install it on the **Models** page, then come back to the
   copy and choose it.
5. Click **Save**.

Only the detector differs now. Camera, scene version, objects to track and
rules are the same.

## Step 3. Run both

1. Click **Start** on the copy and wait until its run has completed.
2. Open the first experiment. The comparison adds up all runs of an
   experiment, so give it exactly one run on the same scene version. If it has
   a run from guide 11 and you have not changed the scene since, keep that run
   and do not start another. If you changed the scene, for example with the
   zones of guide 12, delete the old run in the **Runs** table, then click
   **Start**.

## Step 4. Compare

1. Open **Analysis**.
2. In **Compare experiments**, tick both experiments.
3. The table shows one row per experiment:

| Column | Recommended detector | YOLO11n |
| --- | --- | --- |
| **Condition** | Recommended detector | Detector YOLO11n |
| **Events** | 27 | 29 |
| **Observations** | 3 | 3 |
| **Valid** | 3 | 3 |
| **Routes (share of valid)** | Route A 2 (66.7 %), Route B 1 (33.3 %) | the same |
| **Mean decision time** | about 1.0 s | about 0.9 s |

These are the sample results. The route result does not change with the
detector. The small detector recorded two more events and a slightly
shorter decision time. Small differences like these are normal, and they are
why one condition at a time is the rule.

To see all measurements of one experiment, pick it in the **Experiment** list
at the top of the **Analysis** page.

## A real before-and-after study

**One live camera, two periods.** Run the first experiment during the first
period, for example a week without signage. Then duplicate it, give the copy
its own **Name**, change the condition notes, click **Save**, and run the copy
during the second period. Each run belongs to its own experiment, so the
periods stay apart.

**Two recordings.** A scene belongs to a camera, and each recording is its own
camera. Copy the scene from one to the other:

1. In the Scene Builder of the first camera, click **Export JSON**.
2. Open the Scene Builder of the second camera, click **Import JSON** and
   choose the exported file. Save.
3. Duplicate the experiment. In the copy, change **Name**, pick the second
   camera and click **Save**.

The two recordings must show the same view. Otherwise the lines and zones do
not sit on the same places.

> [!IMPORTANT]
> CV-Scope reports what was observed. A difference between two conditions
> can have other causes, such as the weather, the day of the week or a crowd.
> Record such circumstances in the condition notes.

## Next

[Guide 15](15-heatmaps-and-paths.md) shows where people walked, as a heatmap
and as individual paths over the video.
