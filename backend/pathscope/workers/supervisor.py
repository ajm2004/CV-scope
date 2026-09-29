"""Run supervisor: owns camera worker processes for active runs.

For every run it starts a worker process, drains its output queues on
background threads, persists events through an ``EventWriter``, keeps the
latest status/preview in memory for the API and WebSocket layers, dispatches
webhook actions, and restarts crashed workers for live sources.
"""

from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass, field

import httpx

from pathscope.config import get_settings
from pathscope.logging_setup import get_logger
from pathscope.storage.writer import EventWriter
from pathscope.workers.camera_worker import run_camera_worker
from pathscope.workers.messages import Command, OutMessage, PreviewMessage, WorkerSpec

log = get_logger(__name__)

TERMINAL_STATES = {"finished", "failed", "stopped"}


@dataclass
class RunHandle:
    run_id: int
    spec: WorkerSpec
    process: mp.Process | None = None
    cmd_q: object = None
    out_q: object = None
    preview_q: object = None
    writer: EventWriter | None = None
    status: dict = field(default_factory=dict)
    latest_preview: PreviewMessage | None = None
    preview_seq: int = 0
    annotated_jpeg: bytes | None = None
    annotated_seq: int = -1
    # The same frame with recognized names drawn in, for viewers with a token
    annotated_id_jpeg: bytes | None = None
    annotated_id_seq: int = -1
    recent_events: deque = field(default_factory=lambda: deque(maxlen=500))
    event_seq: int = 0
    recognition_diag: dict | None = None  # latest per-track diagnostics of the licensed modules
    recognition_events: int = 0
    recordings: int = 0
    anomalies: int = 0  # anomaly events received from the worker (confirmed)
    restarts: int = 0
    started_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    finished: bool = False
    final_state: str | None = None
    stop_requested: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def state(self) -> str:
        return self.status.get("state", "starting")


class RunSupervisor:
    def __init__(self) -> None:
        self._runs: dict[int, RunHandle] = {}
        self._lock = threading.Lock()
        self._ctx = mp.get_context("spawn")
        self._watchdog = threading.Thread(target=self._watch, daemon=True, name="run-watchdog")
        self._watchdog_started = False
        self._http = httpx.Client(timeout=5.0)

    # ------------------------------------------------------------------ public
    def start(self, spec: WorkerSpec) -> RunHandle:
        with self._lock:
            if spec.run_id in self._runs and not self._runs[spec.run_id].finished:
                raise RuntimeError(f"run {spec.run_id} is already active")
            handle = RunHandle(run_id=spec.run_id, spec=spec)
            handle.writer = EventWriter(spec.run_id, spec.experiment_id, spec.camera_id, spec.store_trajectories)
            self._runs[spec.run_id] = handle
            self._spawn(handle)
            if not self._watchdog_started:
                self._watchdog.start()
                self._watchdog_started = True
        handle.writer.update_run(status="starting", snapshot={"model_id": spec.model_id, "provider": spec.provider, "device": spec.device, "image_size": spec.image_size, "tracker_id": spec.tracker_id})
        return handle

    def get(self, run_id: int) -> RunHandle | None:
        with self._lock:
            return self._runs.get(run_id)

    def active(self) -> list[RunHandle]:
        with self._lock:
            return [h for h in self._runs.values() if not h.finished]

    def all(self) -> list[RunHandle]:
        with self._lock:
            return list(self._runs.values())

    def send(self, run_id: int, kind: str, payload: dict | None = None) -> bool:
        handle = self.get(run_id)
        if handle is None or handle.finished or handle.cmd_q is None:
            return False
        if kind == "stop":
            handle.stop_requested = True
        try:
            handle.cmd_q.put(Command(kind, payload or {}))
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("command send failed", run_id=run_id, error=str(exc))
            return False

    def stop(self, run_id: int, timeout_s: float = 15.0) -> bool:
        handle = self.get(run_id)
        if handle is None:
            return False
        if handle.finished:
            return True
        handle.stop_requested = True
        self.send(run_id, "stop")
        deadline = time.time() + timeout_s
        while time.time() < deadline and not handle.finished:
            time.sleep(0.1)
        if not handle.finished:
            log.warning("worker did not stop in time; terminating", run_id=run_id)
            self._terminate(handle)
            self._finalize(handle, "stopped", "Worker terminated after timeout")
        return True

    def stop_all(self) -> None:
        for h in self.active():
            self.stop(h.run_id, timeout_s=8.0)
        try:
            self._http.close()
        except Exception:  # noqa: BLE001
            pass

    def forget(self, run_id: int) -> None:
        with self._lock:
            h = self._runs.get(run_id)
            if h and h.finished:
                del self._runs[run_id]

    # ------------------------------------------------------------------ internals
    def _spawn(self, handle: RunHandle) -> None:
        handle.cmd_q = self._ctx.Queue()
        handle.out_q = self._ctx.Queue()
        handle.preview_q = self._ctx.Queue(maxsize=2)
        handle.process = self._ctx.Process(
            target=run_camera_worker,
            args=(handle.spec, handle.cmd_q, handle.out_q, handle.preview_q),
            name=f"pathscope-run-{handle.run_id}",
            daemon=True,
        )
        handle.process.start()
        handle.last_heartbeat = time.time()
        threading.Thread(target=self._drain_out, args=(handle,), daemon=True, name=f"drain-{handle.run_id}").start()
        threading.Thread(target=self._drain_preview, args=(handle,), daemon=True, name=f"preview-{handle.run_id}").start()
        log.info("worker started", run_id=handle.run_id, pid=handle.process.pid)

    def _terminate(self, handle: RunHandle) -> None:
        p = handle.process
        if p is not None and p.is_alive():
            p.terminate()
            p.join(3.0)
            if p.is_alive():
                p.kill()
                p.join(1.0)

    def _finalize(self, handle: RunHandle, state: str, error: str | None = None) -> None:
        with handle.lock:
            if handle.finished:
                return
            handle.finished = True
            handle.final_state = state
        if handle.writer is not None:
            handle.writer.flush()
            db_state = {"finished": "completed", "failed": "failed", "stopped": "stopped"}.get(state, state)
            handle.writer.update_run(status=db_state, stats=self._stats_from_status(handle.status), error=error, ended=True)
        handle.status["state"] = state
        if error:
            handle.status["error"] = error
        if handle.spec.relations:
            try:
                from pathscope.relationships.service import get_relationship_service

                get_relationship_service().finish_run(handle.run_id, handle, self)
            except Exception as exc:  # noqa: BLE001
                log.warning("relationship analysis not closed", run_id=handle.run_id, error=str(exc)[:300])
        log.info("run finalized", run_id=handle.run_id, state=state, events=handle.writer.written_events if handle.writer else None)

    @staticmethod
    def _stats_from_status(status: dict) -> dict:
        keys = ("processed_frames", "read_frames", "pipeline_fps", "counters", "tracker", "rule_stats", "timings_ms", "media_time_s", "reconnects", "zone_occupancy", "recognition", "recording", "anomaly", "relations")
        return {k: status.get(k) for k in keys if k in status}

    def _drain_out(self, handle: RunHandle) -> None:
        writer = handle.writer
        assert writer is not None
        last_stats_write = time.time()
        while True:
            try:
                msg: OutMessage = handle.out_q.get(timeout=0.5)
            except queue.Empty:
                writer.maybe_flush()
                if handle.finished:
                    break
                if handle.process is not None and not handle.process.is_alive():
                    # Process died; give the queue a moment then finish
                    time.sleep(0.5)
                    try:
                        msg = handle.out_q.get_nowait()
                    except queue.Empty:
                        break
                else:
                    continue
            except (EOFError, OSError):
                break
            handle.last_heartbeat = time.time()
            if msg.kind == "status":
                handle.status = msg.payload
                state = msg.payload.get("state")
                if state == "running" and time.time() - last_stats_write > 5.0:
                    last_stats_write = time.time()
                    writer.update_run(status="running", stats=self._stats_from_status(msg.payload))
                elif state in ("starting", "paused"):
                    writer.update_run(status=state if state != "starting" else "starting")
                elif state in TERMINAL_STATES:
                    self._finalize(handle, state, msg.payload.get("error"))
                    break
            elif msg.kind == "snapshot":
                writer.update_run(snapshot=msg.payload)
            elif msg.kind == "events":
                self.publish_events(handle, msg.payload)
            elif msg.kind == "track_ended":
                for s in msg.payload:
                    writer.add_track(s)
            elif msg.kind == "recognition_events":
                self._record_recognition(handle, msg.payload)
            elif msg.kind == "recognition_diag":
                handle.recognition_diag = msg.payload
            elif msg.kind == "anomalies":
                self._anomalies(handle, msg.payload)
            elif msg.kind == "relations":
                self._relations(handle, msg.payload)
            elif msg.kind == "recording":
                from pathscope.storage.recordings import add_recording

                if add_recording(handle.run_id, handle.spec.experiment_id, handle.spec.camera_id, msg.payload) is not None:
                    handle.recordings += 1
            writer.maybe_flush()
        writer.flush()

    def publish_events(self, handle: RunHandle, events: list[dict]) -> None:
        """Store events, show them live and send their webhooks (also used for
        anomalies raised after a model's verdict, possibly after the run ended)."""
        writer = handle.writer
        if writer is not None:
            writer.add_events(events)
        for e in events:
            handle.event_seq += 1
            handle.recent_events.append({"seq": handle.event_seq, **e})
            if handle.spec.webhooks_enabled:  # Settings: "Allow webhook actions"
                for url in e.get("webhooks") or []:
                    self._webhook(url, e, handle)
        if handle.finished and writer is not None:
            writer.flush()

    def notify(self, handle: RunHandle, urls: list[str], payload: dict) -> None:
        """Webhook follow-ups that are not new events (an anomaly described or ended)."""
        if handle.spec.webhooks_enabled:
            for url in urls:
                self._webhook(url, payload, handle)

    def _anomalies(self, handle: RunHandle, updates: list[dict]) -> None:
        try:
            from pathscope.anomaly.service import get_anomaly_service

            handle.anomalies += sum(1 for u in updates if u.get("phase") == "confirmed")
            get_anomaly_service().handle_updates(handle, updates, self)
        except Exception as exc:  # noqa: BLE001 - never stops draining the worker
            log.warning("anomaly events not recorded", run_id=handle.run_id, error=str(exc)[:300])

    def _relations(self, handle: RunHandle, payload: dict) -> None:
        try:
            from pathscope.relationships.service import get_relationship_service

            get_relationship_service().handle(handle, payload, self)
        except Exception as exc:  # noqa: BLE001 - never stops draining the worker
            log.warning("relationships not recorded", run_id=handle.run_id, error=str(exc)[:300])

    @staticmethod
    def _record_recognition(handle: RunHandle, events: list[dict]) -> None:
        """Recognition events go to their own restricted store, never to the ordinary event table."""
        try:
            from pathscope.recognition.events.recorder import record_events

            ids = record_events(handle.run_id, handle.spec.experiment_id, handle.spec.camera_id, events)
            handle.recognition_events += len(ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("recognition events not recorded", run_id=handle.run_id, error=str(exc)[:200])

    def _drain_preview(self, handle: RunHandle) -> None:
        while not handle.finished:
            try:
                msg: PreviewMessage = handle.preview_q.get(timeout=0.5)
            except queue.Empty:
                if handle.process is not None and not handle.process.is_alive():
                    break
                continue
            except (EOFError, OSError):
                break
            handle.latest_preview = msg
            handle.preview_seq += 1

    @staticmethod
    def annotated_preview(handle: RunHandle, identities: bool = False) -> tuple[int, bytes] | None:
        """The latest preview with tracked boxes drawn, made once per new frame.

        The plain frame and the one with recognized names are cached apart, so
        a viewer without a recognition token never receives a name."""
        msg, seq = handle.latest_preview, handle.preview_seq
        if msg is None:
            return None
        cached_seq = handle.annotated_id_seq if identities else handle.annotated_seq
        cached = handle.annotated_id_jpeg if identities else handle.annotated_jpeg
        if cached_seq != seq or cached is None:
            from pathscope.vision.overlay import annotate_jpeg

            try:
                cached = annotate_jpeg(msg.jpeg, msg.tracks, msg.width, msg.source_width, identities=identities)
            except Exception:  # noqa: BLE001 - fall back to the plain frame
                cached = msg.jpeg
            if identities:
                handle.annotated_id_jpeg, handle.annotated_id_seq = cached, seq
            else:
                handle.annotated_jpeg, handle.annotated_seq = cached, seq
        return seq, cached

    def _webhook(self, url: str, event: dict, handle: RunHandle) -> None:
        def _post():
            try:
                self._http.post(url, json={"run_id": handle.run_id, "event": event})
            except Exception as exc:  # noqa: BLE001
                log.warning("webhook failed", url=url, error=str(exc)[:200])

        threading.Thread(target=_post, daemon=True).start()

    def _watch(self) -> None:
        settings = get_settings()
        while True:
            time.sleep(2.0)
            for handle in self.active():
                p = handle.process
                if p is None:
                    continue
                if p.is_alive():
                    continue
                # Process exited: did it report a terminal state?
                time.sleep(1.0)
                if handle.finished:
                    continue
                live = handle.spec.source_type != "file"
                if live and not handle.stop_requested and handle.restarts < settings.worker_restart_limit:
                    handle.restarts += 1
                    log.warning("worker crashed; restarting", run_id=handle.run_id, attempt=handle.restarts)
                    handle.status = {"state": "starting", "error": f"worker restarted ({handle.restarts})"}
                    self._spawn(handle)
                else:
                    code = p.exitcode
                    self._finalize(handle, "failed" if not handle.stop_requested else "stopped", f"worker process exited unexpectedly (exit code {code})" if not handle.stop_requested else None)


_supervisor: RunSupervisor | None = None


def get_supervisor() -> RunSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = RunSupervisor()
    return _supervisor
