/* Time control of a graph: all time, a snapshot at T, a range, or a replay of
 * how the graph grew (stepping through the moments it changed). */

import { useEffect, useRef, useState } from "react";
import type { TimeMode } from "./graphModel";

export type TimeKind = TimeMode["kind"];

function fmt(ms: number, withDate: boolean): string {
  const d = new Date(ms);
  return withDate ? d.toLocaleString() : d.toLocaleTimeString();
}

export function useTimeMode(bounds: [number, number] | null) {
  const [kind, setKind] = useState<TimeKind>("all");
  const [t, setT] = useState<number>(0);
  const [from, setFrom] = useState<number>(0);
  const [to, setTo] = useState<number>(0);
  const [afterglow, setAfterglow] = useState(30);
  const key = bounds ? `${bounds[0]}-${bounds[1]}` : "";
  const last = useRef("");
  useEffect(() => {
    if (!bounds || key === last.current) return;
    last.current = key;
    setT(bounds[1]);
    setFrom(bounds[0]);
    setTo(bounds[1]);
  }, [key, bounds]);
  const mode: TimeMode =
    kind === "snapshot" ? { kind, t, afterglow: afterglow * 1000 } : kind === "range" ? { kind, from: Math.min(from, to), to: Math.max(from, to) } : kind === "evolution" ? { kind, t } : { kind: "all" };
  return { kind, setKind, t, setT, from, setFrom, to, setTo, afterglow, setAfterglow, mode };
}

export default function TimeBar({ bounds, steps, state, caption }: { bounds: [number, number] | null; steps: number[]; state: ReturnType<typeof useTimeMode>; caption?: React.ReactNode }) {
  const [playing, setPlaying] = useState(false);
  const { kind, setKind, t, setT, from, setFrom, to, setTo, afterglow, setAfterglow } = state;
  const multiDay = bounds ? bounds[1] - bounds[0] > 20 * 3600 * 1000 : false;

  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => {
      const next = steps.find((s) => s > t);
      if (next == null) {
        setPlaying(false);
        return;
      }
      setT(next);
    }, 900);
    return () => clearInterval(id);
  }, [playing, steps, t, setT]);

  if (!bounds) return <div className="g-timebar"><span className="hint">No timed relationships in this graph.</span></div>;
  const [b0, b1] = bounds;
  const step = (dir: 1 | -1) => {
    const next = dir > 0 ? steps.find((s) => s > t) : [...steps].reverse().find((s) => s < t);
    if (next != null) setT(next);
  };
  return (
    <div className="g-timebar">
      <select value={kind} onChange={(e) => { setKind(e.target.value as TimeKind); setPlaying(false); if (e.target.value === "evolution") setT(b0); }} aria-label="Time mode">
        <option value="all">All time</option>
        <option value="snapshot">Snapshot at time T</option>
        <option value="range">Time range</option>
        <option value="evolution">Replay (how it grew)</option>
      </select>
      <span className="row" style={{ gap: 4 }}>
        {(kind === "snapshot" || kind === "evolution") && (
          <>
            <button className="btn sm" onClick={() => step(-1)} title="Previous change" aria-label="Previous change">
              ◀
            </button>
            <button className="btn sm" onClick={() => { if (!playing && t >= b1) setT(b0); setPlaying(!playing); }} title={playing ? "Pause" : "Play through the changes"}>
              {playing ? "Pause" : "Play"}
            </button>
            <button className="btn sm" onClick={() => step(1)} title="Next change" aria-label="Next change">
              ▶
            </button>
          </>
        )}
      </span>
      <div className="stack" style={{ gap: 2 }}>
        {kind === "all" && <span className="hint">{fmt(b0, true)} – {fmt(b1, multiDay)} · {steps.length} moments of change</span>}
        {(kind === "snapshot" || kind === "evolution") && (
          <>
            <input type="range" min={b0} max={b1} step={1000} value={Math.min(Math.max(t, b0), b1)} onChange={(e) => setT(Number(e.target.value))} aria-label="Time" />
            <div className="g-caption">
              <strong>{fmt(t, multiDay)}</strong> {caption}
            </div>
          </>
        )}
        {kind === "range" && (
          <>
            <div className="row" style={{ gap: 6 }}>
              <input type="range" min={b0} max={b1} step={1000} value={from} onChange={(e) => setFrom(Number(e.target.value))} aria-label="From" />
              <input type="range" min={b0} max={b1} step={1000} value={to} onChange={(e) => setTo(Number(e.target.value))} aria-label="To" />
            </div>
            <div className="g-caption">
              {fmt(Math.min(from, to), multiDay)} – {fmt(Math.max(from, to), multiDay)}
            </div>
          </>
        )}
      </div>
      {kind === "snapshot" ? (
        <label className="row hint" style={{ gap: 4 }} title="Instant relationships (entered, crossed...) stay visible this long after they happened">
          keep
          <input type="number" min={0} max={3600} value={afterglow} onChange={(e) => setAfterglow(Math.max(0, Number(e.target.value)))} style={{ width: 60 }} />s
        </label>
      ) : (
        <span />
      )}
    </div>
  );
}
