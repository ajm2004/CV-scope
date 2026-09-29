"""Camera worker process entry point.

Runs one pipeline for one run. Communicates with the supervisor through two
queues: ``out_q`` (status, events, track summaries) and ``preview_q``
(bounded; frames are dropped when the consumer is slow). Commands arrive on
``cmd_q``.
"""

from __future__ import annotations

import os
import queue
import time
import traceback
from dataclasses import asdict

from pathscope.workers.messages import (
    Command,
    OutMessage,
    PreviewMessage,
    StatusMessage,
    WorkerSpec,
)


def _build_pipeline(spec: WorkerSpec):
    from pathscope.domain.rules import Rule
    from pathscope.domain.scene import SceneDocument
    from pathscope.vision.detectors import DetectorConfig
    from pathscope.vision.pipeline import Pipeline, PipelineConfig
    from pathscope.vision.preprocessing import PreprocessConfig

    scene = SceneDocument.model_validate(spec.scene) if spec.scene else None
    rules = [Rule.model_validate(r) for r in spec.rules]
    det = DetectorConfig(
        model_id=spec.model_id,
        weights_path=spec.weights_path,
        provider=spec.provider,
        device=spec.device,
        image_size=spec.image_size,
        confidence=spec.confidence,
        iou=spec.iou,
        half=spec.half,
        classes=list(spec.tracked_classes),
        extra={"family": spec.family},
    )
    cfg = PipelineConfig(
        source_type=spec.source_type,
        source_uri=spec.source_uri,
        detector=det,
        scene=scene,
        rules=rules,
        tracked_classes=list(spec.tracked_classes),
        tracker_id=spec.tracker_id,
        tracker_settings=spec.tracker_settings,
        preprocess=PreprocessConfig(rotation=spec.rotation, crop=spec.crop),
        processing_fps=spec.processing_fps,
        frame_skip=spec.frame_skip,
        source_width=spec.source_width,
        source_height=spec.source_height,
        source_fps=spec.source_fps,
        reconnect=spec.reconnect,
        rtsp_transport=spec.rtsp_transport,
        realtime=spec.realtime,
        loop=spec.loop,
        recorded_at=spec.recorded_at,
        models_dir=spec.models_dir or None,
        recognition=spec.recognition,
        relations_enabled=bool(spec.relations),
    )
    return Pipeline(cfg)


def _track_summary(pipeline, track, route_result: str | None, wall_now: float) -> dict:
    rec = pipeline.spatial.pop_record(track.track_id)
    points = [[round(p.t, 3), round(p.x, 4), round(p.y, 4)] for p in (rec.points if rec else [])]
    path_len = None
    if rec and len(rec.points) >= 2:
        mapper = pipeline.spatial.mapper
        path_len = sum(
            mapper.distance((a.x, a.y), (b.x, b.y)) for a, b in zip(rec.points, rec.points[1:], strict=False)
        )
    duration = track.last_time - track.first_time
    media_now = pipeline._last_processed_t
    return {
        "track_id": track.track_id,
        "object_class": track.class_name,
        "first_seen_s": track.first_time,
        "last_seen_s": track.last_time,
        "first_seen_wall": wall_now - (media_now - track.first_time),
        "last_seen_wall": wall_now - (media_now - track.last_time),
        "n_frames": rec.n_frames if rec else track.hits,
        "path_length": path_len,
        "path_unit": pipeline.spatial.mapper.unit,
        "avg_speed": (path_len / duration) if (path_len is not None and duration > 0) else None,
        "speed_unit": pipeline.spatial.mapper.speed_unit,
        "mean_confidence": rec.mean_confidence if rec else track.mean_confidence,
        "final_state": "removed",
        "route_result": route_result,
        "lost_count": rec.lost_count if rec else 0,  # lost and found again, not the final loss
        "points": points,
    }


def run_camera_worker(spec: WorkerSpec, cmd_q, out_q, preview_q) -> None:  # noqa: C901 - worker loop
    os.environ.setdefault("TORCH_HOME", os.path.join(spec.models_dir, "torch") if spec.models_dir else "")
    from pathscope.logging_setup import configure_logging, get_logger
    from pathscope.vision.preprocessing import encode_jpeg, resize_for_preview

    configure_logging(spec.log_level, spec.log_format)
    log = get_logger("pathscope.worker").bind(run_id=spec.run_id, camera_id=spec.camera_id)
    recorder = None  # video recording of the run, when the experiment asks for it
    watcher = None  # Anomaly Assistant of the run, when the experiment turns it on
    relations = None  # relationship engine of the run, when the experiment turns it on

    def send_status(state: str, pipeline=None, error: str | None = None, timings: dict | None = None) -> None:
        msg = StatusMessage(state=state, error=error, wall_time=time.time())
        if pipeline is not None and pipeline.spatial is not None:
            info = pipeline.info
            msg.frame_index = pipeline.read_frames
            msg.media_time_s = pipeline._last_processed_t if pipeline._last_processed_t > -1e8 else 0.0
            msg.processed_frames = pipeline.processed_frames
            msg.read_frames = pipeline.read_frames
            msg.pipeline_fps = round(pipeline.pipeline_fps(), 2)
            msg.source_fps = info.fps if info else 0.0
            msg.timings_ms = {k: round(v, 2) for k, v in (timings or {}).items()}
            msg.counters = pipeline.rules.counters_list()
            msg.tracker = pipeline.tracker.stats().to_dict()
            msg.rule_stats = dict(pipeline.rules.stats)
            msg.active_tracks = sum(1 for t in pipeline._last_tracks if t.state == "tracked")
            msg.routes_in_progress = pipeline.rules.routes_in_progress()
            msg.zone_occupancy = pipeline.spatial.zone_occupancy()
            msg.detector = pipeline.detector.describe() if pipeline.detector else {}
            msg.source = info.to_dict() if info else {}
            src = pipeline.source
            msg.reconnects = getattr(src, "reconnect_count", 0)
            if recorder is not None:
                msg.recording = recorder.state
            if watcher is not None:
                msg.anomaly = watcher.assistant.status()
            if relations is not None:
                msg.relations = relations.engine.status()
            if info and info.frame_count:
                msg.progress = min(1.0, pipeline.read_frames / info.frame_count)
            if pipeline.recognition is not None:
                msg.recognition = {
                    "modules": sorted(pipeline.recognition.provides()),
                    "face": dict(pipeline.recognition.face.stats) if pipeline.recognition.face else None,
                    "plate": dict(pipeline.recognition.plate.stats) if pipeline.recognition.plate else None,
                    "pending_rule_events": pipeline.rules.pending_count(),
                }
        out_q.put(OutMessage("status", asdict(msg)))

    pipeline = None
    last_wall: float | None = None  # wall time of the last processed frame
    try:
        send_status("starting")
        pipeline = _build_pipeline(spec)
        pipeline.open()
        send_status("running", pipeline)
        out_q.put(
            OutMessage(
                "snapshot",
                {
                    "detector": pipeline.detector.describe(),
                    "tracker": pipeline.tracker.describe(),
                    "source": pipeline.info.to_dict(),
                    "geometry_frame": [pipeline.frame_width, pipeline.frame_height],
                    "calibration": pipeline.spatial.mapper.describe(),
                    "rules": pipeline.rules.describe(),
                    "recognition": _recognition_snapshot(pipeline, spec),
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        log.error("worker failed to start", error=str(exc), tb=traceback.format_exc())
        send_status("failed", None, error=f"{type(exc).__name__}: {exc}")
        return

    record = None
    if spec.recording and spec.recording.get("mode", "off") != "off":
        try:
            record = _Recording(spec, pipeline, out_q)
            recorder = record.recorder
        except Exception as exc:  # noqa: BLE001 - the analysis runs on without video
            log.error("video recording not started", error=str(exc))
    if spec.relations:
        try:
            relations = _Relations(spec, pipeline, out_q)
        except Exception as exc:  # noqa: BLE001 - the analysis runs on without relationships
            log.error("relationship engine not started", error=str(exc), tb=traceback.format_exc())
    if spec.anomaly:
        try:
            watcher = _Anomalies(spec, pipeline, out_q, record)
        except Exception as exc:  # noqa: BLE001 - the analysis runs on without the assistant
            log.error("anomaly assistant not started", error=str(exc), tb=traceback.format_exc())

    paused = False
    stop = False
    preview_interval = 1.0 / max(spec.preview_fps, 0.5)
    last_preview = 0.0
    last_status = 0.0
    route_results: dict[int, str] = {}
    final_state = "finished"
    error_text: str | None = None
    consecutive_errors = 0
    last_timings: dict = {}  # kept so the final status carries the last measured timings

    try:
        while not stop:
            # ---- commands
            try:
                while True:
                    cmd: Command = cmd_q.get_nowait()
                    if cmd.kind == "stop":
                        stop = True
                        final_state = "stopped"
                    elif cmd.kind == "pause":
                        paused = True
                        send_status("paused", pipeline)
                    elif cmd.kind == "resume":
                        paused = False
                        send_status("running", pipeline)
                    elif cmd.kind == "seek":
                        pipeline.seek(float(cmd.payload.get("media_time_s", 0.0)))
                    elif cmd.kind == "set_preview":
                        preview_interval = 1.0 / max(float(cmd.payload.get("fps", spec.preview_fps)), 0.5)
                    elif cmd.kind == "anomaly_rebaseline" and watcher is not None:
                        watcher.rebaseline(cmd.payload.get("zone_id"))
            except queue.Empty:
                pass
            if stop:
                break
            if paused:
                time.sleep(0.05)
                continue

            # ---- one pipeline step
            try:
                result = pipeline.step()
                consecutive_errors = 0
            except Exception as exc:  # noqa: BLE001
                consecutive_errors += 1
                log.error("pipeline step failed", error=str(exc), consecutive=consecutive_errors)
                if consecutive_errors >= 10:
                    final_state = "failed"
                    error_text = f"{type(exc).__name__}: {exc}"
                    break
                time.sleep(0.1)
                continue
            if result is None:
                if pipeline.info is not None and pipeline.info.is_live:
                    # A live camera has no "end": it disappeared and could not be reopened.
                    final_state = "failed"
                    error_text = "The camera stopped delivering frames and could not be reopened."
                else:
                    final_state = "finished"
                break
            if result.processed:
                # The time the frame was taken: the clock for live sources, the
                # recording time for a video file with a known start.
                last_wall = result.packet.wall_time

            # ---- video recording (processed frames, with the events of this frame)
            if record is not None and result.processed:
                record.frame(result)

            # ---- anomaly assistant (its own analysis rate, on processed frames)
            if watcher is not None and result.processed:
                try:
                    watcher.frame(result)
                except Exception as exc:  # noqa: BLE001 - never ends the run
                    log.warning("anomaly analysis failed", error=str(exc))

            # ---- relationship engine (tracks, interactions and events of processed frames)
            if relations is not None and result.processed:
                try:
                    relations.frame(result)
                except Exception as exc:  # noqa: BLE001 - never ends the run
                    log.warning("relationship analysis failed", error=str(exc))

            # ---- events and track summaries
            if result.events:
                out_q.put(OutMessage("events", [e.to_dict() for e in result.events]))
                for e in result.events:
                    if e.event_type == "route":
                        route_results[e.track_id] = e.route or e.label
            if result.recognition_events:
                out_q.put(OutMessage("recognition_events", result.recognition_events))
            if pipeline.recognition is not None and pipeline.recognition.diagnostics_due(time.time()):
                out_q.put(OutMessage("recognition_diag", pipeline.recognition.diagnostics()))
            if result.update is not None and result.update.removed:
                summaries = [
                    _track_summary(pipeline, tr, route_results.pop(tr.track_id, None), result.packet.wall_time)
                    for tr in result.update.removed
                ]
                if not spec.store_trajectories:
                    for s in summaries:
                        s["points"] = []
                out_q.put(OutMessage("track_ended", summaries))

            # ---- preview (throttled, dropped when the consumer is behind)
            now = time.time()
            if now - last_preview >= preview_interval:
                last_preview = now
                small = resize_for_preview(result.frame, spec.preview_max_width)
                try:
                    jpeg = encode_jpeg(small, spec.preview_jpeg_quality)
                    msg = PreviewMessage(
                        frame_index=result.packet.frame_index,
                        media_time_s=result.packet.media_time_s,
                        width=small.shape[1],
                        height=small.shape[0],
                        source_width=pipeline.frame_width,
                        source_height=pipeline.frame_height,
                        jpeg=jpeg,
                        tracks=[_track_overlay(t, pipeline) for t in result.tracks],
                        interactions=[_interaction_dict(i) for i in result.interactions],
                        events=[{"type": e.event_type, "label": e.label, "track_id": e.track_id, "route": e.route} for e in result.events],
                        processed=result.processed,
                    )
                    try:
                        preview_q.put_nowait(msg)
                    except queue.Full:
                        pass
                except Exception as exc:  # noqa: BLE001
                    log.warning("preview encode failed", error=str(exc))

            if now - last_status >= 1.0:
                last_status = now
                send_status("running", pipeline, timings=result.timings_ms)
            if result.processed:
                last_timings = result.timings_ms
    except Exception as exc:  # noqa: BLE001
        final_state = "failed"
        error_text = f"{type(exc).__name__}: {exc}"
        log.error("worker crashed", error=error_text, tb=traceback.format_exc())
    finally:
        # Flush every live track as a summary so partial observations are kept
        try:
            if pipeline is not None and pipeline.tracker is not None:
                now = last_wall if last_wall is not None else time.time()
                live = [t for t in pipeline._last_tracks if t.track_id]
                # Close open zone visits (their dwell is recorded) and mark routes that are
                # still in progress as LOST_TRACK.
                end_interactions = pipeline.spatial.end_tracks(live, pipeline.read_frames, reason="run_ended") if pipeline.spatial else []
                if end_interactions and pipeline.rules is not None:
                    evs = pipeline.rules.process(end_interactions, pipeline._last_processed_t, pipeline.read_frames, now)
                    if evs:
                        if record is not None:
                            record.triggers(evs)
                        out_q.put(OutMessage("events", [e.to_dict() for e in evs]))
                        for e in evs:
                            if e.event_type == "route":
                                route_results[e.track_id] = e.route or e.label
                if relations is not None:
                    relations.finish(end_interactions, evs if end_interactions and pipeline.rules is not None else [], pipeline._last_processed_t, now)
                summaries = [_track_summary(pipeline, t, route_results.pop(t.track_id, None), now) for t in live]
                for s in summaries:
                    s["final_state"] = "active_at_end"
                    if not spec.store_trajectories:
                        s["points"] = []
                if summaries:
                    out_q.put(OutMessage("track_ended", summaries))
            if watcher is not None:
                watcher.finish()  # open anomalies end with the run
            if record is not None:
                record.close()  # reports the last file before the final status
            send_status(final_state, pipeline, error=error_text, timings=last_timings)
        except Exception as exc:  # noqa: BLE001
            log.error("worker finalisation failed", error=str(exc))
            out_q.put(OutMessage("status", asdict(StatusMessage(state="failed", error=str(exc), wall_time=time.time()))))
        try:
            if pipeline is not None:
                pipeline.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("worker exited", state=final_state)


class _ModuleFilter:
    """The recognition runtime as the relationship engine may use it (per-module switches)."""

    def __init__(self, inner, modules: set[str]) -> None:
        self.inner = inner
        self.modules = modules

    def provides(self) -> set[str]:
        return set(self.inner.provides()) & self.modules

    def resolve(self, track_id: int, object_class: str):
        from pathscope.domain.entities import anonymous_entity, module_for_class

        if module_for_class(object_class) not in self.modules:
            return anonymous_entity(track_id, object_class, settled=True)
        return self.inner.resolve(track_id, object_class)

    def forget(self, track_id: int) -> None:
        return None


class _Relations:
    """Feeds processed frames to the run's relationship engine and sends what it forms."""

    FLUSH_S = 0.5

    def __init__(self, spec: WorkerSpec, pipeline, out_q) -> None:
        from pathscope.relationships import (
            CompiledRule,
            EngineContext,
            RelationEngine,
            relation_settings,
        )

        cfg = spec.relations or {}
        self.out_q = out_q
        rules = [CompiledRule.model_validate(r) for r in cfg.get("rules") or []]
        settings = relation_settings(cfg.get("settings"))
        resolver = None
        if pipeline.recognition is not None:
            resolver = _ModuleFilter(pipeline.recognition, set(cfg.get("modules") or []))
        ctx = EngineContext(
            run_id=spec.run_id, camera_id=spec.camera_id, experiment_id=spec.experiment_id, frame_width=pipeline.frame_width, frame_height=pipeline.frame_height,
            scene=pipeline.spatial.scene, scene_config_id=None, scene_version=cfg.get("scene_version"), plate_salt=bytes.fromhex(cfg.get("plate_salt") or "00" * 16),
        )
        self.engine = RelationEngine(ctx, rules, settings, resolver)
        pipeline.rules.relations = self.engine  # rules with a HAS RELATIONSHIP clause
        self._last = time.time()
        out_q.put(OutMessage("relations", {"kind": "describe", "describe": self.engine.describe()}))

    def frame(self, result) -> None:
        self.engine.step(result.packet.media_time_s, result.packet.wall_time, result.tracks, result.interactions, result.events)
        if time.time() - self._last >= self.FLUSH_S:
            self.flush()

    def flush(self) -> None:
        self._last = time.time()
        p = self.engine.drain()
        if p:
            self.out_q.put(OutMessage("relations", p))

    def finish(self, interactions, events, t: float, wall: float) -> None:
        try:
            if interactions:
                self.engine.step(t, wall, [], interactions, events)
            self.engine.finish(t, wall)
        finally:
            self.flush()
            self.out_q.put(OutMessage("relations", {"kind": "status", "status": self.engine.status()}))


class _Recording:
    """Feeds the run's processed frames and events to the video recorder."""

    def __init__(self, spec: WorkerSpec, pipeline, out_q) -> None:
        from pathlib import Path

        from pathscope.domain.recording import RecordingSettings
        from pathscope.vision.recording import RunRecorder

        self.spec = spec
        self.pipeline = pipeline
        self.settings = RecordingSettings.model_validate(spec.recording)
        # The video has the processing rate: every recorded frame shows its own analysis.
        rate = pipeline.info.fps if pipeline.info and pipeline.info.fps else 15.0
        if spec.processing_fps:
            rate = min(rate, float(spec.processing_fps))
        rate /= max(1, spec.frame_skip + 1)
        self.banners: list[tuple[float, str]] = []
        self.recorder = RunRecorder(self.settings, Path(spec.recordings_dir), rate, lambda info: out_q.put(OutMessage("recording", info)))

    def frame(self, result) -> None:
        from pathscope.vision.recording import BANNER_S, draw_overlay, overlay_header

        t = result.packet.media_time_s
        for e in result.events:
            if e.record:
                self.banners.append((t + BANNER_S, f"{e.label} #{e.track_id}" if e.track_id else e.label))
        self.banners = [b for b in self.banners if b[0] >= t]
        if self.settings.overlay:
            img = draw_overlay(result.frame, result.tracks, self.pipeline.spatial.scene,
                               overlay_header(self.spec.run_id, t, result.packet.wall_time), [b[1] for b in self.banners])
        else:
            img = result.frame.copy()
        # The live tracks tell "from entry to exit" when a visit really ended.
        active = {tr.track_id for tr in result.tracks if tr.state == "tracked"}
        self.recorder.add_frame(img, t, result.packet.wall_time, active_ids=active)
        self.triggers(result.events)

    def triggers(self, events) -> None:
        wanted = set(self.settings.event_types)
        for e in events:
            if e.record and (not wanted or e.event_type in wanted):
                self.recorder.trigger(e.media_time_s, {"type": e.event_type, "label": e.label, "track_id": e.track_id, "object_id": e.object_id, "media_time_s": round(e.media_time_s, 3)})

    def close(self) -> None:
        self.recorder.close()


class _Anomalies:
    """Runs the Anomaly Assistant on the processed frames and reports its events."""

    def __init__(self, spec: WorkerSpec, pipeline, out_q, record: _Recording | None) -> None:
        from pathlib import Path

        from pathscope.anomaly import AnomalyAssistant, AnomalySettings, EvidenceWriter

        cfg = spec.anomaly or {}
        self.settings = AnomalySettings.model_validate(cfg.get("settings") or {})
        zones = {k: [tuple(p) for p in v] for k, v in (cfg.get("zones") or {}).items()}
        ignore = [[tuple(p) for p in poly] for poly in cfg.get("ignore") or []]
        self.assistant = AnomalyAssistant(self.settings, (pipeline.frame_width, pipeline.frame_height), zones, ignore)
        self.writer = EvidenceWriter(Path(spec.anomaly_dir))
        self.pipeline = pipeline
        self.out_q = out_q
        self.record = record
        self.last_frame = None
        self.last_tracks: list = []

    def frame(self, result) -> None:
        self.last_frame = result.frame
        self.last_tracks = result.tracks
        updates = self.assistant.observe(result.frame, result.packet.media_time_s, result.packet.wall_time, objects=result.tracks, resolver=self.pipeline.recognition)
        if updates:
            self._emit(updates)

    def rebaseline(self, zone_id: str | None) -> None:
        updates = self.assistant.finish(reason="rebaselined") if zone_id is None else []
        self.assistant.rebaseline(zone_id, self.last_frame)
        if updates:
            self._emit(updates)

    def finish(self) -> None:
        updates = self.assistant.finish()
        if updates:
            self._emit(updates)

    def _emit(self, updates) -> None:
        boxes_by_id = {t.track_id: t.box for t in self.last_tracks}
        payload = []
        for u in updates:
            # Object boxes on the evidence carry the class and the anonymous track number only
            boxes = [(f"{o['object_class']} #{o['track_id']}", boxes_by_id[o["track_id"]]) for o in u.objects if o["track_id"] in boxes_by_id]
            try:
                files = self.writer.write(u, boxes)
            except Exception:  # noqa: BLE001 - the event is reported without pictures
                files = {}
            d = u.to_dict()
            d["evidence"] = files
            payload.append(d)
            self._clip(u)
        self.out_q.put(OutMessage("anomalies", payload))

    def _clip(self, u) -> None:
        """Start (confirmed) or extend (ended) a video clip, when the experiment records events."""
        rec = self.record
        if rec is None or not u.zone.get("record_clip", True):
            return
        wanted = set(rec.settings.event_types)
        if wanted and "anomaly" not in wanted:
            return
        t = u.confirmed_t if u.phase == "confirmed" else (u.ended_t or u.confirmed_t)
        track = u.objects[0]["track_id"] if u.objects else 0
        rec.recorder.trigger(t, {"type": "anomaly", "label": f"Anomaly · {u.zone_name}", "track_id": track, "object_id": u.zone_id, "media_time_s": round(t, 3)})


def _recognition_snapshot(pipeline, spec: WorkerSpec) -> dict:
    """Recorded with the run: modules, models and counts, never templates or plates."""
    if pipeline.recognition is None:
        return {"modules": [], "warnings": (spec.recognition or {}).get("warnings", []) if spec.recognition else []}
    desc = pipeline.recognition.describe()
    out = {"modules": desc["modules"], "warnings": (spec.recognition or {}).get("warnings", []), "subject_grace_s": desc["subject_grace_s"]}
    if desc.get("face"):
        out["face"] = {"stack": desc["face"]["stack"], "matcher": desc["face"]["matcher"]}
    if desc.get("plate"):
        out["plate"] = {"stack": desc["plate"]["stack"], "parser": desc["plate"]["parser"], "vehicles": desc["plate"]["vehicles"]}
    return out


def _track_overlay(t, pipeline) -> dict:
    d = t.to_dict()
    rec = pipeline.spatial.records.get(t.track_id)
    if rec is not None:
        pts = rec.points[-40:]
        d["trail"] = [[round(p.x, 4), round(p.y, 4)] for p in pts]
    d["zones"] = pipeline.spatial.zones_of(t.track_id)
    if pipeline.recognition is not None:
        overlay = pipeline.recognition.overlay(t.track_id, t.class_name)
        if overlay:
            d["recognition"] = overlay  # stripped by the API for viewers without a recognition token
    # Candidate route state (for the debug overlay)
    for g in pipeline.rules.route_groups:
        prog = g.progress.get(t.track_id)
        if prog is not None:
            best = max(prog["routes"].items(), key=lambda kv: kv[1])
            route = next((r for r in g.routes if r.id == best[0]), None)
            d["route_state"] = {
                "group": g.label,
                "since_s": round(prog["start_t"], 2),
                "candidate": route.name if route and best[1] > 0 else None,
                "checkpoints": len(prog["passed"]),
            }
            break
    return d


def _interaction_dict(i) -> dict:
    return {
        "kind": i.kind,
        "track_id": i.track_id,
        "object_id": i.object_id,
        "object_name": i.object_name,
        "direction": i.direction,
        "t": round(i.t, 3),
    }
