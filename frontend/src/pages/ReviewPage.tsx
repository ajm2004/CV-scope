import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { Recording, SceneDocument } from "../api/types";
import { ConfirmButton, ErrorNotice, Notice, Panel, Pill } from "../components/ui";
import { bytes, clock, dateTime, eventLabel, OBJECT_COLORS, seconds } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { entityLabel, useEntityNames } from "../recognition/useEntityNames";

const TRACK_COLORS = ["#ff5e5e", "#ffb347", "#f9f871", "#7bed9f", "#70d6ff", "#c39bff", "#ff8fd8", "#a0e7a0"];

interface Overlay {
  geometry: boolean;
  trajectories: boolean;
  ids: boolean;
  markers: boolean;
}

/**
 * Video review of a run. A run on a video file plays that file. A run on a
 * live camera plays the video it recorded (the experiment's Video recording),
 * one file at a time: the timeline covers the whole run and shades the parts
 * with video, and an event jumps to the file that covers it.
 */
export default function ReviewPage() {
  const { runId } = useParams();
  const id = Number(runId);
  const [search] = useSearchParams();
  const qc = useQueryClient();
  const run = useQuery({ queryKey: ["run", id], queryFn: () => api.runs.get(id) });
  const experiment = useQuery({ queryKey: ["experiment", run.data?.experiment_id], queryFn: () => api.experiments.get(run.data!.experiment_id), enabled: !!run.data });
  const camera = useQuery({ queryKey: ["camera", run.data?.camera_id], queryFn: () => api.cameras.get(run.data!.camera_id!), enabled: !!run.data?.camera_id });
  const scene = useQuery({ queryKey: ["scene", run.data?.scene_config_id], queryFn: () => api.scenes.get(run.data!.scene_config_id!), enabled: !!run.data?.scene_config_id });
  const timeline = useQuery({ queryKey: ["timeline", id], queryFn: () => api.events.timeline(id) });
  const traj = useQuery({ queryKey: ["trajectories", id], queryFn: () => api.analytics.trajectories(id) });
  const recordings = useQuery({ queryKey: ["recordings", id], queryFn: () => api.recordings.forRun(id) });
  const removeRecording = useMutation({
    mutationFn: (rid: number) => api.recordings.remove(rid),
    onSuccess: (_d, rid) => {
      if (current?.id === rid) setCurrent(null);
      qc.invalidateQueries({ queryKey: ["recordings", id] });
    },
  });
  const removeAll = useMutation({
    mutationFn: () => api.recordings.removeForRun(id),
    onSuccess: () => {
      setCurrent(null);
      qc.invalidateQueries({ queryKey: ["recordings", id] });
    },
  });
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [t, setT] = useState(0); // run media time at the player position
  const [duration, setDuration] = useState(0); // length of the loaded video
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [overlay, setOverlay] = useState<Overlay>({ geometry: true, trajectories: true, ids: true, markers: true });
  const [selectedEvent, setSelectedEvent] = useState<number | null>(search.get("event") ? Number(search.get("event")) : null);
  const [filterTrack, setFilterTrack] = useState<number | null>(null);
  const [resizeTick, setResizeTick] = useState(0);
  const [current, setCurrent] = useState<Recording | null>(null); // recording in the player (live runs)
  const [notRecorded, setNotRecorded] = useState<number | null>(null); // a moment asked for that has no video
  const pendingSeek = useRef<{ t: number; play: boolean } | null>(null);
  useEffect(() => {
    const onResize = () => setResizeTick((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  const isFile = !!(camera.data?.source_type === "file" && camera.data.video_id);
  const recs = recordings.data ?? [];
  const playable = recs.filter((r) => r.playable);
  const hasVideo = isFile || playable.length > 0;
  const offset = isFile ? 0 : current?.media_start_s ?? 0; // media time of the loaded video's start
  const offsetRef = useRef(0);
  offsetRef.current = offset;
  const fps = isFile ? camera.data?.video?.fps ?? 25 : current?.fps ?? 10;
  const doc: SceneDocument | undefined = scene.data?.document;
  const markers = timeline.data?.markers ?? [];
  // Recognized names are resolved for this viewer only; the markers carry ids.
  const rtoken = useRecognitionAuth((s) => s.token);
  const names = useEntityNames(markers.map((m) => ({ context: m.entity ? { entity: m.entity } : undefined })));
  const showIdentity = !!rtoken && markers.some((m) => !!m.entity);
  const selectedMarker = markers.find((m) => m.id === selectedEvent) ?? null;
  // The timeline spans the video file, or the whole run when the video comes in parts
  const span = isFile ? duration : Math.max(Number(run.data?.stats?.media_time_s ?? 0), ...recs.map((r) => r.media_end_s), ...markers.map((m) => m.t), 1);
  const burnedIn = !isFile && !!current?.overlay; // the recording already shows boxes, numbers and zones
  const recordingAt = (mt: number) => playable.find((r) => mt >= r.media_start_s - 0.05 && mt <= r.media_end_s + 0.05) ?? null;

  const trajectories = useMemo(() => {
    const items = traj.data?.trajectories ?? [];
    return items.map((tr, i) => ({ ...tr, color: TRACK_COLORS[tr.track_id % TRACK_COLORS.length] || TRACK_COLORS[i % TRACK_COLORS.length] }));
  }, [traj.data]);

  // Uploaded video: seek to ?t= once metadata is loaded
  useEffect(() => {
    const v = videoRef.current;
    const t0 = search.get("t");
    if (isFile && v && t0 && duration > 0) {
      v.currentTime = Math.max(0, Number(t0) - 1.5);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [duration]);

  // Recorded video: open the file covering ?t=, the ?event= or else the first one
  useEffect(() => {
    if (isFile || current || playable.length === 0) return;
    const t0 = search.get("t");
    const target = t0 ? Number(t0) : selectedMarker ? selectedMarker.t : null;
    const r = (target !== null ? recordingAt(target) : null) ?? playable[0];
    pendingSeek.current = { t: target !== null && recordingAt(target) ? Math.max(r.media_start_s, target - 1.5) : r.media_start_s, play: false };
    setCurrent(r);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordings.data, isFile, markers.length]);

  // Draw overlay
  useEffect(() => {
    const cv = canvasRef.current;
    const v = videoRef.current;
    if (!cv || !v) return;
    const w = v.clientWidth;
    const h = v.clientHeight;
    if (cv.width !== w || cv.height !== h) {
      cv.width = w;
      cv.height = h;
    }
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    if (burnedIn) return;
    const px = (x: number, y: number) => [x * w, y * h] as const;
    if (doc && overlay.geometry) {
      for (const o of doc.objects) {
        if (!o.visible) continue;
        const col = o.color ?? OBJECT_COLORS[o.type];
        ctx.strokeStyle = col;
        ctx.lineWidth = 2;
        ctx.setLineDash(o.type === "line" ? [6, 4] : []);
        ctx.beginPath();
        o.points.forEach((p, i) => {
          const [x, y] = px(p.x, p.y);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        if (o.type !== "line" && o.type !== "gate") {
          ctx.closePath();
          ctx.fillStyle = `${col}26`;
          ctx.fill();
        }
        ctx.stroke();
        ctx.setLineDash([]);
        const [lx, ly] = px(o.points[0].x, o.points[0].y);
        ctx.font = "11px Segoe UI, sans-serif";
        ctx.fillStyle = "rgba(20,23,22,0.8)";
        const tw = ctx.measureText(o.name).width + 6;
        ctx.fillRect(lx + 4, ly - 16, tw, 14);
        ctx.fillStyle = col;
        ctx.fillText(o.name, lx + 7, ly - 5);
      }
    }
    if (overlay.trajectories) {
      const window = 2.5;
      for (const tr of trajectories) {
        if (filterTrack !== null && tr.track_id !== filterTrack) continue;
        const pts = tr.points.filter((p) => p[0] >= t - window && p[0] <= t + 0.05);
        if (pts.length < 2) continue;
        const highlight = selectedMarker && selectedMarker.track_id === tr.track_id;
        ctx.strokeStyle = tr.color;
        ctx.lineWidth = highlight ? 3 : 1.5;
        ctx.globalAlpha = highlight ? 1 : 0.85;
        ctx.beginPath();
        pts.forEach((p, i) => {
          const [x, y] = px(p[1], p[2]);
          if (i === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        });
        ctx.stroke();
        const last = pts[pts.length - 1];
        const [x, y] = px(last[1], last[2]);
        ctx.fillStyle = tr.color;
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
        if (overlay.ids) {
          ctx.font = "11px Segoe UI, sans-serif";
          ctx.fillStyle = "rgba(20,23,22,0.8)";
          const label = `#${tr.track_id} ${tr.object_class}`;
          ctx.fillRect(x + 6, y - 14, ctx.measureText(label).width + 6, 14);
          ctx.fillStyle = tr.color;
          ctx.fillText(label, x + 9, y - 3);
        }
        ctx.globalAlpha = 1;
      }
    }
  }, [t, doc, overlay, trajectories, selectedMarker, filterTrack, duration, resizeTick, burnedIn]);

  // Keep t in sync while playing
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      if (v) setT(offsetRef.current + v.currentTime);
      raf = requestAnimationFrame(tick);
    };
    if (playing) raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  /** Show the run at media time mt: the uploaded video, or the recording that covers mt. */
  const seek = (mt: number, play = false) => {
    const v = videoRef.current;
    if (isFile) {
      if (!v) return;
      v.currentTime = Math.max(0, Math.min(duration || mt, mt));
      setT(v.currentTime);
      return;
    }
    const r = recordingAt(mt);
    if (!r) {
      setNotRecorded(mt);
      return;
    }
    setNotRecorded(null);
    if (!current || r.id !== current.id) {
      pendingSeek.current = { t: mt, play };
      setCurrent(r);
      return;
    }
    if (v) {
      v.currentTime = Math.max(0, mt - r.media_start_s);
      setT(mt);
      if (play) void v.play();
    }
  };
  const step = (frames: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.pause();
    setPlaying(false);
    seek(offset + v.currentTime + frames / fps);
  };
  const jumpTo = (m: { id: number; t: number; track_id: number }) => {
    setSelectedEvent(m.id);
    setFilterTrack(null);
    const r = isFile ? null : recordingAt(m.t);
    if (!isFile && !r) {
      setNotRecorded(m.t);
      return;
    }
    seek(r ? Math.max(r.media_start_s, m.t - 1.5) : Math.max(0, m.t - 1.5));
  };
  const onLoadedMetadata = (v: HTMLVideoElement) => {
    setDuration(v.duration);
    setResizeTick((n) => n + 1);
    const p = pendingSeek.current;
    if (p && !isFile && current) {
      pendingSeek.current = null;
      v.currentTime = Math.max(0, p.t - current.media_start_s);
      setT(p.t);
      if (p.play) void v.play();
    } else if (!isFile && current) {
      setT(current.media_start_s + v.currentTime);
    }
  };
  const onEnded = () => {
    // Continue with the next file when it follows straight on (the whole run in segments)
    if (isFile || !current) return;
    const next = playable.find((r) => r.id !== current.id && r.media_start_s >= current.media_end_s - 0.5 && r.media_start_s <= current.media_end_s + 1.0);
    if (next) {
      pendingSeek.current = { t: next.media_start_s, play: true };
      setCurrent(next);
    }
  };

  if (run.isError) return <ErrorNotice error={run.error} />;
  if (!run.data) return <div className="hint">Loading…</div>;
  const videoSrc = isFile ? api.videos.fileUrl(camera.data!.video_id!) : current ? api.recordings.fileUrl(current.id) : undefined;
  const totalBytes = recs.reduce((a, r) => a + r.size_bytes, 0);
  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Video review — run #{id}</h1>
          <div className="sub">
            {experiment.data?.name} · {camera.data?.name} · scene v{String(run.data.snapshot?.scene_version ?? "?")}
          </div>
        </div>
        <div className="row">
          <Link className="btn" to={`/analysis/runs/${id}`}>
            Run analysis
          </Link>
        </div>
      </div>
      {!isFile && camera.data && recordings.isSuccess && recs.length === 0 && (
        <Notice tone="warn">
          This run used a live camera ({camera.data.source_type}) and recorded no video, so only the event list and the stored paths are available here. To keep video of future runs, turn on Video recording on the experiment page.
        </Notice>
      )}
      {!isFile && recs.length > 0 && (
        <Notice>
          {recs.length} video {recs.length === 1 ? "file" : "files"} recorded, {bytes(totalBytes)}. Click an event to watch it. The shaded parts of the timeline have video.
          {playable.length < recs.length && " Some files are in a format the browser cannot play: download them below."}
        </Notice>
      )}
      <div className="review">
        <div className="stack">
          <div className="video-stage">
            {hasVideo ? (
              <>
                <video
                  ref={videoRef}
                  src={videoSrc}
                  onLoadedMetadata={(e) => onLoadedMetadata(e.currentTarget)}
                  onLoadedData={() => setResizeTick((n) => n + 1)}
                  onTimeUpdate={(e) => !playing && setT(offset + e.currentTarget.currentTime)}
                  onPlay={() => setPlaying(true)}
                  onPause={() => setPlaying(false)}
                  onEnded={onEnded}
                  onError={() => setDuration(0)}
                  preload="metadata"
                />
                <canvas ref={canvasRef} />
              </>
            ) : (
              <div className="stage-msg" style={{ position: "relative", height: 240 }}>
                No video for this run.
              </div>
            )}
          </div>
          {notRecorded !== null && <Notice tone="warn">No video was recorded at {clock(notRecorded)}. The shaded parts of the timeline have video.</Notice>}
          <div
            className="timeline"
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              if (span > 0) seek(((e.clientX - r.left) / r.width) * span);
            }}
          >
            {isFile && duration > 0 && <div className="played" style={{ width: `${(t / duration) * 100}%` }} />}
            {!isFile && span > 0 && recs.map((r) => <div key={r.id} className="rec-span" style={{ left: `${(r.media_start_s / span) * 100}%`, width: `${Math.max(0.3, ((r.media_end_s - r.media_start_s) / span) * 100)}%` }} title={`Video ${clock(r.media_start_s)}–${clock(r.media_end_s)}`} />)}
            {overlay.markers && span > 0 && markers.map((m) => <div key={m.id} className={`marker ${m.type === "crossing" ? "crossing" : m.type.startsWith("zone") ? "zone" : ""}`} style={{ left: `${(m.t / span) * 100}%` }} title={`${clock(m.t)} ${eventLabel(m.type)} ${m.route ?? m.object ?? ""}`} onClick={(e) => { e.stopPropagation(); jumpTo(m); }} />)}
            {span > 0 && <div className="cursor" style={{ left: `${Math.min(100, (t / span) * 100)}%` }} />}
          </div>
          <div className="toolbar">
            <button className="btn sm" onClick={() => { const v = videoRef.current; if (!v) return; if (v.paused) void v.play(); else v.pause(); }} disabled={!hasVideo}>
              {playing ? "Pause" : "Play"}
            </button>
            <button className="btn sm" onClick={() => step(-1)} disabled={!hasVideo}>
              −1 frame
            </button>
            <button className="btn sm" onClick={() => step(1)} disabled={!hasVideo}>
              +1 frame
            </button>
            <select value={speed} onChange={(e) => { const s = Number(e.target.value); setSpeed(s); if (videoRef.current) videoRef.current.playbackRate = s; }} style={{ width: 90 }}>
              {[0.25, 0.5, 1, 2, 4].map((s) => (
                <option key={s} value={s}>
                  {s}×
                </option>
              ))}
            </select>
            <span className="num small" style={{ width: 130 }}>
              {clock(t)} / {clock(isFile ? duration : span)}
            </span>
            <span className="divider" />
            {burnedIn ? (
              <label className="check">
                <input type="checkbox" checked={overlay.markers} onChange={(e) => setOverlay({ ...overlay, markers: e.target.checked })} />
                Event markers
              </label>
            ) : (
              (
                [
                  ["geometry", "Zones and gates"],
                  ["trajectories", "Trajectories"],
                  ["ids", "Track ids"],
                  ["markers", "Event markers"],
                ] as const
              ).map(([k, label]) => (
                <label key={k} className="check">
                  <input type="checkbox" checked={overlay[k]} onChange={(e) => setOverlay({ ...overlay, [k]: e.target.checked })} />
                  {label}
                </label>
              ))
            )}
            {filterTrack !== null && (
              <button className="btn sm ghost" onClick={() => setFilterTrack(null)}>
                Show all tracks (was #{filterTrack})
              </button>
            )}
          </div>
          <div className="hint">
            {burnedIn
              ? "This video shows the boxes, track numbers, zones and events as the run saw them."
              : "Trajectories are the stored ground-plane samples (about 10 per second); bounding boxes are not stored. Trajectory storage can be turned off in Settings."}
          </div>
          {!isFile && recs.length > 0 && (
            <Panel title={`Recorded video (${recs.length})`} flush actions={<ConfirmButton label="Delete all video of this run" confirm="Delete every video file of this run? Events and results stay." onConfirm={() => removeAll.mutate()} className="btn sm ghost" />}>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Recorded</th>
                      <th className="num">Run time</th>
                      <th className="num">Length</th>
                      <th>Started by</th>
                      <th className="num">Size</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {recs.map((r) => (
                      <tr key={r.id} className={current?.id === r.id ? "selected" : ""}>
                        <td className="muted">{dateTime(r.started_at)}</td>
                        <td className="num">{clock(r.media_start_s)}</td>
                        <td className="num">{seconds(r.duration_s, 1)}</td>
                        <td>
                          {r.kind === "continuous"
                            ? "Whole run"
                            : r.triggers.length
                              ? `${r.kind === "presence" ? "Visit from " : ""}${r.triggers[0].label}${r.triggers[0].track_id ? ` #${r.triggers[0].track_id}` : ""}${r.trigger_count > 1 ? ` and ${r.trigger_count - 1} more` : ""}`
                              : r.kind === "presence"
                                ? "Visit"
                                : "Event"}
                        </td>
                        <td className="num">{bytes(r.size_bytes)}</td>
                        <td className="row" style={{ gap: 4 }}>
                          {r.playable && (
                            <button className="btn sm" onClick={() => seek(r.media_start_s, true)}>
                              Play
                            </button>
                          )}
                          <a className="btn sm" href={api.recordings.fileUrl(r.id, true)}>
                            Download
                          </a>
                          <ConfirmButton label="Delete" confirm="Delete this video file?" onConfirm={() => removeRecording.mutate(r.id)} className="btn sm ghost" />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          )}
        </div>
        <Panel title={`Events (${markers.length})`} flush>
          <div className="table-wrap" style={{ maxHeight: "70vh" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Event</th>
                  <th>Object / route</th>
                  <th className="num">Track</th>
                  {showIdentity && <th>Identity</th>}
                </tr>
              </thead>
              <tbody>
                {markers.map((m) => (
                  <tr key={m.id} className={`clickable ${selectedEvent === m.id ? "selected" : ""}`} onClick={() => jumpTo(m)} title={!isFile && recs.length > 0 && !recordingAt(m.t) ? "No video at this moment" : undefined}>
                    <td className="num">
                      {clock(m.t)}
                      {!isFile && recs.length > 0 && recordingAt(m.t) && <span className="rec-dot" title="Video recorded" />}
                    </td>
                    <td>{eventLabel(m.type)}</td>
                    <td>{m.route ? <Pill tone={["UNKNOWN", "ABANDONED", "LOST_TRACK"].includes(m.route) ? "warn" : "accent"}>{m.route}</Pill> : m.object ?? "–"}</td>
                    <td className="num">
                      <a href="#" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setFilterTrack(m.track_id); }}>
                        #{m.track_id}
                      </a>
                    </td>
                    {showIdentity && (
                      <td>
                        {(() => {
                          const label = entityLabel(m.entity ? { entity: m.entity } : undefined, names.data);
                          if (!label || (!label.known && !label.possible)) return <span className="muted">–</span>;
                          return <Pill tone={label.possible ? "warn" : "accent"}>{label.possible ? "? " : ""}{label.text}</Pill>;
                        })()}
                      </td>
                    )}
                  </tr>
                ))}
                {markers.length === 0 && (
                  <tr>
                    <td colSpan={showIdentity ? 5 : 4} className="empty">
                      No events in this run.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
