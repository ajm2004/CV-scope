import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { api } from "../api/client";
import type { AnomalyRecord, ResolvedNames } from "../api/types";
import { ConfirmButton, Empty, ErrorNotice, Field, KV, Notice, Panel, Pill } from "../components/ui";
import { anomalyText, KIND_LABEL, STATUS_LABEL, tidy, useAnomalyNames, VALIDATION_LABEL } from "../lib/anomaly";
import { dateTime, seconds } from "../lib/format";

const STATUS_TONE: Record<string, "" | "ok" | "warn" | "err" | "accent"> = { raised: "err", awaiting_model: "accent", dismissed: "", held: "warn" };
const VERDICT_TONE: Record<string, "" | "ok" | "warn" | "err" | "accent"> = { confirmed: "err", rejected: "ok", uncertain: "warn" };
const END_REASON: Record<string, string> = {
  cleared: "back to normal",
  accepted: "accepted as the new normal",
  run_ended: "the run ended",
  view_changed: "the whole picture changed",
  rebaselined: "normal picture learned again",
  instant: "a single moment",
};
const PICTURES: [string, string][] = [
  ["before", "Normal (before)"],
  ["overlay", "Event, change outlined"],
  ["crop_before", "Close-up before"],
  ["crop_event", "Close-up at the event"],
  ["overlay_after", "End, change outlined"],
  ["crop_after", "Close-up at the end"],
];

/** Anomalies raised by the Anomaly Assistant, with their evidence and the model's reading. */
export default function AnomaliesPage() {
  const [search, setSearch] = useSearchParams();
  const experiment = search.get("experiment") ? Number(search.get("experiment")) : undefined;
  const run = search.get("run") ? Number(search.get("run")) : undefined;
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const [feedback, setFeedback] = useState("");
  const selected = search.get("id") ? Number(search.get("id")) : null;
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api.experiments.list() });
  const list = useQuery({
    queryKey: ["anomalies", experiment, run, status, kind, feedback],
    queryFn: () => api.anomalies.list({ experiment_id: experiment, run_id: run, status: status || undefined, kind: kind || undefined, feedback: feedback || undefined, limit: 200 }),
    refetchInterval: 5000,
  });
  const names = useAnomalyNames(list.data?.items);
  const item = list.data?.items.find((a) => a.id === selected) ?? null;
  const setParam = (key: string, value: string | number | null | undefined) => {
    const next = new URLSearchParams(search);
    if (value === null || value === undefined || value === "") next.delete(key);
    else next.set(key, String(value));
    setSearch(next, { replace: true });
  };

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Anomalies</h1>
          <div className="sub">Meaningful changes the Anomaly Assistant found, with the pictures it kept. Turn it on per experiment; choose a vision model on the Anomaly Assistant page.</div>
        </div>
        <div className="row">
          <Link className="btn" to="/anomalies/assistant">
            Anomaly Assistant settings
          </Link>
        </div>
      </div>
      <Panel>
        <div className="row wrap" style={{ gap: 12 }}>
          <Field label="Experiment">
            <select value={experiment ?? ""} onChange={(e) => setParam("experiment", e.target.value)}>
              <option value="">All</option>
              {experiments.data?.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.name}
                </option>
              ))}
            </select>
          </Field>
          {run !== undefined && (
            <Field label="Run">
              <span className="row" style={{ gap: 6 }}>
                #{run}
                <button className="btn sm ghost" onClick={() => setParam("run", null)}>
                  All runs
                </button>
              </span>
            </Field>
          )}
          <Field label="Status">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option>
              {Object.entries(STATUS_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Kind">
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">All</option>
              {Object.entries(KIND_LABEL).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Review">
            <select value={feedback} onChange={(e) => setFeedback(e.target.value)}>
              <option value="">All</option>
              <option value="none">Not reviewed</option>
              <option value="true_positive">Correct</option>
              <option value="false_alarm">False alarm</option>
            </select>
          </Field>
        </div>
      </Panel>
      {list.isError && <ErrorNotice error={list.error} />}
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.15fr)", alignItems: "start" }}>
        <Panel title={`${list.data?.total ?? 0} anomal${list.data?.total === 1 ? "y" : "ies"}`} flush>
          {list.data && list.data.items.length === 0 ? (
            <Empty>
              No anomalies{experiment || status || kind || feedback ? " match these filters" : " yet"}. Turn on the Anomaly Assistant on an <Link to="/experiments">experiment</Link> and start a run.
            </Empty>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Where</th>
                    <th>What</th>
                    <th>Status</th>
                    <th className="num">Lasted</th>
                  </tr>
                </thead>
                <tbody>
                  {list.data?.items.map((a) => (
                    <tr key={a.id} className={`clickable ${a.id === selected ? "selected" : ""}`} onClick={() => setParam("id", a.id)}>
                      <td className="muted nowrap">{dateTime(a.confirmed_at)}</td>
                      <td>
                        {a.zone_name}
                        <div className="hint">{a.camera_name ?? `camera ${a.camera_id}`}</div>
                      </td>
                      <td style={{ maxWidth: 320, whiteSpace: "normal" }}>
                        <strong>{KIND_LABEL[a.kind] ?? a.kind}</strong>
                        <div className="hint">{tidy(anomalyText(a.llm.description || a.summary, a.subjects, names.data))}</div>
                      </td>
                      <td>
                        <Pill tone={STATUS_TONE[a.status] ?? ""}>{STATUS_LABEL[a.status] ?? a.status}</Pill>
                        {a.feedback && <div className="hint">{a.feedback === "false_alarm" ? "False alarm" : "Correct"}</div>}
                      </td>
                      <td className="num muted">{a.duration_s != null ? seconds(a.duration_s, 0) : a.ended_at ? "–" : "ongoing"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        {item ? <AnomalyDetail key={item.id} a={item} names={names.data ?? null} /> : <Panel><Empty>Select an anomaly to see its pictures and details.</Empty></Panel>}
      </div>
    </div>
  );
}

function AnomalyDetail({ a, names }: { a: AnomalyRecord; names: ResolvedNames | null }) {
  const qc = useQueryClient();
  const [note, setNote] = useState(a.note);
  const [rebaseline, setRebaseline] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["anomalies"] });
  const feedback = useMutation({ mutationFn: (fb: "true_positive" | "false_alarm" | null) => api.anomalies.feedback(a.id, { feedback: fb, note, rebaseline: fb === "false_alarm" && rebaseline }), onSuccess: refresh });
  const describe = useMutation({ mutationFn: () => api.anomalies.describe(a.id), onSuccess: refresh });
  const raise = useMutation({ mutationFn: () => api.anomalies.raise(a.id), onSuccess: refresh });
  const remove = useMutation({ mutationFn: () => api.anomalies.remove(a.id), onSuccess: refresh });
  const text = (t: string | null) => tidy(anomalyText(t, a.subjects, names));
  const pictures = PICTURES.filter(([name]) => a.evidence[name]);
  const extra = Object.keys(a.evidence).filter((n) => !PICTURES.some(([p]) => p === n) && !["event", "after"].includes(n));

  return (
    <Panel
      title={
        <span className="row" style={{ gap: 8 }}>
          {KIND_LABEL[a.kind] ?? a.kind} · {a.zone_name}
          <Pill tone={STATUS_TONE[a.status] ?? ""}>{STATUS_LABEL[a.status] ?? a.status}</Pill>
        </span>
      }
      actions={
        <Link className="btn sm" to={`/review/${a.run_id}?t=${Math.max(0, a.confirmed_media_s - 2).toFixed(1)}`}>
          Review the run
        </Link>
      }
    >
      <div className="stack" style={{ gap: 12 }}>
        {a.llm.description && (
          <div>
            <div className="row" style={{ gap: 6, marginBottom: 4 }}>
              <Pill tone={VERDICT_TONE[a.llm.verdict ?? ""] ?? ""}>Model: {a.llm.verdict}</Pill>
              <span className="hint">
                {a.llm.model} · {a.llm.latency_ms != null ? `${(a.llm.latency_ms / 1000).toFixed(1)} s` : ""}
                {a.llm.confidence != null ? ` · confidence ${a.llm.confidence.toFixed(2)}` : ""}
              </span>
            </div>
            <div style={{ fontSize: "var(--fs-3, 1.05rem)" }}>{text(a.llm.description)}</div>
            {a.llm.evidence && <div className="hint">Seen: {a.llm.evidence}</div>}
          </div>
        )}
        <div>
          <div className="hint">Computer vision</div>
          <div>{text(a.summary)}</div>
          {a.expected_state && <div className="hint">Normal state: {a.expected_state}</div>}
        </div>
        {a.llm.status === "failed" || a.llm.status === "skipped" ? (
          <Notice tone="warn">The model did not answer: {a.llm.error}</Notice>
        ) : a.llm.status === "queued" || a.llm.status === "running" ? (
          <Notice>Asking the model…</Notice>
        ) : a.llm.status === "pending_end" ? (
          <Notice>The model describes this event when it ends.</Notice>
        ) : null}
        {a.status === "held" && <Notice tone="warn">Held for review: this area needs the model's confirmation, and the model could not be asked. Raise it if it matters.</Notice>}
        {a.status === "dismissed" && <Notice>The model judged the difference irrelevant, so no alert was raised. Raise it if the model was wrong.</Notice>}
        {pictures.length > 0 ? (
          <div className="grid-2" style={{ gap: 8 }}>
            {pictures.map(([name, label]) => (
              <figure key={name} style={{ margin: 0 }}>
                <a href={a.evidence[name]} target="_blank" rel="noreferrer">
                  <img src={a.evidence[name]} alt={label} style={{ width: "100%", height: 220, objectFit: "contain", background: "var(--stage)", display: "block", borderRadius: 6, border: "1px solid var(--line)" }} loading="lazy" />
                </a>
                <figcaption className="hint">{label}</figcaption>
              </figure>
            ))}
          </div>
        ) : (
          <div className="hint">No pictures were kept for this event.</div>
        )}
        {extra.length > 0 && (
          <div className="hint">
            Also kept:{" "}
            {extra.map((n) => (
              <a key={n} href={a.evidence[n]} target="_blank" rel="noreferrer" style={{ marginRight: 8 }}>
                {n}
              </a>
            ))}
          </div>
        )}
        {a.subjects.length > 0 && (
          <div>
            <div className="hint">Tracked in the area</div>
            <ul className="list-plain">
              {a.subjects.map((s) => (
                <li key={s.alias}>
                  <strong>{s.alias}</strong>: {text(`[${s.alias}]`)} ({s.object_class}, track #{s.track_id}
                  {s.status && s.status !== "unresolved" ? `, recognition: ${s.status.replace("_", " ")}` : ""})
                </li>
              ))}
            </ul>
          </div>
        )}
        <KV
          items={[
            ["Camera", a.camera_name ?? `#${a.camera_id}`],
            ["Started", dateTime(a.started_at)],
            ["Confirmed after", seconds(a.confirmed_media_s - a.started_media_s)],
            ["Ended", a.ended_at ? `${dateTime(a.ended_at)} (${END_REASON[a.end_reason ?? ""] ?? a.end_reason})` : "ongoing"],
            ["Duration", a.duration_s != null ? seconds(a.duration_s, 0) : "–"],
            ["Confidence", a.confidence.toFixed(2)],
            ["Changed area", `${a.area_pct.toFixed(1)}% of the ${a.zone_id === "frame" ? "picture" : "zone"}`],
            ["Vision model", `${VALIDATION_LABEL[a.validation] ?? a.validation}${a.validation === "assisted" ? (a.interpret_at === "end" ? ", at the end" : ", when confirmed") : ""}`],
            ["Run", <Link to={`/analysis/runs/${a.run_id}`}>#{a.run_id}</Link>],
          ]}
        />
        <Field label="Your review" help="Marking false alarms builds a record of how well the settings fit this place.">
          <div className="stack" style={{ gap: 6 }}>
            <textarea rows={2} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <label className="check">
              <input type="checkbox" checked={rebaseline} onChange={(e) => setRebaseline(e.target.checked)} />
              For a false alarm on a running camera: take the current picture of this area as normal
            </label>
            <div className="row wrap" style={{ gap: 6 }}>
              <button className={`btn sm ${a.feedback === "true_positive" ? "primary" : ""}`} onClick={() => feedback.mutate("true_positive")} disabled={feedback.isPending}>
                Correct
              </button>
              <button className={`btn sm ${a.feedback === "false_alarm" ? "primary" : ""}`} onClick={() => feedback.mutate("false_alarm")} disabled={feedback.isPending}>
                False alarm
              </button>
              {a.feedback && (
                <button className="btn sm ghost" onClick={() => feedback.mutate(null)}>
                  Clear
                </button>
              )}
              <span className="grow" />
              <button className="btn sm" onClick={() => describe.mutate()} disabled={describe.isPending} title="Ask the selected vision model now">
                {describe.isPending ? "Asking…" : a.llm.description ? "Describe again" : "Describe with the model"}
              </button>
              {!a.published && (
                <button className="btn sm danger" onClick={() => raise.mutate()} disabled={raise.isPending}>
                  Raise now
                </button>
              )}
              <ConfirmButton label="Delete" confirm="Delete this anomaly and its pictures?" onConfirm={() => remove.mutate()} className="btn sm ghost" />
            </div>
            {feedback.data?.rebaselined && <div className="hint">The running camera now treats this area as normal.</div>}
            {[feedback.error, describe.error, raise.error, remove.error].filter(Boolean).map((e, i) => (
              <ErrorNotice key={i} error={e} />
            ))}
          </div>
        </Field>
      </div>
    </Panel>
  );
}
