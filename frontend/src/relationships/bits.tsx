/* Small shared pieces of the relationship pages. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Pill } from "../components/ui";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel, type Components, type EntityOut, type StateName } from "./api";

export const STATE_TONE: Record<string, "" | "ok" | "warn" | "err" | "accent"> = { confirmed: "ok", likely: "accent", possible: "warn", insufficient: "" };
export const STATE_LABEL: Record<string, string> = { confirmed: "Confirmed by rule", likely: "Likely", possible: "Possible", insufficient: "Insufficient evidence" };
export const STATES: StateName[] = ["confirmed", "likely", "possible", "insufficient"];

export function useMeta() {
  const token = useRecognitionAuth((s) => s.token);
  return useQuery({ queryKey: ["relationships-meta", token], queryFn: rel.meta, staleTime: 60_000 });
}

/** Verb phrase of a relationship type ("approached"), from the registry. */
export function useRelationLabels(): (type: string) => string {
  const meta = useMeta();
  return (type: string) => meta.data?.relation_types.find((t) => t.id === type)?.label ?? type.toLowerCase().replace(/_/g, " ");
}

export function StatePill({ state, confidence }: { state: string; confidence?: number | null }) {
  return (
    <Pill tone={STATE_TONE[state] ?? ""}>
      {STATE_LABEL[state] ?? state}
      {confidence != null ? ` · ${Math.round(confidence * 100)}%` : ""}
    </Pill>
  );
}

export function ConfidenceMeter({ value }: { value: number }) {
  return (
    <span className="rel-meter" title={`${Math.round(value * 100)}%`}>
      <span style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }} />
    </span>
  );
}

const COMPONENT_LABEL: Record<string, string> = {
  tracking: "Tracking",
  recognition: "Recognition",
  spatial: "Spatial certainty",
  temporal: "Temporal consistency",
  sensor: "Other sensors",
};

/** The evidence components behind a confidence value. */
export function ComponentBars({ c }: { c: Components }) {
  const rows = Object.entries(COMPONENT_LABEL).filter(([k]) => c[k as keyof Components] != null);
  return (
    <div className="rel-components">
      {rows.map(([k, label]) => {
        const v = Number(c[k as keyof Components]);
        return (
          <div key={k} className="rel-component">
            <span className="muted small">{label}</span>
            <ConfidenceMeter value={v} />
            <span className="num small">{Math.round(v * 100)}%</span>
          </div>
        );
      })}
      {c.support != null && <div className="hint">Supported by {c.support} sample{c.support === 1 ? "" : "s"} / observations.</div>}
    </div>
  );
}

const CATEGORY_ICON: Record<string, string> = { track: "◯", identity: "◆", place: "▭", context: "◇", event: "✦" };

export function entityIcon(e: { category?: string } | null | undefined): string {
  return CATEGORY_ICON[e?.category ?? ""] ?? "·";
}

/** An entity as text, linking to the explorer when it may be opened. */
export function EntityLink({ e, showType = false, withIdentity = true }: { e: EntityOut | null | undefined; showType?: boolean; withIdentity?: boolean }) {
  if (!e) return <span className="muted">?</span>;
  const label = (
    <>
      <span className={`rel-ent rel-ent-${e.category}`} aria-hidden>
        {entityIcon(e)}
      </span>{" "}
      {e.label}
      {showType && !e.redacted && e.label !== e.type_label && <span className="hint"> · {e.type_label}</span>}
    </>
  );
  const ident = withIdentity && e.identity ? (
    <span className="hint">
      {" "}
      → <Link to={`/relationships?key=${encodeURIComponent(e.identity.key)}`}>{e.identity.label}</Link>
    </span>
  ) : null;
  if (e.redacted || !e.key) {
    return (
      <span title="Shown by name only to viewers with recognition access" className="muted">
        {label}
      </span>
    );
  }
  return (
    <span>
      <Link to={`/relationships?key=${encodeURIComponent(e.key)}`}>{label}</Link>
      {ident}
    </span>
  );
}

/** Position in a run's video (media time). */
export function mediaClock(s: number | null | undefined): string {
  if (s == null) return "";
  const t = Math.max(0, s);
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const sec = Math.floor(t % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/** How long a relationship lasted: by the run's own clock when known (video files are analysed faster than real time). */
export function relDuration(r: { start_at: string; end_at: string | null; start_media_s?: number | null; end_media_s?: number | null }): string {
  if (r.start_media_s != null && r.end_media_s != null) return secondsText(r.end_media_s - r.start_media_s);
  return duration(r.start_at, r.end_at);
}

function secondsText(s: number): string {
  if (s < 1) return "";
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

export function duration(from: string | null | undefined, to: string | null | undefined): string {
  if (!from || !to) return "";
  const s = (new Date(to).getTime() - new Date(from).getTime()) / 1000;
  if (s < 1) return "";
  if (s < 90) return `${s.toFixed(0)} s`;
  if (s < 5400) return `${(s / 60).toFixed(1)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

/** Link to the run's video at a media time (the review page says when nothing was recorded). */
export function VideoLink({ runId, t, label = "Video" }: { runId: number | null | undefined; t: number | null | undefined; label?: string }) {
  if (!runId || t == null) return null;
  return (
    <Link className="btn sm ghost" to={`/review/${runId}?t=${Math.max(0, t - 2).toFixed(1)}`} title="Open the run's video a moment before this">
      ▶ {label}
    </Link>
  );
}

export function IdentityNotice({ sees }: { sees: boolean | undefined }) {
  if (sees) return null;
  return (
    <div className="hint">
      Recognized people, plates and registered vehicles are shown as “Recognized person” / “License plate” without a name. Sign in with a recognition access token (Recognition › People) to see identities, if your role allows it.
    </div>
  );
}
