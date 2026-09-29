---
title: Monitor a place with a network camera
level: Advanced
time: 30 minutes, then days or weeks of monitoring
needs: An IP camera with an RTSP or HTTP video stream on your network
summary: Connect an RTSP or HTTP camera, test the stream, keep a run alive through dropouts, and watch load and storage during long monitoring.
learn:
  - Find and test a camera's stream address
  - Set reconnection and the RTSP transport
  - Choose a processing rate for long runs
  - Watch load, reconnects and storage
pages: [Cameras, Live, Settings, Experiments]
---

# Monitor a place with a network camera

Security cameras and many other IP cameras publish a video stream on the
network, usually over RTSP. CV-Scope can read that stream directly, so a run
can watch an entrance, a platform or a car park for days.

## Step 1. Find the stream address

The stream address is in the camera's manual or its app. It usually looks
like this:

```
rtsp://user:password@192.168.1.20:554/stream1
```

* **user** and **password** are the camera's login.
* **192.168.1.20** is the camera's address on your network.
* **554** is the usual RTSP port.
* **/stream1** is the stream path. It differs between makers.

Many cameras offer a main stream and a smaller sub stream. The sub stream is
often enough for counting and needs less processing.

Cameras that publish MJPEG over the web use an address that starts with
`http://` instead. Choose **HTTP / IP camera** for those.

## Step 2. Add and test the camera

1. Open **Cameras** and click **Add camera**.
2. Set **Camera name** and **Location**, for example `Entrance` and
   `Main door, facing north`, and pick a **Project**.
3. Set **Connection type** to **RTSP stream**.
4. Paste the address into **Stream address**.
5. Click **Test connection**. It reports one of these results:

| Result | What to do |
| --- | --- |
| **Stream connected and a frame was decoded.** | The stream works. Its size and frame rate are shown. |
| **Could not connect.** | Check the address, the login, that this computer can reach the camera, and that port 554 is open. |
| **Connected, but no video frame arrived within the timeout.** | Check the stream path. The camera may also limit how many viewers it accepts, so close its app and other viewers. |
| **The address must start with rtsp://, http://, https://, rtmp:// or udp://.** | Fix the start of the address. |

6. Set **Processing frame rate** to `5`. People and cars are followed well at
   5 frames per second, and a long run then costs far less processing.
7. Click **Add camera**. The live picture appears on the right.

The stream address, including the password, is stored in CV-Scope's
database on this computer. Protect the data folder like any file with
passwords in it.

## Step 3. Keep the run alive

Networks drop out now and then. CV-Scope reconnects on its own.

1. Select the camera on **Cameras** and tick **Advanced settings**.
2. Keep **Reconnect on stream loss** ticked.
3. **Reconnect delay (s, initial / max)** starts at 1 second and doubles after
   each failed attempt, up to 30 seconds. CV-Scope keeps trying for as long as
   the run lasts. Keep these values unless the camera needs longer to
   restart.
4. Click **Save camera**.

If the picture freezes or breaks up, change the transport. Open **Settings**,
tick **Show advanced**, set **RTSP transport** in the **Cameras** panel and
click **Save changes**. It applies to runs started afterwards. TCP is the
default and the most reliable. UDP has less delay but loses frames on a busy
network.

## Step 4. Start the monitoring

1. Create an experiment for the camera and draw its scene, as in the earlier
   guides. The Scene Builder shows the live stream. Press `F` to freeze a frame
   while you draw.
2. Click **Start**. A run on a live camera continues until you click
   **Stop**.
3. Keep the CV-Scope server running. Closing its terminal window stops every
   run.

## Step 5. Watch it

**Live** shows every active run, with its picture, counters and newest events.
The row of figures at the top shows the load on this computer:

* **CPU** and **GPU** use of the whole computer.
* **Pipeline load GPU / CPU.** An estimate of what the active runs need. A
  warning appears with suggestions when the computer cannot keep up, for
  example a lower processing rate or a smaller detector.

On a run's results page, the **Diagnostics** tab counts
**Stream reconnects**. While a stream is down, the run waits and carries on
when the camera is back. Nothing is recorded during the gap, so a long outage
shows up as a quiet period in the counts.

## Step 6. Plan storage

A run stores events, not video. A busy entrance can still record many
thousands of events a day.

* **Store sampled trajectories** on **Settings**, in the **Storage** panel,
  adds up to ten positions per second per person, one per processed frame. At
  a processing rate of 5 that is about five. Turn it off if you need counts
  only.
* **Event retention (days)** is recorded in the privacy list, but this version
  does not delete old events yet. Export the data now and then from **Data**,
  as in [guide 10](10-queue-waiting-time.md#export-the-waits), or through the
  API, as in [guide 20](20-webhooks-and-api.md). Delete old runs when you no
  longer need them.

## Several cameras

Each camera runs one experiment at a time, and several cameras can run at
once. **Live** shows them together. Watch the load figures when you add
cameras. Lower the processing rate first when the computer falls behind.

## Next

[Guide 19](19-detectors-and-trackers.md) picks the detector and tracker that
suit your computer and your scene.
