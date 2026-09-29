"""Video files recorded from live cameras: rows, deletion, retention.

The worker writes the files (``pathscope.vision.recording``); the supervisor
stores one row per finished file through ``add_recording``. Deleting a
recording or a run removes its files at once. The maintenance sweep enforces
the video retention setting and removes files whose run no longer exists (an
experiment or project was deleted) or that were never finished (a worker
crashed while writing).
"""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from pathscope.config import get_settings
from pathscope.db.models import Recording, Run
from pathscope.db.session import get_session_factory
from pathscope.logging_setup import get_logger

log = get_logger(__name__)

PLAYABLE = ("video/mp4", "video/webm")


def run_dir(run_id: int) -> Path:
    return get_settings().recordings_dir / f"run-{run_id}"


def inside_recordings(path: str | Path) -> bool:
    root = get_settings().recordings_dir.resolve()
    try:
        return Path(path).resolve().is_relative_to(root)
    except OSError:
        return False


def add_recording(run_id: int, experiment_id: int | None, camera_id: int | None, info: dict) -> int | None:
    """Store the row of a finished file (called by the supervisor)."""
    session = get_session_factory()()
    try:
        row = Recording(
            run_id=run_id, experiment_id=experiment_id, camera_id=camera_id,
            kind=str(info.get("kind", "event")), path=str(info["path"]), mime=str(info.get("mime", "video/mp4")),
            codec=str(info.get("codec", "")), width=int(info.get("width", 0)), height=int(info.get("height", 0)),
            fps=float(info.get("fps", 0.0)), frames=int(info.get("frames", 0)),
            media_start_s=float(info.get("media_start_s", 0.0)), media_end_s=float(info.get("media_end_s", 0.0)),
            started_at=datetime.fromtimestamp(float(info.get("wall_start", time.time())), tz=UTC),
            ended_at=datetime.fromtimestamp(float(info.get("wall_end", time.time())), tz=UTC),
            size_bytes=int(info.get("size_bytes", 0)), overlay=bool(info.get("overlay", True)),
            triggers=list(info.get("triggers") or [])[:100], trigger_count=int(info.get("trigger_count", 0)),
        )
        session.add(row)
        session.commit()
        return row.id
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.warning("recording not stored", run_id=run_id, error=str(exc)[:200])
        return None
    finally:
        session.close()


def delete_files(paths: Iterable[str]) -> int:
    """Remove recording files (only inside the recordings folder) and empty run folders."""
    removed = 0
    folders: set[Path] = set()
    for p in paths:
        path = Path(p)
        if not inside_recordings(path):
            log.warning("recording outside the recordings folder not deleted", path=str(path))
            continue
        try:
            path.unlink(missing_ok=True)
            removed += 1
        except OSError as exc:
            log.warning("recording file not deleted", path=str(path), error=str(exc))
        folders.add(path.parent)
    for folder in folders:
        try:
            if folder.exists() and not any(folder.iterdir()):
                folder.rmdir()
        except OSError:
            pass
    return removed


def delete_recordings(session: Session, rows: list[Recording]) -> int:
    paths = [r.path for r in rows]
    for r in rows:
        session.delete(r)
    session.commit()
    return delete_files(paths)


def sweep(now: datetime | None = None, active_run_ids: set[int] | None = None) -> dict:
    """Apply video retention and remove files that no row refers to."""
    from pathscope.settings_store import get_setting

    now = now or datetime.now(UTC)
    root = get_settings().recordings_dir
    session = get_session_factory()()
    expired = orphans = 0
    try:
        days = int(get_setting(session, "video_retention_days", 0) or 0)
        if days > 0:
            old = list(session.scalars(select(Recording).where(Recording.ended_at < now - timedelta(days=days))))
            expired = delete_recordings(session, old) if old else 0
        if root.exists():
            active = active_run_ids if active_run_ids is not None else _active_runs()
            known = {Path(p).resolve() for p in session.scalars(select(Recording.path))}
            runs = set(session.scalars(select(Run.id)))
            for folder in root.iterdir():
                if not folder.is_dir() or not folder.name.startswith("run-"):
                    continue
                try:
                    run_id = int(folder.name[4:])
                except ValueError:
                    continue
                if run_id not in runs:
                    shutil.rmtree(folder, ignore_errors=True)
                    orphans += 1
                    continue
                if run_id in active:
                    continue  # files of a running run are still being written
                for f in folder.iterdir():
                    if f.is_file() and f.resolve() not in known:
                        f.unlink(missing_ok=True)
                        orphans += 1
                if not any(folder.iterdir()):
                    folder.rmdir()
    finally:
        session.close()
    if expired or orphans:
        log.info("recordings swept", expired=expired, orphans=orphans)
    return {"expired": expired, "orphans": orphans}


def _active_runs() -> set[int]:
    from pathscope.workers.supervisor import get_supervisor

    return {h.run_id for h in get_supervisor().active()}


def usage(session: Session) -> dict:
    rows = list(session.execute(select(Recording.size_bytes)))
    return {"files": len(rows), "bytes": int(sum(r[0] or 0 for r in rows))}


_stop = threading.Event()
_thread: threading.Thread | None = None


def start_maintenance(interval_s: float = 3600.0, first_delay_s: float = 60.0) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()

    def _loop() -> None:
        if _stop.wait(first_delay_s):
            return
        while True:
            try:
                sweep()
            except Exception as exc:  # noqa: BLE001
                log.warning("recording sweep failed", error=str(exc)[:200])
            if _stop.wait(interval_s):
                return

    _thread = threading.Thread(target=_loop, name="recording-maintenance", daemon=True)
    _thread.start()


def stop_maintenance() -> None:
    _stop.set()
