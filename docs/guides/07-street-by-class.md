---
title: Count pedestrians, bicycles and cars
level: Beginner
time: 15 minutes
needs: The street sample video
summary: Count several kinds of objects with the same lines, read the counts per class, and see why a cyclist counts as a person and a bicycle.
learn:
  - Track several object classes at once
  - Let a line count every tracked class
  - Read counts by class
  - Count one class only with a dedicated line
pages: [Cameras, Scene Builder, Experiments, Analysis]
---

# Count pedestrians, bicycles and cars

The street clip looks down on a parking lot. A pedestrian walks through, two
cars drive through and two cyclists ride past. This guide counts all of them
with two lines, one near each side of the picture, and splits the counts by
kind of object.

## Step 1. Add the street clip

1. Open **Cameras** and click **Add camera**.
2. Set **Camera name** to `Street` and pick a **Project**.
3. Set **Connection type** to **Video file**.
4. In **Or use a file already on this computer**, type the full path of
   `samples\videos\person-bicycle-car-detection.mp4` and click **Use file**.
5. Click **Add camera**, then **Open scene builder**.

## Step 2. Create the experiment first

New shapes take their object classes from the experiment selected in the
Scene Builder, so create the experiment before you draw.

1. Click **New experiment** in the top bar.
2. Set **Name** to `Street counts`.
3. Under **Objects to track**, **Person** is already ticked. Also tick
   **Bicycle** and **Car**.
4. Click **Create experiment**. It is now selected in the top bar.

## Step 3. Draw two lines

1. Press `L`. Click at the top edge of the picture, about a tenth of the way
   in from the left. Then click at the bottom edge, straight below.
2. In the inspector, set **Name** to `West edge`. Under **Object to track**,
   **Person**, **Bicycle** and **Car** are ticked.
3. The Line tool is still active. Click at the top edge about a tenth of the
   way in from the right edge, then at the bottom edge straight below. Name the
   new line `East edge`.
4. Click **Save** in the top bar, or press `Ctrl+S`.

> [!TIP]
> A line with no class ticked counts every class the experiment tracks. That
> is handy when you add classes to the experiment later.

## Step 4. Run and read the counts

1. Click **Start** and wait for the clip to finish.
2. Click **Results** at the bottom of the Scene Builder.
3. In **Line crossings**, the **By class** column splits each line's total.
4. The **Object classes (tracks)** panel shows how many different objects of
   each class were tracked.

With the recommended detector the sample gives these counts:

| Line | Total | By class |
| --- | --- | --- |
| East edge | 5 | person 3, bicycle 2 |
| West edge | 3 | car 2, person 1 |

The two cars leave on the left. On the right, one pedestrian leaves and two
cyclists ride out.

## Why a cyclist counts twice

The detector sees the rider as a person and the bicycle as a bicycle. Both are
tracked, so one cyclist adds one person and one bicycle. That explains the 3
persons on the East edge: one pedestrian and two riders.

* **To count cyclists,** count bicycles.
* **To count pedestrians only,** subtract the bicycles from the persons, or
  draw a line with only **Person** ticked where cyclists do not pass.

## Count one class with its own line

A line counts only the classes ticked under **Object to track**. To report
cars and bicycles as separate numbers, draw one line per class.

1. Go back to the Scene Builder. On the results page click **Experiment**,
   then **Scene builder**.
2. Click `East edge` in the **Objects** list of the inspector, and press
   `Ctrl+D`. The copy, `East edge copy`, appears slightly to the right of and
   below the original, and is selected.
3. Name the copy `East bicycles`. Under **Object to track**, untick **Person**
   and **Car**, so only **Bicycle** stays ticked.
4. Click **Save**, then **Start**. `East bicycles` counts 2.

## Next

[Guide 08](08-ignore-areas.md) keeps part of the picture out of every count,
using this same scene.
