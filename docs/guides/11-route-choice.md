---
title: Which way do people go? A route-choice study
level: Intermediate
time: 20 minutes
needs: The corridor sample video and the sample scene file
summary: Import a ready-made scene with an entrance gate, two exit gates and two routes, run it, and read route shares, outcomes and decision times.
learn:
  - Import a scene from a JSON file
  - Understand gates, routes and route outcomes
  - Read route shares and behavioural measures
  - Build a route yourself with the Route tool
pages: [Scene Builder, Experiments, Analysis]
---

# Which way do people go? A route-choice study

A route is a path through gates: a start gate, optional checkpoints and an end
gate. When several routes share the same start gate, they form one study.
Every person who passes the start is recorded as exactly one of the routes,
or as Unknown, Abandoned or Lost track.

The repository has a finished scene for the corridor clip. People pass an
entrance gate in the middle of the room and leave by an exit on the left or
on the right.

## Step 1. Import the sample scene

1. Open the Scene Builder of the `Corridor` camera. If it does not exist yet,
   add it as in [guide 02](02-count-a-line.md#step-1-add-the-corridor-video).
2. Click **Import JSON** at the bottom of the tool column and choose
   `samples\scenes\corridor_route_choice.json`.
3. The scene now has three gates, `Entrance`, `Exit Left` and `Exit Right`,
   a zone called `Centre floor`, and two routes.
4. Click **Save** in the top bar, or press `Ctrl+S`.

> [!WARNING]
> Importing replaces all shapes, routes and the calibration of the scene you
> are editing. To keep the current ones, click **Export JSON** first.

## Step 2. Look at a route

1. In the inspector, under **Routes**, click `Route A`.
2. It reads: **Starts when the object passes** `Entrance`, and
   **Completes when the object passes** `Exit Left`.
3. **Give up after (seconds)** is 30. A person who passes the entrance but
   reaches no exit within 30 seconds is recorded as Abandoned.
4. Click **Back** to return to the scene overview. `Route B` is the same with
   `Exit Right`.

## Step 3. Run it

1. Click **New experiment**, name it `Corridor route choice`, keep **Person**
   and click **Create experiment**.
2. Click **Start**. During the run, the bottom bar counts each route.
3. When the clip has finished, click **Results**.

## Step 4. Read the routes

The **Routes** panel starts with the outcomes:

| Value | Meaning | Sample result |
| --- | --- | --- |
| **Total observations** | People who passed the start gate | 3 |
| **Valid (route completed)** | People who finished one of the routes | 3 |
| **Unknown** | Reached an exit without a required checkpoint | 0 |
| **Abandoned (timeout)** | Reached no exit within the time limit | 0 |
| **Lost track** | Disappeared from view before an exit, or was still on the way when the run stopped | 0 |

The table below it gives each route's **Count**, **Share of valid**,
**Mean duration** and **Median duration**. The sample shows `Route A` 2 times
(66.7 %) and `Route B` once (33.3 %).

Under **Behavioural measurements** you find these values:

* **Mean decision time.** The time from the start gate to the next line or
  zone the person passes, usually the first checkpoint or exit. About 1 second
  in the sample.
* **Route switches.** People who passed a checkpoint of another route first.
* **Same route as the previous observation.** Whether people followed the
  person before them.

Three people are far too few for a conclusion. The sample only shows the
method. A real study needs many more observations, and the page reminds you
that correlations describe the recorded scene, not the reasons for a choice.

## Build a route yourself

1. Draw the gates first: press `G` and click the two ends of each gate.
   Draw each gate across the whole path people take.
2. Press `R` for the Route tool.
3. Click the start gate, then any checkpoints in order, then the end gate.
4. Press `Enter`, or click **Finish route**.
5. Name the route in the inspector and set **Give up after (seconds)** to a
   bit more than the slowest normal walk from start to end. Routes that share
   a start gate all use the longest of their limits.
6. Click **Save** in the top bar, or press `Ctrl+S`.

A checkpoint is drawn with `C`, as a small area. **Require every checkpoint**
is ticked for new routes, so people who skip a checkpoint are recorded as
Unknown. Untick it to count them for the route anyway, with the missed
checkpoints noted in the event.

## Next

[Guide 12](12-space-usage.md) compares how much each part of the floor is
used. [Guide 13](13-sequences.md) records custom sequences, such as passing
the entrance and then entering the centre.
