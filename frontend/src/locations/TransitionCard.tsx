/* Provenance of one cross-camera transition: where from and to, the time it
 * took against the expected travel time, the identity and topology evidence,
 * sensors on the way, and the resulting confidence. A likely transition is
 * shown as likely: never as a fact. */

import { Link } from "react-router";
import { Pill } from "../components/ui";
import { dateTime, seconds } from "../lib/format";
import { ComponentBars, EntityLink, mediaClock, StatePill, VideoLink } from "../relationships/bits";
import { BASIS_LABEL, FLAG_LABEL, type Transition } from "./api";

const TOPO: Record<string, string> = {
  direct: "Directly connected cameras",
  overlap: "Overlapping views",
  path: "Connected through the location model",
  unconnected: "No connection in the location model",
  no_topology: "Cameras not placed in the location model",
};
const SOURCE: Record<string, string> = { link: "configured on the link", path: "sum of the links on the way", distance: "estimated from plan distances", partial: "partly configured", unknown: "no travel time configured" };

export function range(min: number | null, max: number | null): string {
  if (min == null && max == null) return "unknown";
  return max != null ? `${seconds(min ?? 0, 0)}–${seconds(max, 0)}` : `at least ${seconds(min ?? 0, 0)}`;
}

export default function TransitionCard({ t, onEvidence, compact = false }: { t: Transition; onEvidence?: (relationshipId: number) => void; compact?: boolean }) {
  const place = (x: Transition["from"]) => (
    <>
      <strong>{x.camera.name}</strong>
      {x.node && <span> / {x.node.name}</span>}
      {x.camera.node && <div className="hint">{x.camera.node.path}</div>}
    </>
  );
  return (
    <div className="stack" style={{ gap: 8 }}>
      <div className="row wrap" style={{ justifyContent: "space-between", gap: 6 }}>
        <span>
          <span className="section-title">Cross-camera transition</span> {t.subject && <EntityLink e={t.subject} showType />}
        </span>
        <StatePill state={t.state} confidence={t.confidence} />
      </div>
      <dl className="prov-grid">
        <dt>From</dt>
        <dd>
          {place(t.from)}
          <div className="hint">
            last seen {dateTime(t.left_at)} {t.from.run_id && <> · run #{t.from.run_id}{t.from.media_s != null && ` at ${mediaClock(t.from.media_s)}`}</>}
          </div>
        </dd>
        <dt>To</dt>
        <dd>
          {place(t.to)}
          <div className="hint">
            first seen {dateTime(t.arrived_at)} {t.to.run_id && <> · run #{t.to.run_id}{t.to.media_s != null && ` at ${mediaClock(t.to.media_s)}`}</>}
          </div>
        </dd>
        <dt>Time</dt>
        <dd>
          <strong>{t.gap_s >= 0 ? seconds(t.gap_s, 0) : `${seconds(-t.gap_s, 0)} overlap`}</strong>
        </dd>
        <dt>Expected</dt>
        <dd>
          {range(t.expected.min_s, t.expected.max_s)} <span className="hint">({SOURCE[t.expected.source] ?? t.expected.source})</span>
        </dd>
        <dt>Linked by</dt>
        <dd>
          {t.components.identity_method === "annotation" ? "Manual annotation (a reviewer identified both sightings)" : BASIS_LABEL[t.basis] ?? t.basis}
          {t.identity_confidence != null && <> · identity confidence <strong>{t.identity_confidence.toFixed(2)}</strong></>}
        </dd>
        <dt>Topology</dt>
        <dd>
          {TOPO[t.topology.kind] ?? t.topology.kind}
          {t.topology.path.length > 2 && <div className="hint">{t.topology.path.map((n) => n.name).join(" → ")}</div>}
        </dd>
        {t.sensors.length > 0 && (
          <>
            <dt>Sensors</dt>
            <dd>
              {t.sensors.map((s) => `${s.node} (${s.kind})`).join(", ")}
            </dd>
          </>
        )}
        <dt>Correlation</dt>
        <dd>
          <strong>{t.state_label}</strong> · {Math.round(t.confidence * 100)}%
        </dd>
      </dl>
      {t.flags.length > 0 && (
        <div className="row wrap" style={{ gap: 4 }}>
          {t.flags.map((f) => (
            <Pill key={f} tone={f === "slower_than_expected" || f === "faster_than_expected" ? "warn" : "err"}>
              {FLAG_LABEL[f] ?? f}
            </Pill>
          ))}
        </div>
      )}
      {!compact && <ComponentBars c={t.components} />}
      {!compact && <div className="small">{t.reason}</div>}
      {t.status === "withdrawn" && <Pill tone="warn">withdrawn</Pill>}
      <div className="row wrap" style={{ gap: 4 }}>
        {t.relationships.moved_to && onEvidence && (
          <button className="btn sm ghost" onClick={() => onEvidence(t.relationships.moved_to!)}>
            Supporting observations
          </button>
        )}
        <VideoLink runId={t.from.run_id} t={t.from.media_s} label={`From ${t.from.media_s != null ? mediaClock(t.from.media_s) : ""}`} />
        <VideoLink runId={t.to.run_id} t={t.to.media_s} label={`To ${t.to.media_s != null ? mediaClock(t.to.media_s) : ""}`} />
        {t.to.run_id && <Link className="btn sm ghost" to={`/analysis/runs/${t.to.run_id}`}>Run #{t.to.run_id}</Link>}
      </div>
    </div>
  );
}
