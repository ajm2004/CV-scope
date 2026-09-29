/* Relationship rule library: every change is stored as a new version; past
 * relationships keep pointing to the version that created them. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ConfirmButton, Empty, ErrorNotice, Field, Notice, Panel, Pill } from "../components/ui";
import { dateTime } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import { rel, type RuleDefinition, type RuleKind } from "./api";
import { useMeta } from "./bits";
import RuleEditor, { blankRule, KIND_LABEL } from "./RuleEditor";
import "./relationships.css";

export default function RulesPage() {
  const [search, setSearch] = useSearchParams();
  const key = search.get("key");
  const qc = useQueryClient();
  const meta = useMeta();
  const token = useRecognitionAuth((s) => s.token);
  const [archived, setArchived] = useState(false);
  const rules = useQuery({ queryKey: ["relationship-rules", archived, token], queryFn: () => rel.rules(archived) });
  const detail = useQuery({ queryKey: ["relationship-rule", key, token], queryFn: () => rel.rule(key!), enabled: !!key && key !== "new" });
  const [draft, setDraft] = useState<RuleDefinition | null>(null);
  const [note, setNote] = useState("");
  const canEdit = meta.data?.viewer.can.rules ?? false;

  useEffect(() => {
    if (key === "new") return;
    if (detail.data) setDraft(detail.data.latest.definition);
    else if (!key) setDraft(null);
    setNote("");
  }, [key, detail.data]);

  const choose = (k: string | null) => {
    const next = new URLSearchParams(search);
    if (k) next.set("key", k);
    else next.delete("key");
    setSearch(next);
  };
  const startNew = (d: RuleDefinition) => {
    setDraft(d);
    setNote("");
    choose("new");
  };
  const save = useMutation({
    mutationFn: () => (key === "new" ? rel.createRule(draft!, note) : rel.saveRule(key!, draft!, note)),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["relationship-rules"] });
      qc.invalidateQueries({ queryKey: ["relationship-rule", r.key] });
      choose(r.key);
    },
  });
  const archive = useMutation({
    mutationFn: (a: boolean) => rel.archiveRule(key!, a),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["relationship-rules"] });
      qc.invalidateQueries({ queryKey: ["relationship-rule", key] });
    },
  });
  const latest = detail.data?.latest;
  const changed = key === "new" || (latest && draft && JSON.stringify(draft) !== JSON.stringify(latest.definition));

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1>Relationship rules</h1>
          <div className="sub">
            Rules turn measurements into relationships: distance, time, movement, places and sequences. Editing a rule stores a new version; relationships already formed keep the version that formed them. Use rules in an experiment (Relationships panel).
          </div>
        </div>
        <div className="row wrap">
          <select
            value=""
            onChange={(e) => {
              const t = meta.data?.templates.find((x) => x.id === e.target.value);
              if (t) startNew(structuredClone(t.definition));
            }}
            disabled={!canEdit}
          >
            <option value="">New rule from a template…</option>
            {meta.data?.templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.title}
              </option>
            ))}
          </select>
          <select
            value=""
            onChange={(e) => e.target.value && startNew(blankRule(e.target.value as RuleKind))}
            disabled={!canEdit}
          >
            <option value="">New blank rule…</option>
            {(Object.keys(KIND_LABEL) as RuleKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </select>
        </div>
      </div>
      {!canEdit && meta.data && <Notice>Your access does not allow changing rules (Relationship settings › rules role).</Notice>}
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(260px, 0.8fr) minmax(0, 2fr)", alignItems: "start" }}>
        <Panel
          title="Library"
          flush
          actions={
            <label className="check small">
              <input type="checkbox" checked={archived} onChange={(e) => setArchived(e.target.checked)} />
              show archived
            </label>
          }
        >
          {rules.isError && <ErrorNotice error={rules.error} />}
          {rules.data && rules.data.length === 0 && <Empty>No rules yet. Start from a template above.</Empty>}
          <ul className="rel-entity-list" style={{ maxHeight: "70vh" }}>
            {rules.data?.map((r) => (
              <li key={r.key} className={r.key === key ? "selected" : ""}>
                <button onClick={() => choose(r.key)}>
                  <span>
                    <strong>{r.name || r.key}</strong> <span className="hint">v{r.version}</span>
                    {r.archived && <Pill>archived</Pill>}
                  </span>
                  <span className="hint">{r.summary}</span>
                  <span className="hint">{r.used_by && r.used_by.length ? `used by ${r.used_by.map((u) => u.name).join(", ")}` : "not used by an experiment"}</span>
                </button>
              </li>
            ))}
          </ul>
        </Panel>
        <div className="stack">
          {!draft && <Panel><Empty>Choose a rule, or create one from a template.</Empty></Panel>}
          {draft && (
            <Panel
              title={key === "new" ? "New rule" : `${latest?.name ?? ""} · version ${latest?.version ?? ""}`}
              actions={
                key !== "new" && latest && canEdit ? (
                  latest.archived ? (
                    <button className="btn sm" onClick={() => archive.mutate(false)}>
                      Restore
                    </button>
                  ) : (
                    <ConfirmButton label="Archive" confirm="Archive this rule?" onConfirm={() => archive.mutate(true)} className="btn sm ghost" />
                  )
                ) : undefined
              }
            >
              <fieldset disabled={!canEdit} style={{ border: 0, padding: 0, margin: 0 }}>
                <RuleEditor value={draft} onChange={setDraft} />
              </fieldset>
              {canEdit && (
                <div className="row wrap" style={{ marginTop: 12, gap: 8 }}>
                  <Field label={key === "new" ? "Note" : "What changed (stored with the version)"}>
                    <input type="text" value={note} onChange={(e) => setNote(e.target.value)} placeholder={key === "new" ? "optional" : "distance 2 m → 1.5 m"} style={{ minWidth: 320 }} />
                  </Field>
                  <button className="btn primary" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
                    {key === "new" ? "Create rule" : `Save as version ${(latest?.version ?? 0) + 1}`}
                  </button>
                  {key !== "new" && changed && (
                    <button className="btn ghost" onClick={() => latest && setDraft(latest.definition)}>
                      Discard changes
                    </button>
                  )}
                </div>
              )}
              {save.isError && <ErrorNotice error={save.error} />}
            </Panel>
          )}
          {latest && detail.data && (
            <Panel title="Versions" flush>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Version</th>
                      <th>Saved</th>
                      <th>By</th>
                      <th>Note</th>
                      <th>Rule</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.data.versions.map((v) => (
                      <tr key={v.version}>
                        <td className="num">v{v.version}</td>
                        <td className="muted nowrap">{dateTime(v.created_at)}</td>
                        <td className="muted">{v.created_by || "—"}</td>
                        <td>{v.note}</td>
                        <td className="small">{v.summary}</td>
                        <td>
                          {v.version !== latest.version && canEdit && (
                            <button className="btn sm ghost" onClick={() => setDraft(v.definition)} title="Load this version into the editor; saving stores it as a new version">
                              Load
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {latest.used_by && latest.used_by.length > 0 && (
                <div className="hint" style={{ padding: 10 }}>
                  Used by{" "}
                  {latest.used_by.map((u, i) => (
                    <span key={u.experiment_id}>
                      {i > 0 && ", "}
                      <Link to={`/experiments/${u.experiment_id}`}>{u.name}</Link> ({u.version ? `pinned to v${u.version}` : "latest version"}
                      {u.enabled ? "" : ", relationships off"})
                    </span>
                  ))}
                  . Experiments on “latest” use a new version from their next run; runs already made keep theirs. To apply it to past runs, analyse them again from the run's analysis page.
                </div>
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
