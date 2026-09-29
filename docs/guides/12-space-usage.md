---
title: Compare how much each area is used
level: Intermediate
time: 20 minutes
needs: The corridor sample video
summary: Split a floor into several zones and compare their occupied time, then apply the same idea to parking bays with an overstay flag.
learn:
  - Draw several zones side by side
  - Compare occupied time and visits between zones
  - Set up one zone per parking bay
  - Flag overstays with a visit limit
pages: [Scene Builder, Experiments, Analysis]
---

# Compare how much each area is used

Which aisle of a shop, which corner of a room or which bay of a car park is
used most? Give each area its own zone and compare their occupied time. This
guide splits the corridor floor into three zones.

## Step 1. Draw three zones

1. Open the Scene Builder of the `Corridor` camera. If you imported the route
   scene in guide 11, you can keep it. The new zones are added to it.
2. Click **New experiment**, name it `Floor use`, keep **Person** and click
   **Create experiment**.
3. Press `Z` and draw the left third of the floor. Click where the back wall
   meets the floor at the far left, then a third of the way across along the
   foot of the wall. Then click the bottom edge straight below, and the
   bottom-left corner of the picture. Double-click to finish.
4. In the inspector, set **Name** to `Left` and
   **Ignore visits shorter than** to `1`.
5. Draw the middle third the same way and name it `Centre`. Draw the right
   third and name it `Right`. Give both the same 1-second minimum.
6. Click **Save** in the top bar, or press `Ctrl+S`.

Neighbouring zones may touch. Corners close to the edge of the picture snap
onto it.

## Step 2. Run and compare

1. Click **Start** and wait for the clip to finish.
2. Click **Results**. The **Zones (occupancy and dwell)** panel lists the
   three zones, and also `Centre floor` if you kept the route scene.
3. Compare **Occupied time** first. It tells how long each area had anyone in
   it. **Visits** tells how often people came.

With the recommended detector the sample gives these results:

| Zone | Occupied time | Visits | Longest visit |
| --- | --- | --- | --- |
| Left | about 10 s | 4 | about 5.3 s |
| Centre | about 10 s | 6 | about 3.1 s |
| Right | about 6 s | 3 | about 3.3 s |

People used the left and centre of the floor about equally and the right side
less. They stayed longest on the left, near the door.

## Step 3. Look over several runs

1. Open **Analysis** and pick `Floor use` in the **Experiment** list.
2. The **Zones** panel adds up all runs of the experiment.
3. For live cameras, the occupied time of each zone is also split by clock
   hour, which shows the busy hours of each area.

## Parking bays

The same method measures the use of parking bays, with a camera that looks
down on the car park.

1. Create the experiment. Under **Objects to track**, untick **Person** and
   tick **Car**. Tick **Truck** too if vans park there.
2. Draw one zone per bay. Follow the painted lines, and include the part of
   the bay where the bottom of a parked car is seen from the camera.
3. Name the zones after the bay numbers, such as `Bay 12`.
4. On each zone set **Ignore visits shorter than** to `120` seconds. A car
   that only drives through the bay is then not counted.
5. To flag overstays, set **Flag visits longer than** to the limit, for
   example `7200` for two hours. Each overstay then creates a
   *Dwell exceeded* event, counted as **Long visits flagged** in the zones
   table.
6. On the experiment page, under **Advanced settings**, set
   **Processing FPS** to `1`. Parked cars do not move, so one frame per
   second is plenty.
7. A parked car can be hidden for a while by a passing van. Raise
   **Frames to keep searching for a lost object** so the visit continues, for
   example to `120`, which is 2 minutes at 1 frame per second.
8. Click **Save** at the top of the experiment page.

## Next

[Guide 13](13-sequences.md) records sequences, such as passing the entrance
and then entering the centre of the room.
