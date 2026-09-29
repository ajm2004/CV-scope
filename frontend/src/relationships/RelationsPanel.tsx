/* Relationships of an experiment: which rules (and versions) its runs use,
 * the built-in identity and place relationships, and the patterns whose
 * deviations are reported. */

import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import type { SceneObject } from "../api/types";
import { ANY_SUBJECT } from "../api/types";
import { ClassPicker, Field, Notice, Panel, Pill } from "../components/ui";
import { CLASS_OPTIONS } from "../lib/format";
import { useRecognitionAuth } from "../lib/recognitionToken";
import SubjectClause, { type RecognitionContext } from "../rule-builder/SubjectClause";
import { DEFAULT_RELATIONS, rel, type Expectation, type RelationExperimentSettings } from "./api";

export { DEFAULT_RELATIONS };

function newExpectation(): Expectation {
  return { id: `exp_${Math.random().toString(16).slice(2, 10)}`, name: "", enabled: true, subject: { classes: ["car", "truck"], subject: { ...ANY_SUBJECT } }, relation: "ENTERED", allowed_places: [], forbidden_places: [] };
}

export function RelationsPanel({ value, onChange, sceneObjects, recognition }: { value: RelationExperimentSettings; onChange: (v: RelationExperimentSettings) => void; sceneObjects: SceneObject[]; recognition?: RecognitionContext }) {
  const token = useRecognitionAuth((s) => s.token);
  const rules = useQuery({ queryKey: ["relationship-rules", false, token], queryFn: () => rel.rules(false), staleTime: 15_000 });
  const set = (patch: Partial<RelationExperimentSettings>) => onChange({ ...value, ...patch });
  const places = sceneObjects.filter((o) => o.type !== "ignore");
  const used = (key: string) => value.rules.find((r) => r.key === key);
  const missing = value.rules.filter((r) => rules.data && !rules.data.some((x) => x.key === r.key));
  const setExp = (i: number, patch: Partial<Expectation>) => set({ expectations: value.expectations.map((x, j) => (j === i ? { ...x, ...patch } : x)) });

  return (
    <Panel title="Relationships" actions={value.enabled ? <Pill tone="accent">{value.rules.length} rule{value.rules.length === 1 ? "" : "s"}</Pill> : undefined}>
      <div className="stack" style={{ gap: 10 }}>
        <label className="check">
          <input type="checkbox" checked={value.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          Connect tracks, identities and places into relationships during runs
        </label>
        {!value.enabled && (
          <div className="hint">
            Forms time-bounded, confidence-scored relationships such as “Person track #3 APPROACHED Vehicle track #9” or “Vehicle ENTERED Parking 2”, correlates them into higher-level events and reports deviations from expected patterns. See the{" "}
            <Link to="/relationships">Relationships</Link> pages.
          </div>
        )}
        {value.enabled && (
          <>
            <Field label="Built in (no rules needed)">
              <div className="stack" style={{ gap: 4 }}>
                <label className="check">
                  <input type="checkbox" checked={value.places} onChange={(e) => set({ places: e.target.checked })} />
                  Places: ENTERED, EXITED, CROSSED, USED_ROUTE, REMAINED_IN, MOVED_FROM / MOVED_TO
                </label>
                <label className="check">
                  <input type="checkbox" checked={value.identity} onChange={(e) => set({ identity: e.target.checked })} />
                  Identities: track IDENTIFIED_AS recognized person, IDENTIFIED_BY_PLATE, REGISTERED_AS (licensed recognition modules)
                </label>
                {value.places && (
                  <span className="row wrap" style={{ gap: 6, marginLeft: 22 }}>
                    <span className="small muted">REMAINED_IN after</span>
                    <input type="number" min={0} value={value.remained_min_s} onChange={(e) => set({ remained_min_s: Number(e.target.value) || 0 })} style={{ width: 70 }} />
                    <span className="small muted">s · MOVED_TO when the next place is reached within</span>
                    <input type="number" min={1} value={value.transition_s} onChange={(e) => set({ transition_s: Number(e.target.value) || 30 })} style={{ width: 70 }} />
                    <span className="small muted">s</span>
                    <label className="check">
                      <input type="checkbox" checked={value.occupied} onChange={(e) => set({ occupied: e.target.checked })} />
                      also OCCUPIED for every visit
                    </label>
                  </span>
                )}
              </div>
            </Field>
            <Field label="Rules" help={<>Rules come from the <Link to="/relationships/rules">rule library</Link>. “Latest” picks up new versions from the next run; pin a version to keep an experiment comparable.</>}>
              <div className="stack" style={{ gap: 4 }}>
                {rules.data?.map((r) => {
                  const u = used(r.key);
                  return (
                    <div key={r.key} className="row wrap" style={{ gap: 6 }}>
                      <label className="check">
                        <input type="checkbox" checked={!!u} onChange={(e) => set({ rules: e.target.checked ? [...value.rules, { key: r.key, version: null }] : value.rules.filter((x) => x.key !== r.key) })} />
                        {r.name || r.key}
                      </label>
                      {u && (
                        <select value={u.version ?? ""} onChange={(e) => set({ rules: value.rules.map((x) => (x.key === r.key ? { ...x, version: e.target.value ? Number(e.target.value) : null } : x)) })} style={{ width: 140 }}>
                          <option value="">latest (v{r.version})</option>
                          {Array.from({ length: r.version }, (_, i) => r.version - i).map((v) => (
                            <option key={v} value={v}>
                              pinned v{v}
                            </option>
                          ))}
                        </select>
                      )}
                      <span className="hint">{r.summary}</span>
                    </div>
                  );
                })}
                {rules.data && rules.data.length === 0 && <span className="hint">The library is empty. Create rules on the Rules page (templates cover the common cases).</span>}
                {missing.length > 0 && <Notice tone="warn">Rules no longer in the library (archived or removed): {missing.map((m) => m.key).join(", ")}.</Notice>}
              </div>
            </Field>
            <Field label="Measure spatial conditions every" help="Seconds between distance measurements (0.2 s = 5 per second).">
              <input type="number" min={0.05} max={2} step={0.05} value={value.sample_s} onChange={(e) => set({ sample_s: Number(e.target.value) || 0.2 })} style={{ width: 90 }} />
            </Field>
            <Field label="Patterns" help="Deviations describe what was observed, never intent.">
              <div className="stack" style={{ gap: 4 }}>
                <label className="check">
                  <input type="checkbox" checked={value.learn_patterns} onChange={(e) => set({ learn_patterns: e.target.checked })} />
                  Report when a recognized person or vehicle uses a place, or is observed with a partner, it rarely or never did in earlier sessions
                </label>
                {value.learn_patterns && (
                  <span className="row wrap" style={{ gap: 6, marginLeft: 22 }}>
                    <span className="small muted">after at least</span>
                    <input type="number" min={2} value={value.pattern_min_sessions} onChange={(e) => set({ pattern_min_sessions: Number(e.target.value) || 5 })} style={{ width: 60 }} />
                    <span className="small muted">sessions; rare = below</span>
                    <input type="number" min={1} max={99} value={Math.round(value.pattern_rare_share * 100)} onChange={(e) => set({ pattern_rare_share: (Number(e.target.value) || 10) / 100 })} style={{ width: 60 }} />
                    <span className="small muted">% of them</span>
                  </span>
                )}
                <label className="check">
                  <input type="checkbox" checked={value.publish_deviations} onChange={(e) => set({ publish_deviations: e.target.checked })} />
                  Record deviations as run events (live list, webhooks of the run)
                </label>
              </div>
            </Field>
            <Field label="Expectations" help="Where entities of a kind are expected. Anything else is reported as outside the expectation.">
              <div className="stack" style={{ gap: 8 }}>
                {value.expectations.map((x, i) => (
                  <div key={x.id} className="rule">
                    <div className="row wrap" style={{ marginBottom: 6 }}>
                      <input type="text" value={x.name} placeholder="Delivery vehicles stay in Loading" onChange={(e) => setExp(i, { name: e.target.value })} style={{ maxWidth: 280 }} />
                      <label className="check" style={{ marginLeft: "auto" }}>
                        <input type="checkbox" checked={x.enabled} onChange={(e) => setExp(i, { enabled: e.target.checked })} />
                        Enabled
                      </label>
                      <button className="btn sm ghost" onClick={() => set({ expectations: value.expectations.filter((_, j) => j !== i) })}>
                        Delete
                      </button>
                    </div>
                    <div className="clause">
                      <span className="kw">WHO</span>
                      <ClassPicker value={x.subject.classes} onChange={(classes) => setExp(i, { subject: { ...x.subject, classes } })} options={CLASS_OPTIONS} />
                    </div>
                    <SubjectClause classes={x.subject.classes} subject={x.subject.subject} onChange={(subject) => setExp(i, { subject: { ...x.subject, subject } })} ctx={recognition} />
                    <div className="clause">
                      <span className="kw">WHEN IT</span>
                      <select value={x.relation} onChange={(e) => setExp(i, { relation: e.target.value as Expectation["relation"] })} style={{ width: 200 }}>
                        <option value="ENTERED">enters</option>
                        <option value="CROSSED">crosses</option>
                        <option value="PARKED_IN">parks in (needs a parking rule)</option>
                        <option value="REMAINED_IN">remains in</option>
                        <option value="USED_ROUTE">uses route</option>
                      </select>
                    </div>
                    <div className="clause">
                      <span className="kw">EXPECTED ONLY</span>
                      <span className="row wrap" style={{ gap: 6 }}>
                        {places.map((o) => (
                          <label key={o.id} className="check">
                            <input type="checkbox" checked={x.allowed_places.includes(o.id)} onChange={(e) => setExp(i, { allowed_places: e.target.checked ? [...x.allowed_places, o.id] : x.allowed_places.filter((p) => p !== o.id) })} />
                            {o.name || o.id}
                          </label>
                        ))}
                        {places.length === 0 && <span className="hint">Choose a camera with a scene.</span>}
                      </span>
                    </div>
                    <div className="clause">
                      <span className="kw">NOT EXPECTED</span>
                      <span className="row wrap" style={{ gap: 6 }}>
                        {places.map((o) => (
                          <label key={o.id} className="check">
                            <input type="checkbox" checked={x.forbidden_places.includes(o.id)} onChange={(e) => setExp(i, { forbidden_places: e.target.checked ? [...x.forbidden_places, o.id] : x.forbidden_places.filter((p) => p !== o.id) })} />
                            {o.name || o.id}
                          </label>
                        ))}
                      </span>
                    </div>
                  </div>
                ))}
                <div>
                  <button className="btn sm" onClick={() => set({ expectations: [...value.expectations, newExpectation()] })}>
                    Add expectation
                  </button>
                </div>
              </div>
            </Field>
          </>
        )}
      </div>
    </Panel>
  );
}
