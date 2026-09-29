---
title: Watch a room for changes with the Anomaly Assistant
level: Advanced
time: 30 minutes
needs: A camera on a place that should stay as it is (a webcam on a room works), and optionally a vision language model
summary: Let the Anomaly Assistant learn the normal picture of a room, zone or stall and report objects that appear, disappear or move, and presence where nobody should be, with before and after pictures and an optional description by a vision language model.
learn:
  - Watch the whole picture or zones with their own sensitivity and persistence
  - Tell real changes from shadows, noise and slow daylight
  - Read an anomaly with its before, event and close-up pictures
  - Let a vision language model describe or confirm events, locally or in the cloud
  - Mark false alarms and teach the assistant the new normal
pages: [Experiments, Anomalies, Live, Settings]
---

# Watch a room for changes with the Anomaly Assistant

Motion detection reports every flicker. The Anomaly Assistant works the other
way round: it learns what a place normally looks like and reports only
*meaningful* differences that last. It suits places that should stay as they
are: an empty house, a vault, a barn stall, a bed, a storeroom shelf.

It reports:

| Kind | Example |
| --- | --- |
| **Presence** | A person, animal or vehicle the detector tracks is inside a zone that should be empty |
| **Movement** | Something moves that no tracked object explains (an animal the detector does not know) |
| **Object appeared** | A bag was left on the floor |
| **Object removed** | The box on the shelf is gone |
| **Object moved** | The chair now stands somewhere else |
| **Scene changed** | The bedsheet was pulled, a cupboard was opened |
| **Camera blocked or moved** | Someone covered or turned the camera |

Dust, compression noise, small lighting changes, shadows, insects and the sun
creeping over the floor are filtered out. The detection is computer vision
and works without any AI model. A vision language model can add a
plain-language description, and can double-check events before they are
raised.

> [!CAUTION]
> The assistant keeps a few pictures of every anomaly. Tell the people who
> can appear in the picture, and set **Anomaly evidence retention (days)** in
> **Settings** to delete them after a while.

## Step 1. Draw the areas to watch

Skip this step to watch the whole picture.

1. Open **Cameras**, choose the camera and open its **Scene Builder**.
2. Draw a zone around each area that has its own rules, for example "Bed" or
   "North stall". Untick its measures if you do not need entry and exit
   counts for it.
3. Draw **ignore** regions over parts that change all the time: a TV, a
   monitor, a window with trees. The assistant never watches them.
4. Save the scene.

## Step 2. Turn the assistant on

1. Open the experiment in **Experiments** (or create one for the camera).
2. Under **Objects to track**, tick the classes whose presence matters, for
   example Person, Dog and Horse. Pixel changes are found without them;
   presence needs them.
3. In the **Anomaly Assistant** panel, tick **Watch for meaningful change**.
4. Under **Watch**, tick **The whole picture** and/or the zones.
5. Open each area and write its **Normal state, in plain words**, for example
   `The stall is empty.` or `The bed is made; nobody is here at night.` The
   sentence is shown with every event and helps a vision model.
6. Click **Save**.

## Step 3. Set how strict each area is

Each area has its own settings:

| Setting | What it does |
| --- | --- |
| **Sensitivity** | Low: only large, lasting changes (2 % of the area, 4 s). Medium (default): 0.8 % and 2.5 s. High: 0.3 % and 1.5 s. Custom: set every threshold. |
| **Only when it lasts at least (s)** | Persistence. A cat crossing a vault for one second is ignored at 5 s. |
| **Report** | Which kinds count here. A barn stall might want Presence only. |
| **Presence of** | Which tracked classes count as presence. None ticked: every tracked class. |
| **Accept a still change as normal after (s)** | A moved chair stops being an event after this long and becomes part of the normal picture. 0 keeps the event open until the change is undone. |
| **Quiet time after an event (s)** | Prevents a string of events from one disturbance. |

Settings for the whole camera, under **Settings for the whole camera**: how
long the normal picture is learned at the start (8 s), how many analyses per
second (4), how fast it follows daylight, and whether a covered camera or
switched lights are reported.

> [!TIP]
> Start with Medium. If you get false alarms, raise the persistence first,
> then lower the sensitivity. If small changes are missed, draw a tighter zone
> around them: the smallest change is a percentage of the area, so a small
> zone around a bed notices a pulled sheet that the whole picture would not.

## Step 4. Start and let it learn

1. Keep the scene as it should be and click **Start**.
2. On **Live**, the run shows **Learning the normal picture**, then
   **Watching for anomalies**. When something is found the pill turns red
   (**Anomaly now**) and counts the events.
3. **Re-learn normal** takes what the camera sees now as normal, for example
   after you rearranged the room on purpose.

## Step 5. Read an anomaly

Open **Anomalies** (or click the pill on **Live**). Each row is one event;
click it to see:

* the **normal picture** from just before, the **event** with the watched
  zone in amber and the change tinted red, and **close-ups** before and at
  the event (and at the end, once it ended);
* the computer-vision summary, for example
  `A dog entered North stall; lasted 18 s, back to normal.`;
* when it started, how long it took to confirm, how it ended, the confidence
  and the changed area;
* the tracked objects. With the licensed recognition modules they show as
  **Person A** with "recognized person" or "unknown person". Viewers with a
  recognition token see the name, everyone else does not.

**Review the run** jumps to the moment on the run's review page, where the
video clip plays if the experiment records clips. Tick **anomaly** among the
clip events in **Video recording** to record one for every anomaly.

Mark each event **Correct** or **False alarm**. For a false alarm on a
running camera, tick **take the current picture of this area as normal** so
it stops reporting the same thing.

## Step 6. Add a vision language model (optional)

A model turns the evidence into a sentence such as `An animal entered the
normally empty north barn zone and remained for 18 seconds.` It interprets
what the computer vision found. It never detects on its own.

1. Open **Anomaly Assistant** in the menu.
2. Choose a **Provider**:
   * **Local model**: runs on this computer, and pictures never leave it.
     Set it up in **Local vision models** on the same page, without leaving
     it: **Install Ollama** (Windows: it downloads the official installer,
     checks that it is signed by Ollama and installs it for your user; on
     Linux and macOS the page shows the command), then **Download** a model
     from the list and click **Use**. The list shows the download size, the
     GPU memory each model needs and whether it fits your card. A 12 GB card
     runs `qwen2.5vl:7b` next to the detector (about 5.5 GB for the model,
     about 1 s per event once loaded, 3 s with four pictures).
   * **OpenAI**, **Anthropic Claude**, **Google Gemini**, **OpenRouter**:
     paste an API key. The pictures of each event are sent to that provider.
   * **DeepSeek** reads text only, so it gets the written observations
     without pictures.
   * **Other compatible API** for any OpenAI-compatible endpoint.
3. Click **Save**, then **Test**. It sends a tiny made-up picture pair and
   should answer `confirmed`.
4. Back on the experiment, set each area's **Vision model**:

| Choice | When the alert is raised |
| --- | --- |
| **Computer vision only** | At once. No model is asked. |
| **Raise at once, the model adds a description** | At once. The description follows when the event is confirmed or when it ends (then it can say how long it lasted). |
| **Raise only when the model confirms** | After the model's answer. If it judges the change irrelevant (a shadow, a reflection) the event is kept as **Dismissed by the model** and no alert is raised. |

If the model cannot be asked (no model, an error, the hourly budget or the
queue is full), **When the model cannot answer** decides: raise the event
anyway (default, safer), or hold it for review. **Raise now** on the
Anomalies page raises a held event.

> [!WARNING]
> Larger local models need much more GPU memory and take longer per event, and
> cameras that raise events at the same time wait for each other. Start light,
> watch **Last answer took** on the Anomaly Assistant page, and keep **Calls at
> the same time** at 1 on a single GPU.

> [!NOTE]
> The model never receives a name or a plate number: people and vehicles are
> aliases like [Person A] with an anonymous status. Only confirmed events are
> sent, never the video stream, and never more than **Calls per hour at most**.

## Step 7. Send alerts

Each raised anomaly is an ordinary event of type **Anomaly**: it appears on
**Live** and in **Data**, is counted and exported, and starts video clips. To
push it elsewhere, list webhook addresses under the area's **Webhooks**. They
receive the event, then `anomaly.described` with the model's description and
`anomaly.ended` with the duration. See [guide 20](20-webhooks-and-api.md)
for receiving webhooks.

## Try it without a camera

The command line runs the assistant on any video, outside the platform:

```bash
cvscope anomaly analyse samples/videos/people-detection.mp4 --out anomaly-test
```

It prints every event and writes the pictures to `anomaly-test`. Watch part
of the picture with `--zone "Door=0.0,0.2 0.3,0.2 0.3,1.0 0.0,1.0"` (points
from 0 to 1), and try `--sensitivity high` or `--persistence 5`.
