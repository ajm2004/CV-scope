---
title: Run a real study from start to finish
level: Advanced
time: 1 to 2 hours of preparation
needs: A computer for the study, and permission to record where you record
summary: Plan the study, prepare a dedicated machine or Docker, choose the database and privacy settings, test before recording, and keep the data safe.
learn:
  - Organise projects, cameras and experiments for a study
  - Run CV-Scope on a dedicated machine or in Docker
  - Configure storage, retention and the database
  - Check, back up and hand over the data
pages: [Projects, Settings, Hardware, Data, Analysis]
---

# Run a real study from start to finish

The earlier guides each practise one technique. This one ties them together
for a study that runs for days or weeks, possibly with several cameras.

## Step 1. Plan the study

1. **Write the question down.** For example: do more people take the stairs
   when the new sign is up? The question decides what you draw and which
   conditions you compare.
2. **Get permission.** Recording people in public or at work is regulated in
   most places. Inform people, for example with a notice at the entrance, and
   follow the rules that apply to you and your institution.
3. **Organise it in CV-Scope.**
   * One **project** for the study, created on **Projects** with a short
     description.
   * One **camera** per viewpoint.
   * One **experiment** per condition, made by duplicating the first, as in
     [guide 14](14-compare-conditions.md). Put the condition in
     **Environmental condition notes** and **Tags**.

## Step 2. Prepare the machine

* **A dedicated computer.** Runs stop when the computer restarts for updates
  or is switched off, and record nothing while it sleeps. Turn off sleep in
  the power settings, and schedule system updates outside the recording time.
* **Enough power.** Check **Hardware** and benchmark on your own footage, as in
  [guide 19](19-detectors-and-trackers.md). A graphics card makes a large
  difference with several cameras.
* **Enough disk.** Events take little space. Uploaded videos and stored
  trajectories take more. The first-run system check shows the data folder.

### Or run it in Docker

The repository has Docker images for a processor and for NVIDIA graphics cards:

```
docker compose up                              # processor only
docker compose --profile gpu up cvscope-gpu  # NVIDIA card, needs the NVIDIA Container Toolkit
```

The database, uploaded videos and detectors are kept in the `cvscope-data`
volume. The Docker setup listens on this computer only. To open it to other
computers, change the service's `ports` entry in `docker-compose.yml` from
`"127.0.0.1:8420:8420"` to `"8420:8420"`, and read the caution below.

On Linux, USB cameras need device pass-through. Add
`devices: ["/dev/video0:/dev/video0"]` to the service in `docker-compose.yml`.
Network cameras need nothing special.

## Step 3. Configure storage and the database

Settings that need a restart live in a file called `.env` in the CV-Scope
folder. Copy `.env.example` to `.env` and change what you need. In Docker, set
the same variables under `environment:` in `docker-compose.yml` instead:

| Variable | Default | Use it to |
| --- | --- | --- |
| `PATHSCOPE_DATA_DIR` | `./data` | Keep the database, videos and detectors on another disk. |
| `PATHSCOPE_DATABASE_URL` | SQLite in the data folder | Use PostgreSQL for several cameras over a long time. |
| `PATHSCOPE_HOST` | `127.0.0.1` | Open the app to other computers with `0.0.0.0`. |
| `PATHSCOPE_STORE_TRAJECTORIES` | `true` | Keep counts only, with `false`. |

`PATHSCOPE_STORE_TRAJECTORIES` and `PATHSCOPE_RETENTION_DAYS` only set the
starting values of the **Settings** page. After you save **Settings** once,
change them there.

A PostgreSQL address looks like this. It needs the `postgres` extra of the
backend installed:

```
PATHSCOPE_DATABASE_URL=postgresql+psycopg://pathscope:secret@localhost:5432/pathscope
```

With Docker, first uncomment the `PATHSCOPE_DATABASE_URL` line in
`docker-compose.yml`. Then start CV-Scope with a PostgreSQL service:

```
docker compose --profile postgres up --build
```

> [!CAUTION]
> CV-Scope has no login. With `PATHSCOPE_HOST=0.0.0.0`, or a Docker port
> open to the network, everyone who can reach the computer can see the data
> and start or stop runs. Only do this on a network you control, or put a
> proxy with a login in front of it.

## Step 4. Choose what is stored

1. Open **Settings**. The panel **What this installation stores** lists every
   kind of data and whether it is kept.
2. In **Storage**, decide on **Store sampled trajectories**.
3. If an experiment records video of a live camera
   ([guide 23](23-record-video.md)), set **Video retention (days)**. Recorded
   video is deleted that many days after it was recorded. `0` keeps it until
   you delete it.
4. **Event retention (days)** and **Keep uploaded source videos** are recorded
   in the privacy list, but this version does not delete events or uploaded
   videos by itself yet. Delete runs and videos you no longer need, and plan
   exports and backups accordingly.
5. Click **Save changes**.

CV-Scope stores no faces and no identities. Track numbers are anonymous and
start again in every run. Live camera video is processed in memory and never
written to disk, unless an experiment turns on video recording.

## Step 5. Test before you record

Run this checklist a day before the real recording starts:

| Check | How |
| --- | --- |
| The picture covers what you study | Open the camera's Scene Builder and look at the live view. |
| Lines and zones sit where people walk | Watch a short test run with **Trajectories** and **Boxes** on. |
| The counts are accurate enough | Turn on video recording for a test run ([guide 23](23-record-video.md)), then judge 50 events on their clips and enter a manual count, as in [guide 17](17-check-accuracy.md). |
| The computer keeps up | Watch **Pipeline load** on **Live** during the test. |
| The stream survives a dropout | Unplug the network cable of the camera for a minute. Check that **Stream reconnects** on **Diagnostics** went up and that new events keep arriving on **Live**. |
| The data comes out | Export the test run as CSV from **Data** and open it in your analysis tool. |

Before the real runs, write the plan into the experiment's **Research notes**
and click **Save**. The experiment is locked while a run is active. Each run's
start time is shown in the **Started** column of **Runs**.

## Step 6. Keep the data safe

* **Back up the data folder.** With SQLite, stop CV-Scope and copy the whole
  data folder, which holds `pathscope.db`, videos, recordings and detectors. With
  PostgreSQL, back up the database with its own tools, such as `pg_dump`.
* **Export regularly.** The **Data** page exports CSV, JSON or Parquet. Parquet
  keeps the column types for Python, R or other analysis tools.
* **Check the results as you go.** The **Analysis** page adds up each
  experiment and compares conditions while the study runs.

## Step 7. Report

* **Describe the method.** Name the detector, tracker and settings. The
  **Diagnostics** tab of each run has the full configuration.
* **Report the accuracy.** Give the counting error, precision and recall from
  the **Evaluation** tab.
* **Stay with what was observed.** CV-Scope measures movement. Differences
  between conditions are observations, not proof of their cause.

## Where to go from here

Every guide is in the [guides list](README.md). The reference documentation is
in the repository's `docs` folder: installation, the data model, the models
and the privacy notes.
