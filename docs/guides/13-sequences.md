---
title: Record sequences with rules
level: Intermediate
time: 20 minutes
needs: The route scene from guide 11
summary: Write rules in plain terms, such as a person crosses the entrance and then enters the centre within 10 seconds, and find the events they record.
learn:
  - Write a sequence rule with a time window
  - Write a single-trigger rule with its own label
  - Read rule and sequence events
  - Choose between routes and sequence rules
pages: [Experiments, Data]
---

# Record sequences with rules

Lines, zones and routes count on their own. Rules add observations in plain
terms that combine several steps, for example:

> WHEN Person CROSSES Entrance THEN ENTERS Centre floor WITHIN 10 s
> RECORD AS Entered centre after the entrance

This guide adds two rules to the corridor scene from
[guide 11](11-route-choice.md). That scene has the `Entrance` gate and the
`Centre floor` zone.

## Step 1. Create the experiment

1. Open **Experiments** and click **New experiment**.
2. Set **Name** to `Corridor sequences`, pick the `Corridor` camera, keep
   **Person** and click **Create experiment**.
3. On the experiment page, **Scene version** stays on **Latest**, which is the
   route scene you saved in guide 11.

## Step 2. A sequence rule

1. In the **Rules** panel, click **Add rule**.
2. In the mode list next to the rule name, choose **Sequence (then…)**. A
   **THEN** step appears.
3. Set the rule like this:
   * **Rule name:** `Into the centre`.
   * **WHEN:** Person.
   * **CROSSES:** `Entrance`, **any direction**.
   * **THEN:** pick `Centre floor`. The step changes from **crosses** to
     **enters** by itself. Set **within** to `10` seconds.
   * **RECORD AS:** `Entered centre after the entrance`.
4. Leave **OVERALL TIMEOUT** empty. It limits the whole sequence, which only
   matters when a rule has several steps.

## Step 3. A single-trigger rule

1. Click **Add rule** again. Keep **Single trigger**.
2. Set the rule like this:
   * **Rule name:** `Entrance count`.
   * **WHEN:** Person.
   * **CROSSES:** `Entrance`, **any direction**.
   * **COUNT AS:** `Entrance passage`.
3. Click **Save** at the top of the page.

## Step 4. Run and find the events

1. Click **Start**, and open **Results** when the run has finished.
2. **Events by type** now includes **Sequence** and **Rule**.
3. Open the **Events** tab. Set **Event type** to **Sequence**. The
   **Route / label** column shows `Entered centre after the entrance`, and
   **Duration** shows the time between the two steps.
4. Set **Event type** to **Rule** to see the `Entrance passage` events.

With the recommended detector the sample has 3 entrance passages, at about
00:03, 00:16 and 00:44. Two of those people entered the centre within 10
seconds, at about 00:16 and 00:44. The person at 00:03 was already in the
centre when they crossed the entrance. The rule needs an entry after the
crossing, so it did not match.

## How rules behave

* **Every step can fail.** A sequence that does not reach its next step within
  its **within** time is dropped. Under **Rule engine** on the **Diagnostics**
  tab of the results, **sequence expired** counts those. **sequence track lost**
  counts sequences whose object left the view first, like the person at
  00:03.
* **Steps run in order.** Add more steps with **Add step**. Each step's time
  counts from the step before.
* **One rule, one label.** The label appears in counters during a run, in the
  **Route / label** column and in exports.
* **Actions.** **Count** adds to the counters, **Record event** stores the
  event, and **Send webhook** posts it to another system. See
  [guide 20](20-webhooks-and-api.md).

## Routes or sequence rules

* **Use routes** when every person who starts should end up in exactly one
  category, including Unknown, Abandoned and Lost track. Routes give shares
  and decision times.
* **Use sequence rules** for any other chain of steps, for example a visit to a
  display after the entrance, or two zones in a row. A person can match
  several rules, or none.

## Next

[Guide 14](14-compare-conditions.md) runs two versions of an experiment and
compares them side by side.
