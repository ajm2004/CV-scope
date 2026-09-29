---
title: Watch how long a pet spends on the sofa
level: Beginner
time: 10 minutes, then a few hours of recording
needs: A webcam that sees the sofa, and a cat or a dog
summary: Track only cats or dogs, draw a zone over the sofa, and read how long the pet spent there and when.
learn:
  - Track animals instead of people
  - Draw a zone by hand around a piece of furniture
  - Choose a low processing rate for slow scenes
  - Read visits and time per hour
pages: [Cameras, Experiments, Scene Builder, Analysis]
---

# Watch how long a pet spends on the sofa

The detectors CV-Scope uses know cats, dogs and horses as well as people and
vehicles. This guide uses that to measure how long a cat or a dog spends on
the sofa. People in the room are then not tracked at all.

It uses the same zone technique as [guide 03](03-webcam-screen-time.md). Read
that guide first if you have not added a webcam before.

## Step 1. Point a camera at the sofa

1. Place the webcam so that it sees the whole seat of the sofa, from slightly
   above if you can. A pet curled up on a cushion is easier to recognise from
   above than from the side.
2. Add the webcam on the **Cameras** page as in
   [guide 03](03-webcam-screen-time.md#step-1-add-the-webcam). Name it
   `Sofa cam`.
3. Check the live picture on the right. Light matters: a dark room at night
   makes a dark cat hard to see.

## Step 2. Create the experiment

1. Open **Experiments** and click **New experiment**.
2. Set **Name** to `Sofa watch` and pick the camera `Sofa cam`.
3. Under **Objects to track**, untick **Person** and tick **Cat**, or
   **Dog**, or both.
4. Click **Create experiment**. The experiment page opens.

## Step 3. Draw the sofa zone

1. Click **Scene builder** at the top of the experiment page. The experiment
   is selected in the top bar, so new shapes track the same animals.
2. Press `Z`. Click the corners of the seat, following the cushions. Add a
   little room in front of the seat, because a pet's box ends where its paws
   or belly are. Double-click the last corner to finish.
3. In the inspector, set these fields:
   * **Name:** `Sofa`.
   * **Object to track:** the animals you chose.
   * **Ignore visits shorter than:** `10` seconds. A cat that only walks across
     the sofa is then not counted.
4. Click **Save** in the top bar, or press `Ctrl+S`.

## Step 4. Settings for a slow scene

A resting pet hardly moves, so a few frames per second are enough.

1. Click **Edit experiment** in the top bar.
2. Tick **Advanced settings** and set these values:
   * **Processing FPS:** `2`. This keeps the computer quiet during a long
     recording.
   * **Frames to keep searching for a lost object:** `60`. At 2 frames per
     second that is 30 seconds. A sleeping cat that the detector misses for a
     while then keeps its visit.
3. Click **Save**.

## Step 5. Record and read the result

1. Click **Start**. After a few seconds of start-up, the camera view on the
   experiment page shows the run's picture. Check once that a box appears
   around the pet. If none appears, see
   [the tips below](#if-the-pet-is-not-found).
2. Let it run for as long as you like, then click **Stop** on the experiment
   page or on the **Live** page.
3. Open the run's **Results**. The **Zones (occupancy and dwell)** panel shows
   these values:

| Value | Meaning |
| --- | --- |
| **Occupied time** | Time with the pet on the sofa. |
| **Visits** | Separate stays on the sofa. |
| **Longest visit** | The longest single stay. |
| **Occupied time per hour** | A bar for each clock hour of the run. |

For several recordings, pick the experiment on the **Analysis** page. Its
**Zones** panel adds up all runs.

## If the pet is not found

* **Too dark.** Turn on a lamp, or record during the day.
* **Curled up or under a blanket.** A detector needs to see some of the shape
  of the animal. A pet hidden under a blanket is not found.
* **Too small in the picture.** Move the camera closer. A higher
  **Requested resolution** on the camera helps only together with a higher
  **Inference resolution (px)**, for example `1280`, set in the camera's
  **Advanced settings** or the experiment's.
* **Found only now and then.** In the experiment's **Advanced settings**,
  lower **Detection confidence to start or continue a track** from 0.5 to
  about 0.3, lower **Confidence threshold** from 0.25 to 0.15, and raise
  **Frames to keep searching for a lost object**.

## Next

[Guide 07](07-street-by-class.md) counts several kinds of objects at once.
