---
title: Send events to other tools with webhooks and the API
level: Advanced
time: 30 minutes
needs: The scene from guide 02 and a terminal
summary: Post events to another system the moment they happen, receive them with a short script, and read, export and control runs through the REST API.
learn:
  - Add a webhook action to a rule
  - Receive webhooks with a small local script
  - Switch webhooks off for the whole installation
  - Export data and start runs through the API
pages: [Experiments, Settings, Data]
---

# Send events to other tools with webhooks and the API

CV-Scope can tell other systems what happens as it happens. A rule with a
webhook action posts each of its events to a web address you choose. Home
automation and workflow tools accept such webhooks. Chat tools usually need a
workflow tool in between, because they expect their own message format. For
everything else there is the REST API that the CV-Scope interface itself uses.

## Step 1. Start a small receiver

This script listens on this computer and prints each event it receives.

1. Save the following as `hook_receiver.py` in the CV-Scope folder:

   ```python
   import json
   from http.server import BaseHTTPRequestHandler, HTTPServer

   class Hook(BaseHTTPRequestHandler):
       def do_POST(self):
           body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
           e = body["event"]
           print(e["event_type"], e.get("label"), e.get("object_name"), e.get("direction"), "track", e["track_id"])
           self.send_response(200)
           self.end_headers()

       def log_message(self, *args):
           pass  # keep the output to one line per event

   HTTPServer(("127.0.0.1", 8765), Hook).serve_forever()
   ```

2. Open a second terminal in the CV-Scope folder and start it:

   ```
   .venv\Scripts\python.exe hook_receiver.py
   ```

3. Leave it running. It prints nothing until an event arrives.

## Step 2. Add a webhook to a rule

1. Open **Experiments** and create an experiment `Webhook test` for the
   `Corridor` camera, with **Person**. Its scene needs `Middle line` from
   [guide 02](02-count-a-line.md).
2. In **Rules**, click **Add rule** and keep **Single trigger**:
   * **Rule name:** `Notify`.
   * **WHEN:** Person.
   * **CROSSES:** `Middle line`, **any direction**.
   * **COUNT AS:** `Middle crossing`.
3. Under **ACTIONS**, tick **Send webhook** and type
   `http://127.0.0.1:8765/hook` in the address box that appears.
4. Click **Save**, then **Start**.

The receiver prints one line per crossing, for example:

```
rule Middle crossing Middle line reverse track 1
```

With the recommended detector the sample sends 3 webhooks, one per crossing.

## What a webhook contains

Each webhook is an HTTP POST with a JSON body:

```json
{
  "run_id": 12,
  "event": {
    "event_type": "rule",
    "label": "Middle crossing",
    "rule_name": "Notify",
    "object_name": "Middle line",
    "direction": "reverse",
    "track_id": 1,
    "object_class": "person",
    "media_time_s": 3.167,
    "wall_time": 1790061755.36
  }
}
```

The event has more fields, such as `duration_s`, `avg_speed`, `confidence` and
`context`. `wall_time` is when CV-Scope processed the event, in seconds since
1970. For a live camera that is when it happened. For a video file it is the
processing time, and `media_time_s` is the position in the video. A webhook
carries the event record only, never an image.

CV-Scope sends each webhook once. When the receiver is down, the event is not
sent again, but it is still stored and can be read later through the API.

## Switch webhooks off

**Settings** has a switch for every webhook of every rule. Tick
**Show advanced**, then untick **Allow webhook actions** in the **Export**
panel and click **Save changes**. It applies to runs started after the
change.

## Step 3. Use the API

The interface talks to CV-Scope through a REST API, and so can your own
scripts. The interactive documentation lists every endpoint and lets you try
them in the browser:

```
http://127.0.0.1:8420/api/docs
```

In Windows PowerShell, type `curl.exe` rather than `curl`, which is a
different command there. Replace the numbers in the examples with your own
experiment and run numbers. They are shown in the page addresses of the app,
for example `/experiments/3`.

**Export all zone visits of an experiment as CSV:**

```
curl.exe -o visits.csv "http://127.0.0.1:8420/api/events/export?format=csv&experiment_id=3&event_type=zone_exit"
```

**List the newest events of a run as JSON:**

```
curl.exe "http://127.0.0.1:8420/api/events?run_id=12&page_size=20"
```

**Start an experiment and stop its run:**

```
curl.exe -X POST http://127.0.0.1:8420/api/experiments/3/start
curl.exe -X POST http://127.0.0.1:8420/api/runs/13/stop
```

The start call answers with the new run, including its `id`.

**Read a run summary in Python:**

```python
import json
import urllib.request

summary = json.load(urllib.request.urlopen("http://127.0.0.1:8420/api/analytics/runs/12/summary"))
for z in summary["zones"]:
    print(z["object_name"], z["occupied_s"], "seconds occupied,", z["exits"], "visits")
```

> [!WARNING]
> CV-Scope has no login. Anyone who can reach its address can read the data
> and start or stop runs. Keep it on `127.0.0.1`, the default, or on a network
> you trust. [Guide 21](21-deploy-a-study.md) covers this.

## Next

[Guide 21](21-deploy-a-study.md) prepares a real study: a dedicated machine,
the database, privacy settings and backups.
