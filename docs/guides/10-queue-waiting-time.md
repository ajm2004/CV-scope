---
title: Measure waiting time in a queue
level: Intermediate
time: 15 minutes
needs: The corridor scene from guide 09
summary: Read how long people stay in a waiting area, and add a rule that records every wait longer than a limit as a named event.
learn:
  - Read mean, median and longest visits
  - Write a Remains in zone for rule
  - Tell rule events from built-in flags
  - Export the waits for a spreadsheet
pages: [Experiments, Scene Builder, Data]
---

# Measure waiting time in a queue

In front of a counter, a ticket machine or a lift, the time each person spends
in the waiting area is their waiting time. A zone measures it for everyone. A
rule can also record each wait that runs longer than you accept.

The practice uses the `Floor` zone from [guide 09](09-room-occupancy.md) as
the waiting area. For a real queue, draw the zone over the floor where people
stand in line.

## Step 1. Create a separate experiment

A new experiment keeps the rule apart from the occupancy study of guide 09.
Both use the same scene.

1. Open **Experiments** and click **New experiment**.
2. Set **Name** to `Queue times`, pick the `Corridor` camera, keep **Person**
   and click **Create experiment**.

## Step 2. Add a rule for long waits

1. In the **Rules** panel of the experiment page, click **Add rule**.
2. In the mode list next to the rule name, choose **Remains in zone for…**.
3. Set the rule like this:
   * **Rule name:** `Long wait`.
   * **WHEN:** Person.
   * **ENTERS:** `Floor`.
   * **AND REMAINS FOR:** more than `5` seconds.
   * **CREATE EVENT:** `Long wait`.
   * **ACTIONS:** keep **Count** and **Record event** ticked.
4. Click **Save**.

## Step 3. Run it

1. Click **Start** at the top of the experiment page.
2. When the run has finished, click **Results** in its row under **Runs**.

## Step 4. Read the waiting times

In **Zones (occupancy and dwell)**, the visits of `Floor` are the waits:

| Column | Meaning | Sample result |
| --- | --- | --- |
| **Visits** | People who waited, excluding visits shorter than 1 second | 7 |
| **Mean visit** | Average wait | about 4.8 s |
| **Median visit** | Half the people waited less than this | about 5.0 s |
| **Longest visit** | The longest wait | about 5.8 s |

The median is often the better summary for a queue, because one very long
wait pulls the mean up.

The **Events by type** list counts the **Dwell** events of the rule. With the
recommended detector the sample has 3: two people at about 00:20 and one at
about 00:33. Each is recorded at the moment the person has been in the area
for 5 seconds, while they are still in view. Someone who walks out of the
picture stops adding waiting time at the moment they were last seen.

## Rules or built-in flags

The zone inspector has **Flag visits longer than**, which records a
*Dwell exceeded* event without a rule. Use it for a quick flag on one zone.
Use a rule when you want any of these:

* **Your own name** for the event, shown in counters and exports.
* **Fewer classes** than the zone counts, for example only Person in a zone
  that also counts cars.
* **A webhook** that tells another system at once. See
  [guide 20](20-webhooks-and-api.md).

## Export the waits

1. Open **Data**.
2. Set **Experiment** to `Queue times` and **Event type** to **Zone exit**.
3. Each row is one completed wait. **Duration** is its length in seconds.
4. Click **CSV** to download the rows for a spreadsheet.

## Next

[Guide 11](11-route-choice.md) follows people from an entrance to one of
several exits.
