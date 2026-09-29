/* Guided enrollment on a live camera: the person follows one instruction at a
 * time and every view is captured by itself, the way a phone enrolls a face.
 * The ring around the picture shows which views are done. */

import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Camera, EnrollmentResult, RecognitionPerson } from "../api/types";
import { ErrorNotice, Field, Notice, Pill, Progress } from "../components/ui";
import { num } from "../lib/format";
import { useGuidedEnrollment, type GuidedCapture, type GuidedStep } from "./useGuidedEnrollment";

const LIVE_SOURCES = new Set(["usb", "rtsp", "http"]);
// Where each view sits on the ring, in SVG degrees (0 = right, 90 = bottom).
const VIEW_ANGLE: Record<string, number> = { right: 0, above: 90, left: 180, below: 270 };
const DIRECTION_ANGLE: Record<string, number> = { right: 0, down: 90, left: 180, up: 270 };
const SHORT_LABEL: Record<string, string> = { front: "Front", left: "Left", right: "Right", above: "Chin down", below: "Chin up", lighting: "Lighting", rear: "Back of head" };

function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

function arcPath(cx: number, cy: number, r: number, centerDeg: number, spanDeg: number): string {
  const [x0, y0] = polar(cx, cy, r, centerDeg - spanDeg / 2);
  const [x1, y1] = polar(cx, cy, r, centerDeg + spanDeg / 2);
  return `M ${x0.toFixed(2)} ${y0.toFixed(2)} A ${r} ${r} 0 0 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`;
}

function arrowPoints(cx: number, cy: number, r: number, deg: number, size = 8): string {
  // Inside the ring, pointing outwards, so nothing is clipped by the viewBox.
  const tip = polar(cx, cy, r - 1, deg);
  const left = polar(cx, cy, r - size, deg + 7);
  const right = polar(cx, cy, r - size, deg - 7);
  return [tip, left, right].map(([x, y]) => `${x.toFixed(2)},${y.toFixed(2)}`).join(" ");
}

function Ring({ steps, captured, activeView, direction }: { steps: GuidedStep[]; captured: string[]; activeView: string | null; direction: string | null }) {
  const c = 50;
  const r = 46;
  const frontDone = captured.includes("front");
  const arrowAngle = direction && DIRECTION_ANGLE[direction] !== undefined ? DIRECTION_ANGLE[direction] : null;
  return (
    <svg className="guided-ring" viewBox="0 0 100 100" aria-hidden="true">
      <circle className={`front-ring ${frontDone ? "done" : ""} ${activeView === "front" ? "active" : ""}`} cx={c} cy={c} r={r} />
      {steps
        .filter((s) => VIEW_ANGLE[s.view] !== undefined)
        .map((s) => (
          <path
            key={s.view}
            className={`seg ${captured.includes(s.view) ? "done" : ""} ${activeView === s.view ? "active" : ""}`}
            d={arcPath(c, c, r, VIEW_ANGLE[s.view], 54)}
          />
        ))}
      {arrowAngle !== null && <polygon className="arrow" points={arrowPoints(c, c, r, arrowAngle)} />}
    </svg>
  );
}

export default function GuidedEnrollment({ person, cameras, onChanged, look = "" }: { person: RecognitionPerson; cameras: Camera[]; onChanged: (p: RecognitionPerson) => void; look?: string }) {
  const live = cameras.filter((c) => LIVE_SOURCES.has(c.source_type));
  const [cameraId, setCameraId] = useState<number | "">("");
  // The camera list arrives after the first render: take the one used last, else the first.
  useEffect(() => {
    if (cameraId !== "" && live.some((c) => c.id === cameraId)) return;
    const stored = Number(localStorage.getItem("pathscope.enrollmentCamera") ?? "");
    const pick = live.find((c) => c.id === stored) ?? live[0];
    setCameraId(pick ? pick.id : "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live.map((c) => c.id).join(",")]);
  const [running, setRunning] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [extraView, setExtraView] = useState<string | null>(null);
  const [donePlan, setDonePlan] = useState(false);
  const [result, setResult] = useState<EnrollmentResult | null>(null);
  const [flash, setFlash] = useState(0);
  const flashTimer = useRef<number | undefined>(undefined);

  const onCaptured = (c: GuidedCapture) => {
    onChanged(c.person);
    setFlash((n) => n + 1);
    window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => setFlash(0), 600);
  };
  const { ready, frameUrl, analysis, captured, note, error, connected, setTarget } = useGuidedEnrollment(person.id, running && cameraId !== "" ? Number(cameraId) : null, running, onCaptured, look);
  const steps = ready?.plan ?? [];
  const extras = ready?.extras ?? [];
  const finalize = useMutation({
    mutationFn: () => api.recognition.finalize(person.id),
    onSuccess: (r) => {
      setResult(r.result);
      onChanged(r.person);
    },
  });

  // Walk the plan: the first view that is still missing, then the next one after
  // every capture. Views captured in an earlier session are skipped.
  useEffect(() => {
    if (!ready) return;
    const next = steps.findIndex((s) => !captured.includes(s.view));
    if (extraView) return;
    if (next === -1) {
      setDonePlan(true);
      setTarget(null);
      return;
    }
    setStepIndex(next);
    setTarget(steps[next].view);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, captured, extraView]);

  useEffect(
    () => () => {
      window.clearTimeout(flashTimer.current);
    },
    [],
  );

  // Switching to another look starts that look from its first view.
  useEffect(() => {
    setDonePlan(false);
    setExtraView(null);
    setStepIndex(0);
    setResult(null);
  }, [look]);

  const stop = () => {
    setRunning(false);
    setDonePlan(false);
    setExtraView(null);
  };
  const start = () => {
    setResult(null);
    setDonePlan(false);
    setExtraView(null);
    setStepIndex(0);
    if (cameraId !== "") localStorage.setItem("pathscope.enrollmentCamera", String(cameraId));
    setRunning(true);
  };
  const skip = () => {
    const next = steps.findIndex((s, i) => i > stepIndex && !captured.includes(s.view));
    if (next === -1) {
      setDonePlan(true);
      setTarget(null);
    } else {
      setStepIndex(next);
      setTarget(steps[next].view);
    }
  };
  const startExtra = (view: string) => {
    setExtraView(view);
    setDonePlan(false);
    setTarget(view);
  };

  useEffect(() => {
    if (extraView && captured.includes(extraView)) {
      setExtraView(null);
      setDonePlan(true);
      setTarget(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [captured, extraView]);

  if (live.length === 0)
    return (
      <Notice>
        Guided capture needs a live camera. Add a USB webcam or a network camera on the Cameras page, or use single pictures below.
      </Notice>
    );

  const activeView = extraView ?? (donePlan ? null : steps[stepIndex]?.view ?? null);
  const currentStep = [...steps, ...extras].find((s) => s.view === activeView);
  const instruction = error ? "" : analysis?.instruction ?? (connected ? "Starting the camera…" : "Connecting…");
  const holdShare = analysis && analysis.hold_needed > 0 ? Math.min(1, analysis.hold / analysis.hold_needed) : 0;
  const quality = analysis?.quality?.score ?? null;
  const missing = steps.filter((s) => !captured.includes(s.view));

  return (
    <div className="stack">
      <div className="inline-form">
        <Field label="Camera">
          <select value={cameraId} onChange={(e) => setCameraId(e.target.value ? Number(e.target.value) : "")} disabled={running}>
            {live.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </Field>
        {!running ? (
          <button className="btn primary" disabled={cameraId === ""} onClick={start}>
            Start guided capture
          </button>
        ) : (
          <button className="btn" onClick={stop}>
            Stop
          </button>
        )}
        <span className="hint">
          The camera opens only while this runs. Each view is kept the moment the pose and the picture are good enough.
          {look ? ` Capturing the look "${look}"; earlier looks stay as they are.` : ""}
        </span>
      </div>

      {error && <ErrorNotice error={error} />}

      {running && (
        <div className="guided">
          <div className="guided-stage">
            <div className={`guided-circle ${ready?.mirror ? "mirror" : ""}`}>
              {frameUrl ? <img src={frameUrl} alt="Live camera" /> : <span className="hint">Waiting for the camera…</span>}
              <span className={`guided-flash ${flash ? "on" : ""}`} key={flash} />
            </div>
            <Ring steps={steps} captured={captured} activeView={activeView} direction={analysis?.direction ?? null} />
          </div>
          <div className="stack" style={{ gap: 10 }}>
            <div>
              <div className="guided-instruction">{donePlan && !extraView ? "All views captured" : instruction}</div>
              {currentStep && !donePlan && (
                <div className="hint">
                  Step {Math.min(stepIndex + 1, steps.length)} of {steps.length}: {currentStep.label}
                </div>
              )}
            </div>
            {!donePlan && (
              <div style={{ maxWidth: 260 }}>
                <Progress value={holdShare} />
                <span className="hint">{analysis?.ok ? "Hold still…" : "Follow the instruction above"}</span>
              </div>
            )}
            {note && <Notice tone={note.level === "err" ? "err" : "warn"}>{note.message}</Notice>}
            <div className="guided-steps">
              {[...steps, ...extras.filter((e) => captured.includes(e.view) || e.view === extraView)].map((s, i) => (
                <span key={s.view} className={`guided-step ${captured.includes(s.view) ? "done" : ""} ${activeView === s.view ? "active" : ""}`}>
                  {captured.includes(s.view) ? "✓" : `${i + 1}.`} {SHORT_LABEL[s.view] ?? s.label}
                </span>
              ))}
            </div>
            <div className="row wrap">
              {!donePlan && (
                <button className="btn sm" onClick={skip} disabled={currentStep?.required}>
                  Skip this view
                </button>
              )}
              {donePlan &&
                extras.map((e) => (
                  <button key={e.view} className="btn sm" disabled={captured.includes(e.view)} onClick={() => startExtra(e.view)}>
                    Add {SHORT_LABEL[e.view] ?? e.label}
                  </button>
                ))}
              {donePlan && (
                <button className="btn primary sm" disabled={finalize.isPending || captured.length === 0} onClick={() => finalize.mutate()}>
                  Finish and check quality
                </button>
              )}
            </div>
            <div className="hint">
              {analysis?.box
                ? `Face ${num(analysis.quality?.size_px ?? 0, 0)} px · picture quality ${num((quality ?? 0) * 100, 0)}%` +
                  (analysis.rel_yaw != null ? ` · turn ${num(Math.abs(analysis.rel_yaw) < 0.005 ? 0 : analysis.rel_yaw, 2)}` : "") +
                  (analysis.rel_pitch != null ? ` · tilt ${num(Math.abs(analysis.rel_pitch) < 0.005 ? 0 : analysis.rel_pitch, 2)}` : "")
                : "No face in view"}
            </div>
          </div>
        </div>
      )}

      {running && donePlan && missing.length > 0 && (
        <Notice tone="warn">
          Skipped: {missing.map((s) => SHORT_LABEL[s.view] ?? s.label).join(", ")}. More views make recognition more reliable; you can start the guided capture again to add them.
        </Notice>
      )}
      {finalize.isError && <ErrorNotice error={finalize.error} />}
      {result && (
        <Notice tone={result.status === "enrolled" ? "ok" : "warn"}>
          <div className="row wrap">
            <Pill tone={result.status === "enrolled" ? "ok" : "warn"}>{result.status}</Pill>
            <span>
              Quality {num((result.quality ?? 0) * 100, 0)}% · views {result.views.join(", ")} · consistency {result.consistency != null ? num(result.consistency, 2) : "n/a"}
            </span>
          </div>
          {result.problems.length > 0 && result.problems.map((p) => <div key={p}>{p}</div>)}
        </Notice>
      )}
    </div>
  );
}
