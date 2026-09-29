"""Recording settings on experiments, the recordings API, deletion, retention and the privacy list."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

from pathscope.config import get_settings
from pathscope.db.models import Recording, Run
from pathscope.db.session import get_session_factory
from pathscope.storage.recordings import add_recording, delete_files, sweep


def _setup(client) -> tuple[int, int]:
    pid = client.post("/api/projects", json={"name": "Recording study"}).json()["id"]
    cam = client.post("/api/cameras", json={"project_id": pid, "name": "Room webcam", "source_type": "usb", "source_uri": "0"}).json()
    return pid, cam["id"]


def _run(experiment_id: int, camera_id: int) -> int:
    session = get_session_factory()()
    try:
        run = Run(experiment_id=experiment_id, camera_id=camera_id, status="completed", snapshot={}, stats={})
        session.add(run)
        session.commit()
        return run.id
    finally:
        session.close()


def _video(run_id: int, name: str, seconds: float = 2.0) -> Path:
    folder = get_settings().recordings_dir / f"run-{run_id}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.avi"
    w = cv2.VideoWriter(str(path), cv2.CAP_FFMPEG, cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for i in range(int(seconds * 10)):
        w.write(np.full((48, 64, 3), i * 10 % 255, np.uint8))
    w.release()
    return path


def _add(run_id: int, experiment_id: int, camera_id: int, path: Path, ended_ago_s: float = 0.0) -> int:
    end = time.time() - ended_ago_s
    return add_recording(run_id, experiment_id, camera_id, {
        "kind": "event", "path": str(path), "mime": "video/x-msvideo", "codec": "MJPG", "width": 64, "height": 48, "fps": 10.0,
        "frames": 20, "media_start_s": 5.0, "media_end_s": 7.0, "wall_start": end - 2.0, "wall_end": end,
        "size_bytes": path.stat().st_size, "overlay": True, "triggers": [{"type": "zone_entry", "label": "Room entry", "track_id": 3, "media_time_s": 6.0}],
        "trigger_count": 1,
    })


def test_experiments_keep_their_recording_settings(client):
    pid, cid = _setup(client)
    body = {"project_id": pid, "camera_id": cid, "name": "Room visits", "recording": {"mode": "events", "pre_s": 3, "post_s": 8, "event_types": ["zone_entry", "zone_exit"]}}
    e = client.post("/api/experiments", json=body).json()
    assert e["recording"]["mode"] == "events" and e["recording"]["pre_s"] == 3 and e["recording"]["event_types"] == ["zone_entry", "zone_exit"]
    upd = client.put(f"/api/experiments/{e['id']}", json={"recording": {"mode": "continuous", "overlay": False}}).json()
    assert upd["recording"]["mode"] == "continuous" and upd["recording"]["overlay"] is False
    assert client.post(f"/api/experiments/{e['id']}/duplicate").json()["recording"]["mode"] == "continuous"
    assert client.put(f"/api/experiments/{e['id']}", json={"recording": {"mode": "sometimes"}}).status_code == 422
    plain = client.post("/api/experiments", json={"project_id": pid, "camera_id": cid, "name": "No video"}).json()
    assert plain["recording"]["mode"] == "off"


def test_recordings_are_listed_played_with_ranges_and_deleted(client):
    pid, cid = _setup(client)
    eid = client.post("/api/experiments", json={"project_id": pid, "camera_id": cid, "name": "Clips", "recording": {"mode": "events"}}).json()["id"]
    run_id = _run(eid, cid)
    path = _video(run_id, "event-1")
    rid = _add(run_id, eid, cid, path)
    rows = client.get(f"/api/runs/{run_id}/recordings").json()
    assert len(rows) == 1 and rows[0]["id"] == rid and rows[0]["duration_s"] == 2.0 and rows[0]["playable"] is False
    assert rows[0]["triggers"][0]["label"] == "Room entry" and rows[0]["url"] == f"/api/recordings/{rid}/file"
    size = path.stat().st_size
    full = client.get(f"/api/recordings/{rid}/file")
    assert full.status_code == 200 and len(full.content) == size
    part = client.get(f"/api/recordings/{rid}/file", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100 and part.headers["content-range"] == f"bytes 0-99/{size}"
    assert "attachment" in client.get(f"/api/recordings/{rid}/file?download=true").headers["content-disposition"]
    assert [r["id"] for r in client.get(f"/api/recordings?experiment_id={eid}").json()] == [rid]

    privacy = {row["item"]: row for row in client.get("/api/system/privacy").json()["stored"]}
    assert privacy["Live camera video"]["stored"] is True and "Clips" in privacy["Live camera video"]["detail"]

    assert client.delete(f"/api/recordings/{rid}").status_code == 204
    assert not path.exists() and client.get(f"/api/runs/{run_id}/recordings").json() == []

    # deleting the run takes its video with it
    path2 = _video(run_id, "event-2")
    _add(run_id, eid, cid, path2)
    assert client.delete(f"/api/runs/{run_id}").status_code == 204
    assert not path2.exists() and not path2.parent.exists()


def test_retention_deletes_old_video_and_the_sweep_removes_orphans(client):
    pid, cid = _setup(client)
    eid = client.post("/api/experiments", json={"project_id": pid, "camera_id": cid, "name": "Retention"}).json()["id"]
    run_id = _run(eid, cid)
    old = _video(run_id, "old")
    new = _video(run_id, "new")
    _add(run_id, eid, cid, old, ended_ago_s=10 * 86400)
    keep = _add(run_id, eid, cid, new)
    stray = _video(run_id, "unfinished")  # a file no row refers to: a worker crashed while writing it
    gone_run = _video(987654, "left-behind")  # the run was deleted with its experiment
    try:
        client.put("/api/settings", json={"values": {"video_retention_days": 7}})
        result = sweep(active_run_ids=set())
        assert result["expired"] == 1 and result["orphans"] == 2
        assert not old.exists() and new.exists() and not stray.exists() and not gone_run.parent.exists()
        assert [r["id"] for r in client.get(f"/api/runs/{run_id}/recordings").json()] == [keep]
    finally:
        client.put("/api/settings", json={"values": {"video_retention_days": 0}})


def test_files_outside_the_recordings_folder_are_never_served_or_deleted(client, data_dir):
    pid, cid = _setup(client)
    eid = client.post("/api/experiments", json={"project_id": pid, "camera_id": cid, "name": "Guard"}).json()["id"]
    run_id = _run(eid, cid)
    outside = data_dir / "not-a-recording.avi"
    outside.write_bytes(b"x" * 10)
    session = get_session_factory()()
    try:
        now = datetime.now(UTC)
        row = Recording(run_id=run_id, kind="event", path=str(outside), mime="video/mp4", started_at=now - timedelta(seconds=2), ended_at=now, triggers=[])
        session.add(row)
        session.commit()
        rid = row.id
    finally:
        session.close()
    assert client.get(f"/api/recordings/{rid}/file").status_code == 404
    assert delete_files([str(outside)]) == 0 and outside.exists()
