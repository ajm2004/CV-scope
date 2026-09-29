import type { Direction, InteractionKind, Rule, RuleStep, SceneObject } from "../api/types";
import { ANY_SUBJECT } from "../api/types";
import { ClassPicker } from "../components/ui";
import { CLASS_OPTIONS, OBJECT_TYPE_LABELS } from "../lib/format";
import RelationClause from "./RelationClause";
import SubjectClause, { type RecognitionContext } from "./SubjectClause";

function newRule(objects: SceneObject[], classes: string[]): Rule {
  const first = objects[0];
  return {
    id: `rule_${Math.random().toString(16).slice(2, 10)}`,
    name: "",
    enabled: true,
    classes,
    subject: { ...ANY_SUBJECT },
    trigger: { kind: first && (first.type === "line" || first.type === "gate") ? "crosses" : "enters", object_id: first?.id ?? "", direction: "both" },
    then: [],
    remains_for_s: null,
    record_as: "",
    actions: [{ kind: "count" }, { kind: "record_event" }],
    timeout_s: null,
  };
}

const KINDS: { id: InteractionKind; label: string; lineOnly?: boolean; zoneOnly?: boolean }[] = [
  { id: "crosses", label: "crosses", lineOnly: true },
  { id: "enters", label: "enters", zoneOnly: true },
  { id: "exits", label: "exits", zoneOnly: true },
];

function kindsFor(o: SceneObject | undefined) {
  if (!o) return KINDS;
  const line = o.type === "line" || o.type === "gate";
  return KINDS.filter((k) => (line ? k.lineOnly : k.zoneOnly));
}

function ObjectSelect({ objects, value, onChange, onHighlight }: { objects: SceneObject[]; value: string; onChange: (id: string) => void; onHighlight?: (ids: string[]) => void }) {
  return (
    <select
      value={value}
      onChange={(e) => {
        onChange(e.target.value);
        onHighlight?.([e.target.value]);
      }}
      onFocus={() => value && onHighlight?.([value])}
      onBlur={() => onHighlight?.([])}
    >
      {value === "" && <option value="">Select…</option>}
      {objects.map((o) => (
        <option key={o.id} value={o.id}>
          {o.name || o.id} ({OBJECT_TYPE_LABELS[o.type]})
        </option>
      ))}
    </select>
  );
}

function StepRow({ step, objects, onChange, onRemove, showWithin, onHighlight }: { step: RuleStep; objects: SceneObject[]; onChange: (s: RuleStep) => void; onRemove: () => void; showWithin: boolean; onHighlight?: (ids: string[]) => void }) {
  const obj = objects.find((o) => o.id === step.object_id);
  const kinds = kindsFor(obj);
  return (
    <div className="row wrap">
      <select value={step.kind} onChange={(e) => onChange({ ...step, kind: e.target.value as InteractionKind })} style={{ width: 90 }}>
        {kinds.map((k) => (
          <option key={k.id} value={k.id}>
            {k.label}
          </option>
        ))}
      </select>
      <ObjectSelect
        objects={objects}
        onHighlight={onHighlight}
        value={step.object_id}
        onChange={(id) => {
          const o = objects.find((x) => x.id === id);
          const k = kindsFor(o);
          onChange({ ...step, object_id: id, kind: k.some((x) => x.id === step.kind) ? step.kind : k[0].id });
        }}
      />
      {step.kind === "crosses" && (
        <select value={step.direction} onChange={(e) => onChange({ ...step, direction: e.target.value as Direction })} style={{ width: 100 }}>
          <option value="both">any direction</option>
          <option value="forward">forward</option>
          <option value="reverse">reverse</option>
        </select>
      )}
      {showWithin && (
        <span className="row">
          <span className="small muted">within</span>
          <input type="number" min="1" step="1" value={step.within_s ?? ""} placeholder="∞" onChange={(e) => onChange({ ...step, within_s: e.target.value ? Number(e.target.value) : null })} style={{ width: 70 }} />
          <span className="small muted">s</span>
        </span>
      )}
      <button className="btn sm ghost" onClick={onRemove}>
        Remove
      </button>
    </div>
  );
}

export default function RuleBuilder({ rules, objects, classes, onChange, recognition, relationsEnabled = false, onHighlight }: {
  rules: Rule[];
  objects: SceneObject[];
  classes: string[];
  onChange: (rules: Rule[]) => void;
  recognition?: RecognitionContext;
  relationsEnabled?: boolean;
  /** the scene objects a rule refers to, while it is pointed at (shown on the camera view) */
  onHighlight?: (ids: string[]) => void;
}) {
  const usable = objects.filter((o) => o.type !== "ignore");
  const update = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const remove = (i: number) => onChange(rules.filter((_, j) => j !== i));
  return (
    <div>
      {rules.length === 0 && <div className="hint" style={{ marginBottom: 8 }}>No rules yet. Rules describe multi-step observations in plain terms, for example “when a person crosses the entrance, then crosses gate A within 20 s, record as Route A”.</div>}
      {rules.map((r, i) => {
        const trig = usable.find((o) => o.id === r.trigger.object_id);
        const isDwell = r.remains_for_s !== null;
        const mode = isDwell ? "dwell" : r.then.length > 0 ? "sequence" : "single";
        return (
          <div className="rule" key={r.id} onMouseEnter={() => onHighlight?.([r.trigger.object_id, ...r.then.map((s) => s.object_id)].filter(Boolean))} onMouseLeave={() => onHighlight?.([])}>
            <div className="row" style={{ marginBottom: 6 }}>
              <input type="text" value={r.name} placeholder="Rule name (optional)" onChange={(e) => update(i, { name: e.target.value })} style={{ maxWidth: 240 }} />
              <select
                value={mode}
                onChange={(e) => {
                  const m = e.target.value;
                  if (m === "dwell") update(i, { remains_for_s: 60, then: [], trigger: { ...r.trigger, kind: "enters", object_id: usable.find((o) => o.type === "zone" || o.type === "checkpoint")?.id ?? r.trigger.object_id } });
                  else if (m === "sequence") update(i, { remains_for_s: null, then: r.then.length ? r.then : [{ kind: "crosses", object_id: usable[0]?.id ?? "", direction: "both", within_s: 20 }] });
                  else update(i, { remains_for_s: null, then: [] });
                }}
                style={{ width: 200 }}
              >
                <option value="single">Single trigger</option>
                <option value="sequence">Sequence (then…)</option>
                <option value="dwell">Remains in zone for…</option>
              </select>
              <label className="check" style={{ marginLeft: "auto" }}>
                <input type="checkbox" checked={r.enabled} onChange={(e) => update(i, { enabled: e.target.checked })} />
                Enabled
              </label>
              <button className="btn sm ghost" onClick={() => remove(i)}>
                Delete
              </button>
            </div>
            <div className="clause">
              <span className="kw">WHEN</span>
              <ClassPicker value={r.classes} onChange={(v) => update(i, { classes: v })} options={CLASS_OPTIONS.filter((c) => classes.length === 0 || classes.includes(c.id))} />
            </div>
            <SubjectClause classes={r.classes} subject={r.subject} onChange={(subject) => update(i, { subject })} ctx={recognition} />
            <RelationClause rule={r} onChange={(relation) => update(i, { relation })} ctx={recognition} enabled={relationsEnabled} />
            <div className="clause">
              <span className="kw">{r.trigger.kind.toUpperCase()}</span>
              <StepRow step={{ ...r.trigger, within_s: null }} objects={isDwell ? usable.filter((o) => o.type === "zone" || o.type === "checkpoint") : usable} onChange={(s) => update(i, { trigger: { kind: s.kind, object_id: s.object_id, direction: s.direction } })} onRemove={() => {}} showWithin={false} onHighlight={onHighlight} />
            </div>
            {mode === "sequence" &&
              r.then.map((st, k) => (
                <div className="clause" key={k}>
                  <span className="kw">THEN {st.kind.toUpperCase()}</span>
                  <StepRow step={st} objects={usable} onChange={(s) => update(i, { then: r.then.map((x, j) => (j === k ? s : x)) })} onRemove={() => update(i, { then: r.then.filter((_, j) => j !== k) })} showWithin onHighlight={onHighlight} />
                </div>
              ))}
            {mode === "sequence" && (
              <div className="clause">
                <span />
                <div>
                  <button className="btn sm" onClick={() => update(i, { then: [...r.then, { kind: "crosses", object_id: usable[0]?.id ?? "", direction: "both", within_s: 20 }] })}>
                    Add step
                  </button>
                </div>
              </div>
            )}
            {mode === "dwell" && (
              <div className="clause">
                <span className="kw">AND REMAINS FOR</span>
                <span className="row">
                  <span className="small muted">more than</span>
                  <input type="number" min="1" value={r.remains_for_s ?? 60} onChange={(e) => update(i, { remains_for_s: Number(e.target.value) })} style={{ width: 80 }} />
                  <span className="small muted">seconds</span>
                </span>
              </div>
            )}
            <div className="clause">
              <span className="kw">{mode === "sequence" ? "RECORD AS" : mode === "dwell" ? "CREATE EVENT" : "COUNT AS"}</span>
              <input type="text" value={r.record_as} placeholder={mode === "sequence" ? "Route A / Left turn" : mode === "dwell" ? "Long wait" : trig ? `${trig.name} crossing` : "label"} onChange={(e) => update(i, { record_as: e.target.value })} style={{ maxWidth: 260 }} />
            </div>
            <div className="clause">
              <span className="kw">ACTIONS</span>
              <span className="row wrap">
                <label className="check">
                  <input type="checkbox" checked={r.actions.some((a) => a.kind === "count")} onChange={(e) => update(i, { actions: e.target.checked ? [...r.actions, { kind: "count" }] : r.actions.filter((a) => a.kind !== "count") })} />
                  Count
                </label>
                <label className="check">
                  <input type="checkbox" checked={r.actions.some((a) => a.kind === "record_event")} onChange={(e) => update(i, { actions: e.target.checked ? [...r.actions, { kind: "record_event" }] : r.actions.filter((a) => a.kind !== "record_event") })} />
                  Record event
                </label>
                <label className="check">
                  <input type="checkbox" checked={r.actions.some((a) => a.kind === "webhook")} onChange={(e) => update(i, { actions: e.target.checked ? [...r.actions, { kind: "webhook", url: "" }] : r.actions.filter((a) => a.kind !== "webhook") })} />
                  Send webhook
                </label>
                {r.actions.some((a) => a.kind === "webhook") && (
                  <input type="url" placeholder="https://example.org/hook" value={r.actions.find((a) => a.kind === "webhook")?.url ?? ""} onChange={(e) => update(i, { actions: r.actions.map((a) => (a.kind === "webhook" ? { ...a, url: e.target.value } : a)) })} style={{ maxWidth: 260 }} />
                )}
              </span>
            </div>
            {mode === "sequence" && (
              <div className="clause">
                <span className="kw">OVERALL TIMEOUT</span>
                <span className="row">
                  <input type="number" min="1" value={r.timeout_s ?? ""} placeholder="none" onChange={(e) => update(i, { timeout_s: e.target.value ? Number(e.target.value) : null })} style={{ width: 80 }} />
                  <span className="small muted">seconds from the first step</span>
                </span>
              </div>
            )}
          </div>
        );
      })}
      <button className="btn sm" onClick={() => onChange([...rules, newRule(usable, classes)])} disabled={usable.length === 0}>
        Add rule
      </button>
      {usable.length === 0 && <span className="hint" style={{ marginLeft: 8 }}>Draw lines or zones in the scene first.</span>}
    </div>
  );
}
