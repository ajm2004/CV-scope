import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { SceneDocument } from "../api/types";
import { ErrorNotice, Pill } from "../components/ui";
import { clock, eventLabel, num, OBJECT_COLORS, pct } from "../lib/format";
import { NewExperimentModal } from "../pages/ExperimentsPage";
import Inspector from "./Inspector";
import SceneCanvas from "./SceneCanvas";
import { newId, type Tool, useEditor } from "./store";
import { useCameraPreview } from "./useCameraPreview";
import { useImage, useLiveRun } from "./useLiveRun";

/** Inputs that take no typed text: shortcuts keep working while they have focus. */
const NON_TEXT_INPUTS = new Set(["range", "checkbox", "radio", "button", "submit", "reset", "color", "file"]);

const TOOLS: { id: Tool; label: string; key: string; color?: string }[] = [
  { id: "select", label: "Select", key: "V" },
  { id: "pan", label: "Pan / zoom", key: "H" },
  { id: "line", label: "Line", key: "L", color: OBJECT_COLORS.line },
  { id: "gate", label: "Gate", key: "G", color: OBJECT_COLORS.gate },
  { id: "zone", label: "Zone", key: "Z", color: OBJECT_COLORS.zone },
  { id: "checkpoint", label: "Checkpoint", key: "C", color: OBJECT_COLORS.checkpoint },
  { id: "ignore", label: "Ignore area", key: "I", color: OBJECT_COLORS.ignore },
  { id: "route", label: "Route", key: "R", color: OBJECT_COLORS.route },
  { id: "calibration", label: "Calibration", key: "K", color: OBJECT_COLORS.calibration },
];

function useElementSize<T extends HTMLElement>(): [React.RefObject<T | null>, { w: number; h: number }] {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

export default function SceneBuilderPage() {
  const { cameraId } = useParams();
  const cid = Number(cameraId);
  const [search, setSearch] = useSearchParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const ed = useEditor;
  const doc = useEditor((s) => s.doc);
  const tool = useEditor((s) => s.tool);
  const dirty = useEditor((s) => s.dirty);
  const version = useEditor((s) => s.version);
  const frozen = useEditor((s) => s.frozen);
  const routeDraft = useEditor((s) => s.routeDraft);
  const past = useEditor((s) => s.past);
  const future = useEditor((s) => s.future);

  const camera = useQuery({ queryKey: ["camera", cid], queryFn: () => api.cameras.get(cid), refetchInterval: 5000 });
  const cameras = useQuery({ queryKey: ["cameras", camera.data?.project_id], queryFn: () => api.cameras.list(camera.data!.project_id), enabled: !!camera.data });
  const frameInfo = useQuery({ queryKey: ["frame-info", cid], queryFn: () => api.cameras.frameInfo(cid), retry: 0 });
  const scene = useQuery({ queryKey: ["latest-scene", cid], queryFn: () => api.cameras.latestScene(cid) });
  const experiments = useQuery({ queryKey: ["experiments-cam", cid], queryFn: () => api.experiments.list({ camera_id: cid }), refetchInterval: 5000 });
  const [experimentId, setExperimentId] = useState<number | "">(search.get("experiment") ? Number(search.get("experiment")) : "");
  const [creating, setCreating] = useState(false);
  const [scrub, setScrub] = useState(0);
  const [snapshotT, setSnapshotT] = useState(0);
  const [error, setError] = useState<unknown>(null);
  const [stageRef, stageSize] = useElementSize<HTMLDivElement>();

  // Load the scene into the editor once frame info and scene are known
  useEffect(() => {
    if (!scene.data) return;
    const d: SceneDocument = scene.data.document;
    if (frameInfo.data) {
      d.frame_width = frameInfo.data.width;
      d.frame_height = frameInfo.data.height;
    }
    ed.getState().load(d, { sceneId: scene.data.id, version: scene.data.version, frozen: scene.data.frozen });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scene.data?.id, frameInfo.data?.width]);

  useEffect(() => {
    if (experimentId === "" && experiments.data?.length) setExperimentId(experiments.data[0].id);
  }, [experiments.data, experimentId]);
  useEffect(() => {
    if (experimentId !== "") setSearch({ experiment: String(experimentId) }, { replace: true });
  }, [experimentId, setSearch]);

  const experiment = experiments.data?.find((e) => e.id === experimentId) ?? null;
  const activeRunId = camera.data?.active_run_id ?? null;
  const live = useLiveRun(activeRunId);
  const isLive = activeRunId !== null && !live.finished;
  // Live cameras (USB, RTSP, HTTP) show a continuous preview that can be frozen;
  // video files show a still frame chosen with the slider.
  const sourceKnown = camera.data !== undefined;
  const liveSource = camera.data ? camera.data.source_type !== "file" : false;
  const [frozenImg, setFrozenImg] = useState<HTMLImageElement | null>(null);
  const preview = useCameraPreview(cid, liveSource && !isLive && !frozenImg);
  const snapshotUrl = useMemo(() => (isLive || liveSource || !sourceKnown ? null : api.cameras.snapshotUrl(cid, snapshotT)), [cid, snapshotT, isLive, liveSource, sourceKnown]);
  const fileImage = useImage(snapshotUrl);
  const image = liveSource ? (frozenImg ?? preview.frame?.img ?? null) : fileImage;
  const defaultClasses = experiment?.object_classes ?? ["person"];
  const toggleFreeze = () => {
    if (frozenImg) setFrozenImg(null);
    else if (preview.frame) setFrozenImg(preview.frame.img);
  };
  const freezeRef = useRef<(() => void) | undefined>(undefined);
  freezeRef.current = liveSource && !isLive ? toggleFreeze : undefined;
  useEffect(() => {
    if (isLive) setFrozenImg(null);
  }, [isLive]);
  useEffect(() => {
    if (preview.runActive) qc.invalidateQueries({ queryKey: ["camera", cid] });
  }, [preview.runActive, cid, qc]);

  // Keyboard shortcuts
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Ctrl+S saves the scene from anywhere, also while typing in the inspector.
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (ed.getState().dirty) save.mutate();
        return;
      }
      const t = e.target as HTMLElement | null;
      const typing = !!t && (t.tagName === "TEXTAREA" || t.tagName === "SELECT" || (t.tagName === "INPUT" && !NON_TEXT_INPUTS.has((t as HTMLInputElement).type)));
      if (typing) return;
      const s = ed.getState();
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) s.redo();
        else s.undo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") {
        e.preventDefault();
        s.redo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "d") {
        e.preventDefault();
        if (s.selectedId) s.duplicateObject(s.selectedId);
        return;
      }
      if (e.key === "Delete" || e.key === "Backspace") {
        if (s.selectedId) s.removeObject(s.selectedId);
        else if (s.selectedRouteId) s.removeRoute(s.selectedRouteId);
        return;
      }
      if (e.key === "Escape") {
        s.clearDraft();
        s.clearRouteDraft();
        s.select(null);
        s.setTool("select");
        return;
      }
      if (e.key === "Enter" && s.tool === "route") {
        finishRoute();
        return;
      }
      if (e.key.toLowerCase() === "f" && !e.ctrlKey && !e.metaKey && freezeRef.current) {
        freezeRef.current();
        return;
      }
      const tool = TOOLS.find((x) => x.key.toLowerCase() === e.key.toLowerCase());
      if (tool && !e.ctrlKey && !e.metaKey) s.setTool(tool.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const finishRoute = () => {
    const s = ed.getState();
    if (!s.doc || s.routeDraft.length < 2) return;
    const [start, ...rest] = s.routeDraft;
    const end = rest.pop()!;
    s.addRoute({ id: newId("route"), name: `Route ${String.fromCharCode(65 + s.doc.routes.length)}`, enabled: true, color: null, start, sequence: rest, end, classes: defaultClasses, timeout_s: 60, strict_sequence: true });
    s.clearRouteDraft();
    s.setTool("select");
  };

  const save = useMutation({
    mutationFn: async () => {
      const s = ed.getState();
      if (!s.doc) throw new Error("No scene loaded");
      return api.cameras.saveScene(cid, { document: s.doc });
    },
    onSuccess: (sc) => {
      ed.getState().markSaved({ sceneId: sc.id, version: sc.version, frozen: sc.frozen });
      qc.invalidateQueries({ queryKey: ["latest-scene", cid] });
      qc.invalidateQueries({ queryKey: ["cameras"] });
      setError(null);
    },
    onError: setError,
  });
  const start = useMutation({
    mutationFn: async () => {
      if (!experiment) throw new Error("Select or create an experiment first.");
      if (ed.getState().dirty) {
        const sc = await api.cameras.saveScene(cid, { document: ed.getState().doc! });
        ed.getState().markSaved({ sceneId: sc.id, version: sc.version, frozen: sc.frozen });
      }
      return api.experiments.start(experiment.id);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera", cid] });
      qc.invalidateQueries({ queryKey: ["experiments-cam", cid] });
      qc.invalidateQueries({ queryKey: ["latest-scene", cid] });
      setError(null);
    },
    onError: setError,
  });
  const stop = useMutation({
    mutationFn: () => api.runs.stop(activeRunId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["camera", cid] });
      qc.invalidateQueries({ queryKey: ["experiments-cam", cid] });
    },
    onError: setError,
  });
  const pause = () => live.send(live.status?.state === "paused" ? "resume" : "pause");

  useEffect(() => {
    if (live.finished && activeRunId) {
      qc.invalidateQueries({ queryKey: ["camera", cid] });
      qc.invalidateQueries({ queryKey: ["experiments-cam", cid] });
    }
  }, [live.finished, activeRunId, cid, qc]);

  const runState = isLive ? live.status?.state ?? "starting" : "stopped";
  const duration = frameInfo.data?.duration_s ?? null;
  const importRef = useRef<HTMLInputElement | null>(null);

  const exportJson = () => {
    const d = ed.getState().doc;
    if (!d) return;
    const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `scene_camera${cid}_v${version}.json`;
    a.click();
  };
  const importJson = (file: File) => {
    file.text().then((txt) => {
      try {
        const d = JSON.parse(txt) as SceneDocument;
        const cur = ed.getState().doc;
        if (cur) {
          d.frame_width = cur.frame_width;
          d.frame_height = cur.frame_height;
        }
        ed.getState().commit((doc) => {
          doc.objects = d.objects;
          doc.routes = d.routes;
          doc.calibration = d.calibration ?? null;
        });
      } catch (e) {
        setError(e);
      }
    });
  };

  if (camera.isError) return <div className="main"><ErrorNotice error={camera.error} /></div>;

  return (
    <div className="sb">
      <div className="sb-top">
        <Link to={camera.data ? `/projects/${camera.data.project_id}` : "/projects"} className="btn ghost sm">
          Project
        </Link>
        <select value={cid} onChange={(e) => nav(`/scene/${e.target.value}`)} title="Camera">
          {(cameras.data ?? (camera.data ? [camera.data] : [])).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <select value={experimentId} onChange={(e) => setExperimentId(e.target.value ? Number(e.target.value) : "")} title="Experiment">
          <option value="">No experiment selected</option>
          {experiments.data?.map((e) => (
            <option key={e.id} value={e.id}>
              {e.name}
            </option>
          ))}
        </select>
        <button className="btn sm" onClick={() => setCreating(true)}>
          New experiment
        </button>
        {experiment && (
          <Link className="btn ghost sm" to={`/experiments/${experiment.id}`}>
            Edit experiment
          </Link>
        )}
        <span className="divider" />
        <Pill tone={runState === "running" ? "ok" : runState === "paused" ? "warn" : runState === "starting" ? "accent" : ""} dot={isLive}>
          {runState}
        </Pill>
        {isLive && live.status && (
          <span className="hint num">
            {num(live.status.pipeline_fps, 1)} fps · {live.status.active_tracks} tracked · {clock(live.status.media_time_s)}
            {live.status.progress != null ? ` · ${pct(live.status.progress * 100, 0)}` : ""}
          </span>
        )}
        <span className="grow" />
        {experiment && experiment.scene_config_id != null && scene.data && experiment.scene_config_id !== scene.data.id && !isLive && (
          <Pill tone="warn">
            <span title="The experiment is pinned to another scene version. Choose Latest under Scene version on the experiment page to run what you draw here.">
              {experiment.name} runs a pinned scene version
            </span>
          </Pill>
        )}
        <span className="hint">
          Scene v{version}
          {frozen ? " (used by a run; saving creates a new version)" : ""}
          {dirty ? " · unsaved changes" : ""}
        </span>
        <button className="btn sm" onClick={() => ed.getState().undo()} disabled={past.length === 0} title="Undo (Ctrl+Z)">
          Undo
        </button>
        <button className="btn sm" onClick={() => ed.getState().redo()} disabled={future.length === 0} title="Redo (Ctrl+Y)">
          Redo
        </button>
        <button className="btn sm" onClick={() => save.mutate()} disabled={!dirty || save.isPending}>
          Save
        </button>
        {isLive ? (
          <>
            <button className="btn sm" onClick={pause}>
              {live.status?.state === "paused" ? "Resume" : "Pause"}
            </button>
            <button className="btn sm danger" onClick={() => stop.mutate()} disabled={stop.isPending}>
              Stop
            </button>
          </>
        ) : (
          <button className="btn sm ok" onClick={() => start.mutate()} disabled={!experiment || start.isPending} title={!experiment ? "Select or create an experiment first" : undefined}>
            Start
          </button>
        )}
      </div>

      <div className="sb-tools">
        {TOOLS.map((t) => (
          <button key={t.id} className={`tool ${tool === t.id ? "active" : ""}`} onClick={() => ed.getState().setTool(t.id)} title={`${t.label} (${t.key})`}>
            {t.color ? <span className="swatch" style={{ background: t.color }} /> : <span className="swatch" style={{ background: "transparent", borderColor: "transparent" }} />}
            {t.label}
            <kbd>{t.key}</kbd>
          </button>
        ))}
        <div className="hint" style={{ padding: "8px 6px" }}>
          {tool === "line" || tool === "gate" ? "Click the two ends of the line." : tool === "zone" || tool === "checkpoint" || tool === "ignore" ? "Click each corner; double-click or click the first point to finish. Esc cancels." : tool === "route" ? "Click the start gate, any checkpoints, then the end gate. Press Enter to finish." : tool === "calibration" ? "Click reference points on the ground, then enter their real coordinates in the inspector." : tool === "pan" ? "Drag to pan, wheel to zoom." : "Click to select, drag to move, drag vertices to reshape. Delete removes."}
        </div>
        {tool === "route" && routeDraft.length > 0 && (
          <div style={{ padding: "0 6px" }}>
            <div className="hint">{routeDraft.length} selected</div>
            <button className="btn sm primary" onClick={finishRoute} disabled={routeDraft.length < 2}>
              Finish route
            </button>
          </div>
        )}
        <div style={{ padding: "8px 6px" }} className="stack">
          <button className="btn sm ghost" onClick={exportJson}>
            Export JSON
          </button>
          <button className="btn sm ghost" onClick={() => importRef.current?.click()}>
            Import JSON
          </button>
          <input ref={importRef} type="file" accept="application/json" style={{ display: "none" }} onChange={(e) => e.target.files?.[0] && importJson(e.target.files[0])} />
          <button className="btn sm ghost" onClick={() => ed.getState().setView({ scale: 1, x: 0, y: 0 })}>
            Reset view
          </button>
        </div>
      </div>

      <div className="sb-stage" ref={stageRef}>
        {stageSize.w > 0 && doc && (image || live.frame) && <SceneCanvas width={stageSize.w} height={stageSize.h} image={image} live={isLive ? live.frame : null} defaultClasses={defaultClasses} />}
        {!doc && <div className="stage-msg">Loading scene…</div>}
        {doc && !image && !live.frame && (
          <div className="stage-msg">
            {liveSource && !isLive ? (
              preview.error || preview.status?.state === "error" ? (
                <span>
                  The camera could not be opened: {preview.error ?? preview.status?.error}
                  <br />
                  Close other apps that use the camera (video calls, the Camera app, browser tabs). CV-Scope keeps retrying.
                </span>
              ) : (
                "Connecting to the camera…"
              )
            ) : frameInfo.isError ? (
              <span>Could not read a frame from this camera. {String((frameInfo.error as Error)?.message ?? "")}</span>
            ) : isLive ? (
              "Waiting for the first frame from the worker…"
            ) : (
              "Loading a frame from the camera…"
            )}
          </div>
        )}
        <div className="stage-hud">
          {isLive && <span className="pill live">LIVE</span>}
          {!isLive && liveSource && (frozenImg ? <span className="pill">FROZEN</span> : preview.frame ? <span className="pill live">PREVIEW</span> : null)}
          {!isLive && frameInfo.data && (
            <span className="pill">
              {frameInfo.data.width}×{frameInfo.data.height}
              {liveSource ? (preview.status && !frozenImg && preview.frame ? ` · ${num(preview.status.fps, 0)} fps` : "") : ` · ${clock(snapshotT)}`}
            </span>
          )}
          {error ? <span className="pill" style={{ color: "#ff8f8f" }}>{error instanceof Error ? error.message : String(error)}</span> : null}
        </div>
      </div>

      <div className="sb-inspector">
        <Inspector defaultClasses={defaultClasses} />
      </div>

      <div className="sb-bottom">
        {!isLive && liveSource && (
          <div className="row">
            <button className="btn sm" onClick={toggleFreeze} disabled={!frozenImg && !preview.frame} title="Freeze or resume the live picture (F)">
              {frozenImg ? "Resume live" : "Freeze frame"}
            </button>
            <span className="hint">
              {frozenImg
                ? "Showing a frozen frame. The camera is switched off until you resume."
                : "Live picture from the camera. Draw over it directly, or freeze a moment first. Nothing is recorded until you press Start."}
            </span>
          </div>
        )}
        {!isLive && !liveSource && duration != null && (
          <div className="row">
            <span className="hint" style={{ width: 90 }}>
              Frame at {clock(scrub)}
            </span>
            <input type="range" min={0} max={Math.max(0, duration - 0.1)} step={0.1} value={scrub} onChange={(e) => setScrub(Number(e.target.value))} onMouseUp={() => setSnapshotT(scrub)} onKeyUp={() => setSnapshotT(scrub)} onTouchEnd={() => setSnapshotT(scrub)} />
            <span className="hint" style={{ width: 70, textAlign: "right" }}>
              {clock(duration)}
            </span>
            <span className="hint">Freeze any moment of the recording to draw over it.</span>
          </div>
        )}
        {isLive && live.status && (
          <div className="row" style={{ alignItems: "flex-start", gap: 16 }}>
            {live.status.progress != null && (
              <div className="timeline grow" style={{ height: 8 }}>
                <div className="played" style={{ width: `${live.status.progress * 100}%` }} />
              </div>
            )}
            <div className="row wrap" style={{ gap: 12 }}>
              {(live.status.counters ?? []).filter((c) => c.value > 0 || c.kind === "route").slice(0, 12).map((c) => (
                <span key={c.key} className="small nowrap">
                  {c.label}: <strong className="num">{c.value}</strong>
                </span>
              ))}
              {live.status.timings_ms?.detect != null && <span className="hint nowrap">detect {num(live.status.timings_ms.detect, 1)} ms · track {num(live.status.timings_ms.track, 1)} ms</span>}
            </div>
            <div className="event-feed" style={{ width: 380, maxHeight: 56 }}>
              {live.events.slice(-6).reverse().map((e) => (
                <div key={e.seq}>
                  {clock(e.media_time_s)} {eventLabel(e.event_type)} {e.route ?? e.label ?? ""} #{e.track_id}
                </div>
              ))}
              {live.events.length === 0 && <div className="muted">No events yet.</div>}
            </div>
          </div>
        )}
        {!isLive && experiment?.last_run && experiment.last_run.status !== "running" && (
          <div className="row hint">
            Last run #{experiment.last_run.id} {experiment.last_run.status}.{" "}
            <Link to={`/analysis/runs/${experiment.last_run.id}`}>Results</Link>
            <Link to={`/review/${experiment.last_run.id}`}>{camera.data?.source_type === "file" ? "Review video" : "Review events"}</Link>
          </div>
        )}
      </div>

      {creating && camera.data && (
        <NewExperimentModal
          projectId={camera.data.project_id}
          cameraId={cid}
          onClose={() => setCreating(false)}
          onCreated={(id) => {
            setCreating(false);
            qc.invalidateQueries({ queryKey: ["experiments-cam", cid] });
            setExperimentId(id);
          }}
        />
      )}
    </div>
  );
}
