---
title: Leave part of the picture out with an ignore area
level: Beginner
time: 10 minutes
needs: The street scene from guide 07
summary: Draw an ignore area so detections in part of the picture never reach any count, and compare two runs of the same clip.
learn:
  - Draw an ignore area
  - Know which detections an ignore area drops
  - Understand scene versions
  - Compare two runs of one experiment
pages: [Scene Builder, Experiments]
---

# Leave part of the picture out with an ignore area

Some things in view should never be counted: people on a television, a
reflection in a window, a poster, or the street seen through a window. An
ignore area removes every detection whose position lies inside it, before
tracking, so it reaches no line, zone, route or rule.

This guide continues with the `Street counts` experiment from
[guide 07](07-street-by-class.md). Pretend the parking bays at the top of the
picture belong to a neighbour and must stay out of the study.

## Step 1. Draw the ignore area

1. Open the Scene Builder of the `Street` camera with `Street counts`
   selected in the top bar.
2. Press `I`, or click **Ignore area** in the tool column.
3. Click the top-left corner of the picture, then the top-right corner. Then
   click on the right edge about a third of the way down, and on the left edge
   at the same height. Double-click the last corner to finish.
4. In the inspector, set **Name** to `Parking bays`.
5. Click **Save** in the top bar, or press `Ctrl+S`.

The scene version in the top bar went up by one. A run had used the previous
version, so saving created a new version instead of changing the old one. The
first run's results keep their meaning.

## Step 2. Run again and compare

1. Click **Start** and wait for the clip to finish.
2. Click **Edit experiment**. The **Runs** table lists every run of the
   experiment, and its **Scene** column shows the scene version each run used.
   Compare the newest run with the one before it.
3. Open **Results** for each run and compare **Line crossings** and
   **Object classes (tracks)**.

With the recommended detector the sample changes like this:

| Measure | Without the ignore area | With it |
| --- | --- | --- |
| East edge | 5: person 3, bicycle 2 | 1: person 1 |
| West edge | 3: car 2, person 1 | 2: car 2 |
| Tracked objects | person 4, car 2, bicycle 2 | person 1, car 2 |

The cyclists and a pedestrian moved only through the top strip, so they are
gone from every count. The cars and the other pedestrian cross the lines
below the ignore area and still count.

## Which detections are dropped

CV-Scope places each object at the bottom centre of its box. A detection is
dropped when that point lies inside an ignore area.

* **A television or a poster.** Cover the screen or the poster itself. The
  bottom of a person shown on a screen is on the screen.
* **A window to the street.** Cover the window pane.
* **A reflection on a shiny floor.** Cover the reflection. Leave the floor
  where real people walk uncovered.

While its position is inside an ignore area, an object is not tracked. When
it comes out, it is tracked again. If it was tracked just before it went in
and comes out within the lost-object time, 30 processed frames by default, it
keeps its old track number. Otherwise it starts as a new object.

> [!NOTE]
> An ignore area belongs to the camera's scene, so it applies to every
> experiment of this camera that uses the latest scene version. Untick
> **Enabled** in the inspector to switch it off without deleting it. Saving
> then creates another scene version.

## Next

[Guide 09](09-room-occupancy.md) measures how many people are in an area at
the same time.
