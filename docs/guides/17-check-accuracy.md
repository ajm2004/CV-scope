---
title: Check the accuracy of your counts
level: Advanced
time: 30 minutes
needs: The run from guide 02, or any run on a video file
summary: Count a clip yourself, judge the recorded events one by one, log what was missed, and read the counting error, precision and recall of the run.
learn:
  - Enter a manual count and read the counting error
  - Judge events with verdicts
  - Log missed events
  - Read precision, recall and tracking errors
pages: [Experiments, Scene Builder]
---

# Check the accuracy of your counts

A detector can miss a person or see one who is not there, and a tracker can
mix up two people. Before you trust a long study, check a sample of it. The
**Evaluation** tab of every run compares the run with your own judgement.
Every figure there comes only from what you enter. Nothing is estimated.

This guide checks the `Middle line` run from [guide 02](02-count-a-line.md).

## Step 1. Count it yourself

1. Open the run's **Results** and click **Video review**.
2. Keep **Zones and gates** ticked, so the line is drawn over the video.
3. Set the speed to `0.5×` and click **Play**. Count every person who crosses
   `Middle line`. Step with **−1 frame** and **+1 frame** when people overlap.
4. Go back to the results with **Run analysis** and open the **Evaluation**
   tab.
5. Under **Manual counts (counting error)**, set **Line or zone** to
   `Middle line`, type your count in **Your count** and click **Save count**.

The table below shows **Manual**, **System** and **Error**. An error of −1
means the run counted one crossing fewer than you did.

## Step 2. Judge the recorded events

**Events to review** lists the run's crossings, zone visits, routes and rule
events.

1. Click the time of an event. Video review opens at that moment.
2. Watch it, then go back to the **Evaluation** tab.
3. Pick a verdict in the event's row:

| Verdict | Use it when |
| --- | --- |
| **Correct** | The event happened as recorded. |
| **Incorrect** | Nothing like it happened, for example a count caused by a shadow. |
| **Wrong route** | The person took another route than the one recorded. |
| **Wrong object class** | A bicycle was recorded as a car, for example. |
| **Tracking error** | The track jumped between two people, or one person got two tracks. |

To undo a verdict, pick the empty entry at the top of the list.

## Step 3. Log what was missed

A crossing you saw that has no event is a missed event.

1. Under **Missed events**, describe it in **Note (what happened, when)**, for
   example `Person crossed Middle line at 00:31`.
2. Click **Log missed event**. Log each miss separately.

## Step 4. Read the figures

The row at the top of the tab sums up your judgement:

| Figure | How it is worked out |
| --- | --- |
| **Events reviewed** | Events with a verdict. |
| **Precision (reviewed)** | Correct events divided by all judged events. |
| **Recall (needs missed events)** | Correct events divided by correct plus missed events. |
| **Route classification accuracy** | Route events judged correct, out of all route events you judged. |
| **Tracking errors** | Events marked **Tracking error**. |
| **Missed events logged** | Your list from step 3. |

Precision tells how many recorded events are real. Recall tells how many real
events were recorded. Recall stays empty until you mark an event **Correct**
or log a miss.

## How much to check

* **Enough events.** Judge at least 50 events, or a quarter of an hour of
  recording. Three events, as in the sample, only show the method.
* **Typical moments.** Include busy and quiet periods, and bad light if the
  study has it.
* **After every change.** Check again after you move a line, change the
  detector or change tracker settings.

## When the figures are poor

* **Many misses.** Lower **Confidence threshold** under
  **Advanced settings** on the experiment page, or use a larger detector. See
  [guide 19](19-detectors-and-trackers.md).
* **Counts that did not happen.** Raise **Minimum track age (frames)** under
  **Advanced** in the line's inspector, or cover the cause with an ignore area
  ([guide 08](08-ignore-areas.md)).
* **Tracking errors.** Try BoT-SORT with appearance matching, described in
  [guide 19](19-detectors-and-trackers.md). Or mount the camera higher, so
  people hide each other less.
* **Wrong routes.** Make the gates wider than the path, so nobody can pass
  beside them.

## Next

[Guide 18](18-network-cameras.md) connects a network camera for monitoring
over days or weeks.
