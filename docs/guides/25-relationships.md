---
title: Connect people, vehicles and places with relationships
level: Advanced
time: 40 minutes
needs: The route scene from guide 11 (corridor sample video)
summary: Turn tracks, recognized identities, zones and routes into time-bounded relationships with a confidence and evidence, build relationship rules, correlate several observations into one event, and read it all as a graph, a timeline and a summary.
learn:
  - Turn on built-in place relationships and add rules from templates
  - Read why a relationship exists - rule version, measurements, calibration, confidence
  - Follow a run on a timeline and get a summary written from the stored facts
  - Change a rule without changing past results, and analyse a run again
  - Use a relationship in an ordinary rule, and report deviations from expectations
pages: [Relationship rules, Experiments, Relationships, Relationship timeline, Relationship search, Analysis, Relationship settings]
---

# Connect people, vehicles and places with relationships

Counting lines and zones tell you *what* happened. Relationships tell you
*how things relate*: which track followed which, who stayed beside a vehicle
and for how long, where a vehicle parked, which place someone moved to next.

Every relationship has a start and an end, a confidence, and the evidence it
rests on. It comes from a rule and a measurement, never from a guess:

```
Person track #4   FOLLOWED   Person track #3    0:16 - 0:32   Likely · 77 %
  Person track #4 passed the same 2 places as Person track #3, in the same
  order, each 12.8-13.4 s after it (Centre floor -> Exit Left), within 15.8 s.
```

This guide uses the corridor clip and the route scene of
[guide 11](11-route-choice.md). The full reference is `docs/relationships.md`.

> [!NOTE]
> Relationships describe observable behaviour only: near, followed, entered,
> parked. CV-Scope never infers who people are to each other or who owns a
> vehicle. "Associated with" means "observed together by your rule".

## Step 1. Add rules from templates

1. Open **Relationship rules** (sidebar, **Relationships › Rules**).
2. In **New rule from a template…** choose **Shared route movement**. The
   editor shows the rule as a sentence under the form: *WHEN person follows
   person through 3 checkpoints within 60 s CREATE FOLLOWED and EVENT 'Shared
   route movement'*.
3. The corridor has few checkpoints: set **THROUGH** to **2** checkpoints,
   keep **within 60 s** and **each at most 20 s behind**.
4. Click **Create rule**.
5. Add a second rule from the template **Two people remain near each other**
   and click **Create rule**.

The camera in this clip is not calibrated, so distances cannot be metres.
The templates give each distance a fallback in *frame widths* ("without
calibration: 0.06 frame widths"); a rule without one stays off on an
uncalibrated camera, and the run tells you why.

## Step 2. Turn relationships on for the experiment

1. Open **Experiments** and the route-choice experiment of guide 11 (or a new
   experiment on the corridor camera with the route scene).
2. In the **Relationships** panel tick **Connect tracks, identities and places
   into relationships during runs**.
3. Keep **Places** ticked: ENTERED, EXITED, CROSSED, USED_ROUTE, REMAINED_IN
   and MOVED_FROM / MOVED_TO come from your zones, lines and routes without
   any rule. Set **REMAINED_IN after** to **5** s.
4. Under **Rules** tick the two rules. Leave them on **latest**; pin a version
   when you compare conditions and must not pick up changes.
5. Click **Save**.

## Step 3. Run and look at the result

1. Click **Start** and wait until the run has completed (a few seconds with
   a GPU).
2. Open **Relationships**. **In the graph** counts what the run formed.
3. Choose **Person tracks** in the entity list and click a track, for
   example **Person track #4**. **Related entities** lists every place and
   track it is related to.
4. Click a row. The right-hand panel says **why this relationship exists**:
   the rule and its version, the measured values, how it was measured
   (metres, or frame widths when the camera is not calibrated), the
   confidence and what it is made of, and the observations it rests on.
5. Open the **Graph** tab: the track in the middle, the tracks and places it
   relates to around it. Click a line for its evidence, a node to open it.

With YOLO11m (the AUTO choice on this computer) the corridor clip gave 7
person tracks and 30 relationships:

| Relationship | Count |
| --- | --- |
| CROSSED (the three gates) | 10 |
| ENTERED / EXITED (Centre floor) | 7 / 7 |
| USED_ROUTE | 3 |
| FOLLOWED (Shared route movement, lags of about 13 s) | 3 |

and three correlated events **Shared route movement**. Nobody stayed within
0.06 frame widths of someone else for the template's 10 s, so *People near
each other* formed nothing in this clip. Your numbers can differ with another detector.

> [!TIP]
> Each state is a confidence band: **Confirmed by rule** (85 % or more),
> **Likely** (65 %), **Possible** (40 %), **Insufficient evidence**. Filter
> with **At least**. Without calibration relationships rarely reach
> *confirmed*: the measurement is less certain, and the state says so.
> Calibrate the camera ([guide 16](16-calibrate-speed.md)) to measure in metres.

## Step 4. Follow the run on a timeline

1. Open **Relationship timeline**, choose the experiment and the run.
2. The list shows observations, relationships and correlated events in
   order. For a video file the times are positions in the video (0:16);
   for a live camera they are clock times.
3. Click **Summarize**. The summary is written from the stored facts only,
   one line per track and time span, for example *0:16-0:32 Person track #4
   followed Person track #3 for 16 s*.
4. Click **▶** on any line to open **Video review** a moment before it.

## Step 5. Change a rule without changing the past

1. Open **Relationship rules**, click **Shared route movement**.
2. Under **ACTIONS** tick **Record a run event** (the **CREATE EVENT** field
   already says `Shared route movement`).
3. Under **What changed** type `record run events` and click **Save as
   version 2**. **Versions** now lists v2 and the untouched v1.
4. Start the experiment again. The run uses version 2 (the experiment is on
   *latest*): its events now include three `correlated` events, one per
   shared route movement.
5. To apply the new version to the first run, open **Analysis**, the first
   run, the **Relationships** tab, and click **Analyse again**. The stored
   trajectories are replayed with the current rule versions; the new analysis
   becomes **current** and the first one is **kept**. On this clip the replay
   gave exactly the same 30 relationships as the live run.

## Step 6. Use a relationship in an ordinary rule

1. Open the experiment and add a rule in the **Rules** panel: **WHEN**
   person, **CROSSES** Exit Left.
2. Click **+ has relationship…** and choose **FOLLOWED**, in either
   direction, at least **possible**, ended at most **60** s ago, **WITH**
   person.
3. Under **COUNT AS** type `Followed to the left exit`, save, and start a run.

The rule fired twice on this clip, for the two tracks that followed someone
to the left exit. The relationship forms at the same crossing that triggers
the rule; CV-Scope waits a few seconds for it, as it waits for recognition.

## Step 7. Report what is outside an expectation

1. In the experiment's **Relationships** panel click **Add expectation**.
2. Name it `People stay out of the centre`, **WHO** person, **WHEN IT**
   enters, and tick **Centre floor** under **NOT EXPECTED**.
3. Keep **Record deviations as run events** ticked, save and run.

Each person who entered the centre with at least *likely* confidence gives a
**Pattern deviation** (6 of the 7 entries on this clip), in the timeline, the
explorer and the run's events: *Person track #1 entered Centre floor, which
the expectation 'People stay out of the centre' lists as not expected.* With
recognized people or registered vehicles, CV-Scope can also report a place
or a partner an identity has rarely or never been seen with before.

## Step 8. Search, identities and privacy

1. Open **Relationship search**, choose **Show correlated events and pattern
   deviations** and click **Search**. Other questions: everything involving
   an entity, what is associated with it, who was near it, who entered a zone
   after it arrived, route use.
2. With the licensed recognition modules, a track that is recognized gets an
   **IDENTIFIED_AS** link to the recognized person; the track is kept. The
   name is shown only to viewers signed in with a recognition token whose
   role may see identities. Everyone else sees *Recognized person*.
3. Open **Relationship settings** to set who may read, export, change rules
   and see identities, how long relationship data and identity links are
   kept, and to read the audit trail.

> [!CAUTION]
> Relationships can reveal routines and associations that single detections
> do not. Tell the people you observe, keep **Delete identity links after**
> short, and restrict the identity role to the people who need it.
