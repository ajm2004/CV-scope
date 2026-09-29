/* Chronological view of a run, an experiment, an entity or a time range:
 * observations, relationships and correlated events in order, each linked to
 * its evidence and to the run's video; plus a deterministic summary. */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Fragment, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { api } from "../api/client";
import { Empty, ErrorNotice, Field, Notice, Panel } from "../components/ui";
import { dateTime } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel, tzOffsetMin, type StateName, type TimelineItem } from "./api";
import { EntityLink, IdentityNotice, mediaClock, StatePill, useMeta, VideoLink } from "./bits";
import Evidence, { type EvidenceRef } from "./Evidence";
import "./relationships.css";

function clockOf(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function dayOf(iso: string): string {
  return new Date(iso).toLocaleDateString([], { weekday: "short", year: "numeric", month: "short", day: "numeric" });
}

export default function TimelinePage() {
  const [search, setSearch] = useSearchParams();
  const key = search.get("key");
  const runParam = search.get("run") ? Number(search.get("run")) : undefined;
  const token = useRecognitionAuth((s) => s.token);
  const meta = useMeta();
  const [experiment, setExperiment] = useState<number | undefined>(undefined);
  const [minState, setMinState] = useState<StateName>("possible");
  const [kinds, setKinds] = useState({ observation: true, relationship: true, correlated: true });
  const [hours, setHours] = useState<number | undefined>(undefined);
  const [evidence, setEvidence] = useState<EvidenceRef | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const experiments = useQuery({ queryKey: ["experiments"], queryFn: () => api.experiments.list() });
  const runs = useQuery({ queryKey: ["experiment-runs", experiment], queryFn: () => api.experiments.runs(experiment!), enabled: !!experiment });
  const settings = useQuery({ queryKey: ["relationship-settings", token], queryFn: rel.settings });
  const run = useQuery({ queryKey: ["run", runParam], queryFn: () => api.runs.get(runParam!), enabled: !!runParam });
  // A video file is analysed faster than real time: its own clock is the video position
  const fileRun = String(run.data?.snapshot?.source_type ?? "") === "file";
  const clockKnown = !runParam || run.isFetched;
  const scope = key ? { key } : runParam ? { run_id: runParam } : experiment ? { experiment_id: experiment } : hours ? { last_hours: hours } : null;
  const timeline = useQuery({
    queryKey: ["rel-timeline", scope, minState, token, hours],
    queryFn: () => rel.timeline({ ...scope!, min_state: minState, last_hours: hours }),
    enabled: !!scope,
  });
  const summary = useMutation({
    mutationFn: (llm: boolean) =>
      rel.summary({ key: key ?? undefined, run_id: runParam, experiment_id: key || runParam ? undefined : experiment, time_from: hours ? new Date(Date.now() - hours * 3600_000).toISOString() : undefined, min_state: minState === "possible" ? "likely" : minState, tz_offset_min: tzOffsetMin(), llm }),
  });
  const items = useMemo(() => (timeline.data?.items ?? []).filter((i) => kinds[i.kind]), [timeline.data, kinds]);
  const setRun = (id: number | undefined) => {
    const next = new URLSearchParams(search);
    next.delete("key");
    if (id) next.set("run", String(id));
    else next.delete("run");
    setSearch(next);
  };
  const clearKey = () => {
    const next = new URLSearchParams(search);
    next.delete("key");
    setSearch(next);
  };
  const open = (i: TimelineItem) => {
    setSelected(`${i.kind}:${i.id}`);
    if (i.kind === "relationship") setEvidence({ kind: "relationship", id: i.id });
    else if (i.kind === "correlated") setEvidence({ kind: "correlated", id: i.id });
  };
  let lastDay = "";

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationship timeline</h1>
          <div className="sub">Everything the graph knows, in order. Click a relationship or correlated event for its evidence; ▶ opens the run's video at that moment when video was recorded.</div>
        </div>
      </div>
      <IdentityNotice sees={meta.data?.viewer.sees_identities} />
      <Panel>
        <div className="row wrap" style={{ gap: 12, alignItems: "flex-end" }}>
          {key ? (
            <Field label="Entity">
              <span className="row" style={{ gap: 6 }}>
                <EntityLink e={timeline.data?.entity} showType />
                <button className="btn sm ghost" onClick={clearKey}>
                  Choose a run instead
                </button>
              </span>
            </Field>
          ) : (
            <>
              <Field label="Experiment">
                <select value={experiment ?? ""} onChange={(e) => { setExperiment(e.target.value ? Number(e.target.value) : undefined); setRun(undefined); }}>
                  <option value="">Choose…</option>
                  {experiments.data?.map((x) => (
                    <option key={x.id} value={x.id}>
                      {x.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Run">
                <select value={runParam ?? ""} onChange={(e) => setRun(e.target.value ? Number(e.target.value) : undefined)} disabled={!experiment && !runParam}>
                  <option value="">{experiment ? "All runs of the experiment" : runParam ? `Run #${runParam}` : "—"}</option>
                  {runs.data?.map((r) => (
                    <option key={r.id} value={r.id}>
                      #{r.id} · {dateTime(r.started_at ?? r.created_at)} · {r.status}
                    </option>
                  ))}
                </select>
              </Field>
            </>
          )}
          <Field label="Time">
            <select value={hours ?? ""} onChange={(e) => setHours(e.target.value ? Number(e.target.value) : undefined)}>
              <option value="">{key || runParam || experiment ? "Whole selection" : "Choose…"}</option>
              <option value="1">Last hour</option>
              <option value="24">Last 24 hours</option>
              <option value="168">Last 7 days</option>
            </select>
          </Field>
          <Field label="Relationships at least">
            <select value={minState} onChange={(e) => setMinState(e.target.value as StateName)}>
              <option value="confirmed">Confirmed by rule</option>
              <option value="likely">Likely</option>
              <option value="possible">Possible</option>
              <option value="insufficient">Everything</option>
            </select>
          </Field>
          <Field label="Show">
            <span className="row wrap" style={{ gap: 8 }}>
              {(["observation", "relationship", "correlated"] as const).map((k) => (
                <label key={k} className="check">
                  <input type="checkbox" checked={kinds[k]} onChange={(e) => setKinds({ ...kinds, [k]: e.target.checked })} />
                  {k === "observation" ? "Observations" : k === "relationship" ? "Relationships" : "Correlated events"}
                </label>
              ))}
            </span>
          </Field>
        </div>
      </Panel>
      {!scope && <Notice>Choose an experiment, a run, a time range, or open an entity's timeline from the Relationships explorer.</Notice>}
      {timeline.isError && <ErrorNotice error={timeline.error} />}
      {scope && (
        <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1.3fr) minmax(300px, 1fr)", alignItems: "start" }}>
          <div className="stack">
            <Panel
              title="Summary"
              actions={
                <span className="row">
                  <button className="btn sm" onClick={() => summary.mutate(false)} disabled={summary.isPending}>
                    Summarize
                  </button>
                  {settings.data?.settings.llm_summaries && !key && (
                    <button className="btn sm ghost" onClick={() => summary.mutate(true)} disabled={summary.isPending} title="The model receives the anonymous summary below and nothing else">
                      Reword with language model
                    </button>
                  )}
                </span>
              }
            >
              {summary.isError && <ErrorNotice error={summary.error} />}
              {!summary.data && <div className="hint">A summary written from the stored facts only (likely and confirmed relationships).</div>}
              {summary.data && (
                <div className="stack" style={{ gap: 8 }}>
                  {summary.data.deterministic.sentences.length === 0 && <div className="hint">Nothing to summarize.</div>}
                  <div className="rel-summary">
                    {summary.data.deterministic.sentences.map((s, i) => (
                      <div key={i}>
                        <span className="span">{s.span}</span>
                        {s.text} <VideoLink runId={s.run_id} t={s.media_time_s} label="" />
                      </div>
                    ))}
                  </div>
                  {summary.data.model && (
                    <div className="notice">
                      <div className="section-title">
                        Reworded by {summary.data.model.model} ({summary.data.model.provider}) — from the anonymous facts above only
                      </div>
                      <div className="rel-summary">{summary.data.model.text}</div>
                    </div>
                  )}
                </div>
              )}
            </Panel>
            <Panel title={timeline.data ? `${items.length} item${items.length === 1 ? "" : "s"}` : "Timeline"} flush>
              {timeline.data && items.length === 0 && <Empty>Nothing in this selection.</Empty>}
              <ul className="rel-timeline">
                {clockKnown && items.map((i) => {
                  const day = fileRun ? `Run #${runParam} · positions in the video` : dayOf(i.at);
                  const header = day !== lastDay ? day : null;
                  lastDay = day;
                  const clickable = i.kind !== "observation";
                  return (
                    <Fragment key={`${i.kind}-${i.id}`}>
                      {header && <li className="day">{header}</li>}
                      <li className={`kind-${i.kind} ${clickable ? "clickable" : ""} ${selected === `${i.kind}:${i.id}` ? "selected" : ""}`} onClick={() => clickable && open(i)}>
                        <span className="num muted small" title={fileRun ? dateTime(i.at) : i.media_time_s != null ? `video position ${mediaClock(i.media_time_s)}` : undefined}>
                          {fileRun ? mediaClock(i.media_time_s) : clockOf(i.at)}
                        </span>
                        <span className="dot" />
                        <span>
                          {i.kind === "relationship" && <span className="hint">Relationship · </span>}
                          {i.kind === "correlated" && <strong>{i.type === "deviation" ? "Pattern deviation: " : "Correlated event: "}</strong>}
                          {i.text}
                          {i.kind === "correlated" && i.description && <div className="hint">{i.description}</div>}
                          {i.source && i.source !== "rgb" && i.kind === "observation" && <span className="hint"> ({i.source})</span>}
                        </span>
                        <span className="row" style={{ gap: 4 }} onClick={(e) => e.stopPropagation()}>
                          {i.state && <StatePill state={i.state} confidence={i.confidence} />}
                          <VideoLink runId={i.run_id} t={i.media_time_s} label="" />
                        </span>
                      </li>
                    </Fragment>
                  );
                })}
              </ul>
            </Panel>
          </div>
          <div className="rel-evidence">{evidence ? <Evidence target={evidence} onOpen={setEvidence} onClose={() => setEvidence(null)} /> : <Panel><Empty>Select a relationship or a correlated event.</Empty></Panel>}</div>
        </div>
      )}
    </div>
  );
}
