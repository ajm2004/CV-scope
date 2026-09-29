---
title: Measure walking speed with calibration
level: Advanced
time: 25 minutes
needs: The route scene from guide 11, and a tape measure for a real camera
summary: Tell CV-Scope how big the floor really is, with one known distance or four measured points, and read speeds in metres per second.
learn:
  - Calibrate with one known distance
  - Calibrate a perspective view with four reference points
  - Read speeds per track, route and event
  - Know the limits of each method
pages: [Scene Builder, Experiments, Data]
---

# Measure walking speed with calibration

Without calibration, CV-Scope measures distance in fractions of the picture,
and speed in fractions of the picture per second. A calibration maps the
picture to the real floor, so distances come out in metres and speeds in
metres per second.

There are two methods:

| Method | What you enter | Good for |
| --- | --- | --- |
| **Known distance** | One drawn line and its real length | Cameras looking almost straight down |
| **Reference points** | Four or more points on the floor, with their real positions | Any camera looking at a flat floor at an angle |

## Practice: one known distance

The corridor clip comes without measurements. For practice, pretend that the
`Entrance` gate from [guide 11](11-route-choice.md) is 4 metres long.

1. Open the Scene Builder of the `Corridor` camera with the route scene.
2. Press `V` for the Select tool and click an empty spot of the picture, so
   that no shape is selected. The inspector shows the scene overview.
3. Scroll to **Calibration (optional)**. Keep **Unit** as `m`.
4. In **Known distance**, choose `Entrance`. Replace the 5 in the box next to
   it with `4`.
5. The note above changes to **Scale-only calibration**. Click **Save** in the
   top bar, or press `Ctrl+S`.
6. Click **New experiment**, name it `Walking speed`, keep **Person** and
   click **Create experiment**. Then click **Start**.
7. Open **Results** when the run has finished.

With the 4-metre assumption the sample gives these speeds:

| Where | Value |
| --- | --- |
| **Mean track speed** at the top of the summary | about 1.7 m/s |
| `Route A`, **Mean speed (m/s)** in the routes table | about 2.4 |
| `Route B`, **Mean speed (m/s)** | about 2.2 |

On the **Events** tab, the **Speed** column shows the mean speed of each route
and zone visit.

The corridor camera looks at the floor at an angle, so one scale for the
whole picture is only a rough approximation here. The next method is the
right one for such a view.

## A real camera: four reference points

You need four or more points on the floor that you can see in the picture and
measure in the room. Corners of floor tiles, painted lines, or taped crosses
work well.

1. **Measure the points.** Pick one corner of the area as the origin. Measure
   each point's distance from it along two directions at right angles, in
   metres. Note them as X and Y.
2. **Place the points.** In the Scene Builder, press `K` for the Calibration
   tool. Click each point on the floor in the picture. Each click adds a row
   to the **Reference points** table in the inspector.
3. **Enter the positions.** Type each point's **Ground X** and **Ground Y**
   into its row.
4. **Check the note.** With four or more points it reads
   **Perspective calibration active**. Save the scene.

Tips for good results:

* **Spread the points out.** Place them near the corners of the area people
  walk through, not in a small cluster.
* **Stay on one plane.** All points must lie on the same flat floor. A step or
  a ramp breaks the mapping.
* **Measure carefully.** An error of 10 cm over 5 metres is a 2 % error in
  every speed.

## What the speeds mean

* **Ground point.** Speeds follow the bottom centre of each box, about where
  the feet are. A person partly hidden behind a counter has a box that ends
  higher up, so their position and speed are less reliable.
* **Routes.** A route's mean speed is the path length from start to end,
  divided by the time taken.
* **Checking.** Draw a zone over a measured stretch of floor and walk through
  it at a steady pace while someone times you. The **Speed** of your zone
  visit on the **Events** tab should be close to the distance divided by the
  time.

## Next

[Guide 17](17-check-accuracy.md) checks how accurate the counts of a run are.
