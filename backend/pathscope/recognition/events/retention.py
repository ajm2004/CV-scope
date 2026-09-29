"""Background retention sweeps (started with the API process)."""

from __future__ import annotations

import threading

from pathscope.logging_setup import get_logger

log = get_logger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()


def run_sweep() -> dict | None:
    from pathscope.db.session import get_session_factory
    from pathscope.recognition.common.audit import audit
    from pathscope.recognition.common.config import all_recognition_settings
    from pathscope.recognition.events.recorder import sweep_retention

    session = get_session_factory()()
    try:
        values = all_recognition_settings(session)
        result = sweep_retention(session, values)
        if any(result.values()):
            audit(session, None, "retention_sweep", detail=result)
            session.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        log.warning("recognition retention sweep failed", error=str(exc)[:200])
        return None
    finally:
        session.close()


def _loop(initial_delay_s: float, interval_s: float) -> None:
    if _stop.wait(initial_delay_s):
        return
    while not _stop.is_set():
        run_sweep()
        if _stop.wait(interval_s):
            return


def start_maintenance(initial_delay_s: float = 30.0, interval_s: float = 6 * 3600.0) -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(initial_delay_s, interval_s), daemon=True, name="recognition-retention")
    _thread.start()


def stop_maintenance() -> None:
    _stop.set()
