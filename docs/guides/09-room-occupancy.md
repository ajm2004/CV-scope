---
title: Measure room occupancy with a crowding alert
level: Intermediate
time: 15 minutes
needs: The corridor sample video
summary: Cover a floor with a zone, read how many people were inside at once and for how long, and record an event whenever the area gets crowded.
learn:
  - Draw a zone that follows the floor
  - Read occupancy, visits and occupied time
  - Flag crowding with an occupancy limit
  - Find flagged moments in the event list
pages: [Scene Builder, Experiments, Data]
---

# Measure room occupancy with a crowding alert

A zone counts the objects inside it at every moment. That gives the occupancy
of a room, a shop floor or a platform. With **Flag occupancy above**, CV-Scope
also records an event each time the area gets more crowded than you allow.

## Step 1. Draw the floor zone

1. Open the Scene Builder of the `Corridor` camera. If it does not exist yet,
   add it as in [guide 02](02-count-a-line.md#step-1-add-the-corridor-video).
2. Click **New experiment**, name it `Floor occupancy`, keep **Person** and
   click **Create experiment**.
3. Press `Z`. Click the four corners of the wooden floor:
   * where the back wall meets the floor at the far left,
   * the same at the far right,
   * the bottom-right corner of the picture,
   * the bottom-left corner of the picture.

   Double-click the last corner to finish.
4. In the inspector, set these fields:
   * **Name:** `Floor`.
   * **Measure:** keep all four boxes ticked.
   * **Ignore visits shorter than:** `1` second. A person found for a moment
     is then not counted.
   * **Flag occupancy above:** `2`. A third person on the floor creates an
     *Occupancy exceeded* event.
5. Click **Save** in the top bar, or press `Ctrl+S`.

## Step 2. Run it

1. Click **Start**. During the run, the bottom bar counts `Floor entries` and
   `Floor exits`.
2. When the clip has finished, click **Results** at the bottom of the Scene
   Builder.

## Step 3. Read the occupancy

The **Zones (occupancy and dwell)** panel shows these values for `Floor`:

| Column | Meaning | Sample result |
| --- | --- | --- |
| **Occupied time** | Time with at least one person on the floor | about 19 s |
| **Total time, all objects** | All visits added up | about 34 s |
| **Visits** | Completed visits | 7 |
| **Mean visit** | Average time a person stayed | about 4.8 s |
| **Longest visit** | The longest stay | about 5.8 s |
| **Max occupancy** | Most people on the floor at the same time | 3 |

Occupied time is shorter than total time because people overlapped. At about
00:30, three people cross the floor together.

## Step 4. Find the crowded moments

1. Open the **Events** tab of the results.
2. Set **Event type** to **Occupancy exceeded**.
3. Each row is a moment when more people than the limit were inside. Click a
   row and then **Jump to video** to see it.

The sample has one such event, at about 00:30, when the three people arrive
together. A new event is recorded only after the occupancy has dropped back to
the limit.

> [!TIP]
> Another program can watch for crowding through the API. It can read these
> events with `/api/events?run_id=12&event_type=occupancy_exceeded`, as in
> [guide 20](20-webhooks-and-api.md#step-3-use-the-api). Webhooks come from
> rules, and rules react to crossings, entries, exits and long stays, not to
> occupancy.

## For a real room

* **See the whole floor.** People outside the zone are not counted, so the
  camera must see all of it. A camera high in a corner works well.
* **Count people only once.** A zone counts each tracked person. If people are
  hidden behind each other, the occupancy is too low. Mount the camera higher.
* **Long recordings.** For a live camera, occupied time is also split by clock
  hour below the zones table.

## Next

[Guide 10](10-queue-waiting-time.md) measures how long each person waits in an
area, with a rule for long waits.
