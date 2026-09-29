/* Why a relationship (or a correlated event) exists: the rule version that
 * formed it, the measured values, the calibration, the confidence components
 * and the observations and relationships it rests on. */

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { ErrorNotice, KV, Panel, Pill } from "../components/ui";
import { dateTime, seconds } from "../lib/format";
import { rel, type CorrelatedDetail, type ObservationOut, type RelationshipDetail, type RelationshipOut } from "./api";
import { ComponentBars, EntityLink, mediaClock, relDuration, StatePill, VideoLink } from "./bits";

export type EvidenceRef = { kind: "relationship" | "correlated"; id: number };

const METRIC_LABEL: Record<string, string> = {
  min_distance: "Closest",
  mean_distance: "Mean distance",
  max_distance: "Farthest",
  threshold: "Rule distance",
  duration_s: "Held for",
  valid_samples: "Samples meeting the condition",
  samples: "Samples measured",
  mean_lag_s: "Mean lag behind",
  from_distance: "Distance at the start",
  to_distance: "Distance at the end",
  subject_share: "Share moved by the subject",
  distance: "Distance",
  gap_s: "Gap",
  dwell_s: "Stay",
  direction: "Direction",
  status: "Recognition status",
  steps: "Steps",
  window_s: "Within",
  expected_min_s: "Expected at least",
  expected_max_s: "Expected at most",
  expected_source: "Expected time from",
  topology: "Topology",
  hops: "Links on the way",
  flags: "Flags",
};

// identifiers kept for tracing, not measurements
const HIDDEN_METRICS = new Set(["anchor_track", "transition_uid", "node_id", "camera_id", "from_camera_id", "to_camera_id", "from_track", "to_track", "track", "relationship_id", "usual_entity_id", "partner_entity_id"]);

function metricValue(k: string, v: unknown, unit: string): string {
  if (typeof v === "number") {
    if (k.endsWith("distance") || k === "threshold" || k === "distance") return `${v.toFixed(2)} ${unit === "fw" ? "frame widths" : unit}`;
    if (k.endsWith("_s")) return seconds(v, 1);
    if (k === "subject_share") return `${Math.round(v * 100)}%`;
    return String(v);
  }
  if (Array.isArray(v)) return v.join(", ");
  if (typeof v === "boolean") return v ? "yes" : "no";
  return v == null ? "–" : String(v);
}

function ObservationRow({ o }: { o: ObservationOut }) {
  return (
    <li>
      <span className="muted nowrap">{dateTime(o.at)}</span> <EntityLink e={o.entity} /> <strong>{o.label}</strong> {o.object && <EntityLink e={o.object} />}
      {o.source !== "rgb" && <Pill>{o.source}</Pill>}
      {o.type === "sensor" && <span className="hint"> {String(o.value.kind ?? "")} {o.value.value != null ? String(o.value.value) : ""} {String(o.value.unit ?? "")}</span>}
      <VideoLink runId={o.run_id} t={o.media_time_s} label="" />
    </li>
  );
}

function RelationshipRow({ r, onOpen }: { r: RelationshipOut; onOpen?: (ref: EvidenceRef) => void }) {
  return (
    <li>
      <EntityLink e={r.subject} /> <button className="linklike" onClick={() => onOpen?.({ kind: "relationship", id: r.id })}>{r.type}</button> <EntityLink e={r.object} /> <StatePill state={r.state} confidence={r.confidence} />
      <span className="hint"> {dateTime(r.start_at)}</span>
    </li>
  );
}

export default function Evidence({ target, onOpen, onClose }: { target: EvidenceRef; onOpen?: (ref: EvidenceRef) => void; onClose?: () => void }) {
  const q = useQuery<RelationshipDetail | CorrelatedDetail>({
    queryKey: ["relationship-evidence", target.kind, target.id],
    queryFn: () => (target.kind === "relationship" ? rel.relationship(target.id) : rel.correlatedDetail(target.id)),
  });
  const close = onClose ? (
    <button className="btn sm ghost" onClick={onClose}>
      Close
    </button>
  ) : undefined;
  if (q.isError) return <Panel title="Evidence" actions={close}><ErrorNotice error={q.error} /></Panel>;
  if (!q.data) return <Panel title="Evidence" actions={close}><div className="hint">Loading…</div></Panel>;
  if (target.kind === "correlated") {
    const c = q.data as CorrelatedDetail;
    const byUid = new Map<string, string>();
    for (const o of c.evidence.observations) byUid.set(o.uid, `${o.entity?.label ?? ""} ${o.label} ${o.object?.label ?? ""}`.trim());
    for (const r of c.evidence.relationships) byUid.set(r.uid, `${r.subject?.label ?? ""} ${r.type} ${r.object?.label ?? ""}`);
    return (
      <Panel title={c.kind === "deviation" ? "Pattern deviation" : "Correlated event"} actions={close}>
        <div className="stack" style={{ gap: 10 }}>
          <div className="row wrap">
            <h3 style={{ margin: 0 }}>{c.label}</h3>
            <StatePill state={c.state} confidence={c.confidence} />
            <VideoLink runId={c.run_id} t={c.start_media_s} />
          </div>
          <div>{c.description}</div>
          <KV
            items={[
              ["When", `${dateTime(c.start_at)}${c.end_at ? ` – ${dateTime(c.end_at)}` : ""}`],
              ...(c.run_id && c.start_media_s != null ? [["In the run", `run #${c.run_id}, video position ${mediaClock(c.start_media_s)}${c.end_media_s != null && c.end_media_s - c.start_media_s >= 1 ? `–${mediaClock(c.end_media_s)}` : ""}`] as [string, ReactNode]] : []),
              ...Object.entries(c.roles).map(([role, e]) => [role === "A" ? "Role A" : role === "B" ? "Role B" : role[0].toUpperCase() + role.slice(1), <EntityLink key={role} e={e} />] as [string, ReactNode]),
              ["Rule", <span key="r">{c.rule.name} <span className="hint">v{c.rule.version}</span></span>],
              ["Published as a run event", c.published ? "yes" : "no"],
            ]}
          />
          {c.temporal.length > 0 && (
            <div>
              <div className="section-title">Order of the supporting facts</div>
              <ul className="list-plain">
                {c.temporal.map((t, i) => (
                  <li key={i}>
                    <span className="hint">step {t.step}:</span> {byUid.get(t.a) ?? t.a} <strong>{t.relation}</strong> {byUid.get(t.b) ?? t.b} <span className="hint">({seconds(t.gap_s, 1)})</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="section-title">Supporting relationships</div>
          {c.evidence.relationships.length === 0 ? <div className="hint">None.</div> : <ul className="list-plain">{c.evidence.relationships.map((r) => <RelationshipRow key={r.id} r={r} onOpen={onOpen} />)}</ul>}
          <div className="section-title">Supporting observations</div>
          {c.evidence.observations.length === 0 ? <div className="hint">None.</div> : <ul className="list-plain">{c.evidence.observations.map((o) => <ObservationRow key={o.id} o={o} />)}</ul>}
          <div className="hint">The lower-level observations and relationships are kept; this event only links them.</div>
        </div>
      </Panel>
    );
  }
  const r = q.data as RelationshipDetail;
  const unit = r.calibration.unit ?? String(r.metrics.unit ?? "");
  const metrics = Object.entries(r.metrics).filter(([k, v]) => k !== "unit" && k !== "components" && k !== "sensor_notes" && !HIDDEN_METRICS.has(k) && v !== null && (typeof v !== "object" || (Array.isArray(v) && v.length > 0 && v.every((x) => typeof x !== "object"))));
  const scene = r.calibration.measure === "physical";
  const topology = r.calibration.mode === "topology";
  return (
    <Panel title="Why this relationship exists" actions={close}>
      <div className="stack" style={{ gap: 10 }}>
        <div className="row wrap" style={{ gap: 6 }}>
          <EntityLink e={r.subject} showType />
          <strong>{r.label}</strong>
          <EntityLink e={r.object} showType />
        </div>
        <div className="row wrap">
          <StatePill state={r.state} confidence={r.confidence} />
          <Pill>{r.status === "open" ? "still holds" : "ended"}</Pill>
          {r.sources.map((s) => (
            <Pill key={s} tone={s === "rgb" ? "" : "accent"}>
              {s.toUpperCase()}
            </Pill>
          ))}
          <VideoLink runId={r.run_id} t={r.start_media_s} />
        </div>
        <div className="rel-reason">{r.reason}</div>
        {r.rule.key === "crosscam" && r.subject?.key && (
          <div className="hint">
            Correlated across cameras: <Link to={`/relationships/journeys?key=${encodeURIComponent(r.subject.key)}`}>open the journey</Link> for the full provenance of the move.
          </div>
        )}
        <KV
          items={[
            ["When", `${dateTime(r.start_at)}${r.end_at && r.end_at !== r.start_at ? ` – ${dateTime(r.end_at)}` : ""}${relDuration(r) ? ` (${relDuration(r)})` : ""}`],
            ...(r.run_id && r.start_media_s != null ? [["In the run", `run #${r.run_id}, video position ${mediaClock(r.start_media_s)}${r.end_media_s != null && r.end_media_s - r.start_media_s >= 1 ? `–${mediaClock(r.end_media_s)}` : ""}`] as [string, ReactNode]] : []),
            ["Rule", <span key="rule">{r.rule.key.startsWith("builtin.") || r.rule.key === "crosscam" ? r.rule.name : <Link to={`/relationships/rules?key=${encodeURIComponent(r.rule.key)}`}>{r.rule.name}</Link>} <span className="hint">version {r.rule.version}</span></span>],
            ...(r.rule_summary ? [["Rule text", <span key="rs" className="small">{r.rule_summary}</span>] as [string, ReactNode]] : []),
            ...(r.calibration.mode && r.calibration.mode !== "registry"
              ? [["Measured in", <span key="cal">{topology ? "the location model: camera topology and expected travel times (nothing is measured in the image)" : scene ? `metres (${r.calibration.mode === "homography" ? "ground-plane calibration" : "single known distance"})` : "frame widths — the camera is not calibrated, so these are not metres"}{r.calibration.scene_version ? ` · scene v${r.calibration.scene_version}` : ""}{r.calibration.footprint ? ` · vehicles measured by ${r.calibration.footprint}` : ""}</span>] as [string, ReactNode]]
              : []),
            ...(r.analysis ? [["Analysis", `${r.analysis.source === "live" ? "live run" : "re-analysis"} #${r.analysis.id}${r.analysis.current ? " (current)" : " (superseded, kept for history)"}`] as [string, ReactNode]] : []),
          ]}
        />
        {metrics.length > 0 && (
          <div>
            <div className="section-title">Measurements</div>
            <KV items={metrics.map(([k, v]) => [METRIC_LABEL[k] ?? k.replace(/_/g, " "), metricValue(k, v, unit)])} />
          </div>
        )}
        {Array.isArray(r.metrics.sensor_notes) && (r.metrics.sensor_notes as string[]).length > 0 && (
          <div className="hint">Other sensors: {(r.metrics.sensor_notes as string[]).join("; ")}</div>
        )}
        <div>
          <div className="section-title">Confidence</div>
          <ComponentBars c={r.components} />
        </div>
        <div className="section-title">Supporting observations</div>
        {r.evidence.observations.length === 0 ? (
          <div className="hint">{r.metrics.valid_samples ? `Measured over ${String(r.metrics.valid_samples)} position samples (summarised above; position samples are not stored one by one).` : "None linked."}</div>
        ) : (
          <ul className="list-plain">{r.evidence.observations.map((o) => <ObservationRow key={o.id} o={o} />)}</ul>
        )}
        {r.evidence.relationships.length > 0 && (
          <>
            <div className="section-title">Built on</div>
            <ul className="list-plain">{r.evidence.relationships.map((x) => <RelationshipRow key={x.id} r={x} onOpen={onOpen} />)}</ul>
          </>
        )}
        {(r.cited_by.relationships.length > 0 || r.cited_by.correlated.length > 0) && (
          <>
            <div className="section-title">Used by</div>
            <ul className="list-plain">
              {r.cited_by.relationships.map((x) => <RelationshipRow key={x.id} r={x} onOpen={onOpen} />)}
              {r.cited_by.correlated.map((c) => (
                <li key={`c${c.id}`}>
                  <button className="linklike" onClick={() => onOpen?.({ kind: "correlated", id: c.id })}>{c.label}</button> <StatePill state={c.state} confidence={c.confidence} />
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Panel>
  );
}
