import { useState } from "react";
import type { Calibration, LineObject, RouteDefinition, SceneObject, ZoneObject } from "../api/types";
import { ClassPicker, Field } from "../components/ui";
import { CLASS_OPTIONS, OBJECT_COLORS, OBJECT_TYPE_LABELS } from "../lib/format";
import { isLine, newId, objectLabel, useEditor } from "./store";

function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div className="section-title row" style={{ justifyContent: "space-between" }}>
        <span>{title}</span>
        {right}
      </div>
      <div className="stack" style={{ gap: 8 }}>
        {children}
      </div>
    </div>
  );
}

function CommonFields({ o }: { o: SceneObject }) {
  const update = useEditor((s) => s.updateObject);
  return (
    <>
      <Field label="Name">
        <input type="text" value={o.name} onChange={(e) => update(o.id, { name: e.target.value })} />
      </Field>
      {o.type === "ignore" ? (
        <div className="hint">Detections of every class whose position lies inside are dropped before tracking.</div>
      ) : (
        <Field label="Object to track" help="Leave all unchecked to apply to every tracked class of the experiment.">
          <ClassPicker value={o.classes} onChange={(v) => update(o.id, { classes: v })} options={CLASS_OPTIONS} />
        </Field>
      )}
      <div className="row wrap">
        <label className="check">
          <input type="checkbox" checked={o.enabled} onChange={(e) => update(o.id, { enabled: e.target.checked })} />
          Enabled
        </label>
        <label className="check">
          <input type="checkbox" checked={o.locked} onChange={(e) => update(o.id, { locked: e.target.checked })} />
          Locked
        </label>
        <label className="check">
          <input type="checkbox" checked={o.visible} onChange={(e) => update(o.id, { visible: e.target.checked })} />
          Visible
        </label>
      </div>
    </>
  );
}

function AdvancedFields({ o }: { o: LineObject | ZoneObject }) {
  const update = useEditor((s) => s.updateObject);
  const [open, setOpen] = useState(false);
  return (
    <Section title="Advanced" right={<button className="btn ghost sm" onClick={() => setOpen(!open)}>{open ? "Hide" : "Show"}</button>}>
      {open && (
        <>
          <Field label="Minimum detection confidence" help="Ignore tracks whose average confidence is below this.">
            <input type="number" step="0.05" min="0" max="1" value={o.min_confidence} onChange={(e) => update(o.id, { min_confidence: Number(e.target.value) })} />
          </Field>
          <Field
            label="Minimum track age (frames)"
            help="How long an object must have been tracked before it can trigger. On a line, only its movement from that age on counts: raise it (to 4, say) where people step into view right next to the line and their box is still growing."
          >
            <input type="number" min="0" value={o.min_track_age} onChange={(e) => update(o.id, { min_track_age: Number(e.target.value) })} />
          </Field>
          {o.type === "line" || o.type === "gate" ? (
            <Field label="Debounce (seconds)" help="Ignore repeated crossings by the same object within this time.">
              <input type="number" step="0.1" min="0" value={o.debounce_s} onChange={(e) => update(o.id, { debounce_s: Number(e.target.value) })} />
            </Field>
          ) : o.type === "checkpoint" ? (
            <ExitAllowanceField o={o} />
          ) : null}
          <Field label="Colour">
            <div className="row">
              <input type="text" value={o.color ?? ""} placeholder={OBJECT_COLORS[o.type]} onChange={(e) => update(o.id, { color: e.target.value || null })} />
              <span className="swatch" style={{ background: o.color ?? OBJECT_COLORS[o.type] }} />
            </div>
          </Field>
          <Field label="Notes">
            <textarea value={o.notes} onChange={(e) => update(o.id, { notes: e.target.value })} />
          </Field>
        </>
      )}
    </Section>
  );
}

/** Zones keep a visit through short exits (stored as the object's debounce time). */
function ExitAllowanceField({ o }: { o: ZoneObject }) {
  const update = useEditor((s) => s.updateObject);
  return (
    <Field
      label="Ignore exits shorter than (seconds)"
      help="An object that leaves and comes back within this time keeps its visit, so someone standing on the edge is not counted again and again."
    >
      <input type="number" step="0.5" min="0" value={o.debounce_s} onChange={(e) => update(o.id, { debounce_s: Number(e.target.value) })} />
    </Field>
  );
}

function LineInspector({ o }: { o: LineObject }) {
  const update = useEditor((s) => s.updateObject);
  const flip = () => update(o.id, { points: [o.points[1], o.points[0]] });
  const toggleAction = (a: "count" | "record", on: boolean) => update(o.id, { actions: on ? [...new Set([...o.actions, a])] : o.actions.filter((x) => x !== a) });
  return (
    <>
      <Section title="General">
        <Field label="Kind">
          <select value={o.type} onChange={(e) => update(o.id, { type: e.target.value as "line" | "gate" })}>
            <option value="line">Counting line</option>
            <option value="gate">Gate (usable as route start / end)</option>
          </select>
        </Field>
        <CommonFields o={o} />
      </Section>
      <Section title="Direction">
        <div className="row wrap">
          {(["both", "forward", "reverse"] as const).map((d) => (
            <label key={d} className="check">
              <input type="radio" name={`dir-${o.id}`} checked={o.direction === d} onChange={() => update(o.id, { direction: d })} />
              {d === "both" ? "Both" : d === "forward" ? "Forward (arrow)" : "Reverse"}
            </label>
          ))}
        </div>
        <div className="row">
          <button className="btn sm" onClick={flip}>
            Flip forward direction
          </button>
          <span className="hint">The solid arrow on the canvas points forward. With Both, the faint arrow points in reverse.</span>
        </div>
      </Section>
      <Section title="When an object crosses">
        <label className="check">
          <input type="checkbox" checked={o.actions.includes("count")} onChange={(e) => toggleAction("count", e.target.checked)} />
          Count the crossing
        </label>
        <label className="check">
          <input type="checkbox" checked={o.actions.includes("record")} onChange={(e) => toggleAction("record", e.target.checked)} />
          Record an event with time, direction and track
        </label>
        <div className="hint">Custom actions (webhooks, labels, sequences) are added as rules in the experiment.</div>
      </Section>
      <Section title="Doorway">
        <label className="check">
          <input type="checkbox" checked={!!o.doorway} onChange={(e) => update(o.id, { doorway: e.target.checked })} />
          The camera cannot see past this line
        </label>
        <div className="hint">
          For a door into a room or the edge of a wall. People walking through are hidden by the door frame before their feet reach the
          line, so a normal line misses them. With this on, someone who walks up to the line and disappears there counts as crossing it,
          and someone who appears there and walks away counts as crossing it the other way. The count comes when the tracker gives the
          person up (a few seconds later) and is dated when they were last seen.
        </div>
      </Section>
      <AdvancedFields o={o} />
    </>
  );
}

function ZoneInspector({ o }: { o: ZoneObject }) {
  const update = useEditor((s) => s.updateObject);
  const toggle = (m: ZoneObject["measures"][number], on: boolean) => update(o.id, { measures: on ? [...new Set([...o.measures, m])] : o.measures.filter((x) => x !== m) });
  return (
    <>
      <Section title="General">
        <Field label="Kind">
          <select value={o.type} onChange={(e) => update(o.id, { type: e.target.value as ZoneObject["type"] })}>
            <option value="zone">Zone (monitored area)</option>
            <option value="checkpoint">Checkpoint (route waypoint)</option>
            <option value="ignore">Ignore region (detections here are dropped)</option>
          </select>
        </Field>
        <CommonFields o={o} />
        {o.type !== "ignore" && (
          <div className="row">
            <button
              className="btn sm"
              disabled={o.locked}
              onClick={() => update(o.id, { points: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }, { x: 0, y: 1 }] })}
            >
              Cover the whole image
            </button>
            <span className="hint">The zone then covers everything the camera sees.</span>
          </div>
        )}
      </Section>
      {o.type === "zone" && (
        <Section title="Measure">
          {(
            [
              ["entry", "Entries (count and record when an object enters)"],
              ["exit", "Exits (record when it leaves, with time spent)"],
              ["occupancy", "Occupancy (how many objects are inside)"],
              ["dwell", "Dwell time (how long objects stay)"],
            ] as const
          ).map(([m, label]) => (
            <label key={m} className="check">
              <input type="checkbox" checked={o.measures.includes(m)} onChange={(e) => toggle(m, e.target.checked)} />
              {label}
            </label>
          ))}
          <Field label="Ignore visits shorter than (seconds)" help="Shorter visits are not counted, such as someone walking past.">
            <input type="number" step="0.5" min="0" value={o.min_dwell_s} onChange={(e) => update(o.id, { min_dwell_s: Number(e.target.value) })} />
          </Field>
          <ExitAllowanceField o={o} />
          <Field label="Flag visits longer than (seconds)" help="Creates a dwell-exceeded event. Leave empty to disable.">
            <input type="number" step="1" min="0" value={o.max_dwell_s ?? ""} onChange={(e) => update(o.id, { max_dwell_s: e.target.value ? Number(e.target.value) : null })} />
          </Field>
          <Field label="Flag occupancy above" help="Creates an occupancy-exceeded event. Leave empty to disable.">
            <input type="number" step="1" min="0" value={o.max_objects ?? ""} onChange={(e) => update(o.id, { max_objects: e.target.value ? Number(e.target.value) : null })} />
          </Field>
        </Section>
      )}
      {o.type === "checkpoint" && <div className="hint">A checkpoint is passed when an object enters it. Use it as a waypoint inside a route.</div>}
      {o.type !== "ignore" && <AdvancedFields o={o} />}
    </>
  );
}

function RouteInspector({ r }: { r: RouteDefinition }) {
  const doc = useEditor((s) => s.doc)!;
  const update = useEditor((s) => s.updateRoute);
  const remove = useEditor((s) => s.removeRoute);
  const candidates = doc.objects.filter((o) => o.type !== "ignore");
  const opt = (o: SceneObject) => (
    <option key={o.id} value={o.id}>
      {objectLabel(o)} ({OBJECT_TYPE_LABELS[o.type]})
    </option>
  );
  const setSeq = (seq: string[]) => update(r.id, { sequence: seq });
  return (
    <>
      <Section title="Route">
        <Field label="Name">
          <input type="text" value={r.name} onChange={(e) => update(r.id, { name: e.target.value })} />
        </Field>
        <Field label="Starts when the object passes">
          <select value={r.start} onChange={(e) => update(r.id, { start: e.target.value })}>
            {candidates.map(opt)}
          </select>
        </Field>
        <Field label="Then passes, in order">
          <div className="stack" style={{ gap: 4 }}>
            {r.sequence.map((id, i) => (
              <div key={i} className="row">
                <select value={id} onChange={(e) => setSeq(r.sequence.map((s, j) => (j === i ? e.target.value : s)))}>
                  {candidates.map(opt)}
                </select>
                <button className="btn sm ghost" disabled={i === 0} onClick={() => { const s = [...r.sequence]; [s[i - 1], s[i]] = [s[i], s[i - 1]]; setSeq(s); }} title="Move up">↑</button>
                <button className="btn sm ghost" disabled={i === r.sequence.length - 1} onClick={() => { const s = [...r.sequence]; [s[i + 1], s[i]] = [s[i], s[i + 1]]; setSeq(s); }} title="Move down">↓</button>
                <button className="btn sm ghost" onClick={() => setSeq(r.sequence.filter((_, j) => j !== i))}>Remove</button>
              </div>
            ))}
            <div>
              <button className="btn sm" onClick={() => setSeq([...r.sequence, candidates.find((c) => c.id !== r.start && c.id !== r.end)?.id ?? candidates[0].id])} disabled={candidates.length === 0}>
                Add checkpoint
              </button>
            </div>
          </div>
        </Field>
        <Field label="Completes when the object passes">
          <select value={r.end} onChange={(e) => update(r.id, { end: e.target.value })}>
            {candidates.map(opt)}
          </select>
        </Field>
        <Field label="Object to track">
          <ClassPicker value={r.classes} onChange={(v) => update(r.id, { classes: v })} options={CLASS_OPTIONS} />
        </Field>
        <Field label="Give up after (seconds)" help="Objects that have not completed any route by then are recorded as Abandoned.">
          <input type="number" min="1" value={r.timeout_s} onChange={(e) => update(r.id, { timeout_s: Number(e.target.value) })} />
        </Field>
        <label className="check">
          <input type="checkbox" checked={r.strict_sequence} onChange={(e) => update(r.id, { strict_sequence: e.target.checked })} />
          Require every checkpoint. Reaching the end without them is then recorded as Unknown; unticked, the route still counts and notes the missed checkpoints.
        </label>
        <label className="check">
          <input type="checkbox" checked={r.enabled} onChange={(e) => update(r.id, { enabled: e.target.checked })} />
          Enabled
        </label>
        <div>
          <button className="btn sm danger" onClick={() => remove(r.id)}>
            Delete route
          </button>
        </div>
      </Section>
      <div className="hint">Routes that share the same start form one study: each object that starts is recorded as exactly one of the routes, Unknown, Abandoned or Lost track.</div>
    </>
  );
}

function CalibrationInspector() {
  const doc = useEditor((s) => s.doc)!;
  const setCal = useEditor((s) => s.setCalibration);
  const cal: Calibration = doc.calibration ?? { unit: "m", points: [], known_distance: null, notes: "" };
  const mode = cal.points.length >= 4 ? "homography" : cal.known_distance ? "scale" : "none";
  const lines = doc.objects.filter(isLine);
  return (
    <Section title="Calibration (optional)">
      <div className="hint">
        {mode === "homography" && "Perspective calibration active: distances and speeds are in real units."}
        {mode === "scale" && "Scale-only calibration: a single known distance gives approximate real units (valid for near-overhead views)."}
        {mode === "none" && "No calibration: distances and speeds are reported in frame units (fraction of the frame per second)."}
      </div>
      <Field label="Unit">
        <input type="text" value={cal.unit} onChange={(e) => setCal({ ...cal, unit: e.target.value })} style={{ maxWidth: 80 }} />
      </Field>
      <Field label="Reference points (click on the canvas with the Calibration tool; then enter ground coordinates)" help="Four or more points on one flat ground plane give a full perspective mapping.">
        {cal.points.length === 0 ? (
          <div className="hint">No points yet.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Image (x, y)</th>
                <th>Ground X</th>
                <th>Ground Y</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {cal.points.map((p, i) => (
                <tr key={i}>
                  <td>{i + 1}</td>
                  <td className="mono small">
                    {p.image.x.toFixed(3)}, {p.image.y.toFixed(3)}
                  </td>
                  <td>
                    <input type="number" step="0.1" value={p.ground_x} onChange={(e) => setCal({ ...cal, points: cal.points.map((q, j) => (j === i ? { ...q, ground_x: Number(e.target.value) } : q)) })} style={{ width: 70 }} />
                  </td>
                  <td>
                    <input type="number" step="0.1" value={p.ground_y} onChange={(e) => setCal({ ...cal, points: cal.points.map((q, j) => (j === i ? { ...q, ground_y: Number(e.target.value) } : q)) })} style={{ width: 70 }} />
                  </td>
                  <td>
                    <button className="btn sm ghost" onClick={() => setCal({ ...cal, points: cal.points.filter((_, j) => j !== i) })}>
                      Remove
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Field>
      <Field label="Known distance" help="Pick a drawn line whose real length you know.">
        <div className="row">
          <select
            value={cal.known_distance ? lines.find((l) => l.points[0].x === cal.known_distance!.a.x && l.points[0].y === cal.known_distance!.a.y)?.id ?? "custom" : ""}
            onChange={(e) => {
              const l = lines.find((x) => x.id === e.target.value);
              setCal({ ...cal, known_distance: l ? { a: l.points[0], b: l.points[1], distance: cal.known_distance?.distance ?? 5 } : null });
            }}
          >
            <option value="">none</option>
            {lines.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
            {cal.known_distance && <option value="custom">custom</option>}
          </select>
          <input type="number" step="0.1" min="0.01" disabled={!cal.known_distance} value={cal.known_distance?.distance ?? ""} onChange={(e) => cal.known_distance && setCal({ ...cal, known_distance: { ...cal.known_distance, distance: Number(e.target.value) } })} style={{ width: 90 }} />
          <span className="small muted">{cal.unit}</span>
        </div>
      </Field>
      {(cal.points.length > 0 || cal.known_distance) && (
        <div>
          <button className="btn sm ghost" onClick={() => setCal(null)}>
            Clear calibration
          </button>
        </div>
      )}
    </Section>
  );
}

export function SceneOverview({ defaultClasses }: { defaultClasses: string[] }) {
  const doc = useEditor((s) => s.doc)!;
  const select = useEditor((s) => s.select);
  const selectedId = useEditor((s) => s.selectedId);
  const selectedRouteId = useEditor((s) => s.selectedRouteId);
  const update = useEditor((s) => s.updateObject);
  const remove = useEditor((s) => s.removeObject);
  const addRoute = useEditor((s) => s.addRoute);
  const overlays = useEditor((s) => s.overlays);
  const setOverlay = useEditor((s) => s.setOverlay);
  const gates = doc.objects.filter((o) => o.type !== "ignore");
  return (
    <>
      <Section title={`Objects (${doc.objects.length})`}>
        {doc.objects.length === 0 && <div className="hint">Pick a tool on the left and draw over the frame. Lines and gates take two clicks; zones take one click per corner and a double-click to finish.</div>}
        <ul className="obj-list">
          {doc.objects.map((o) => (
            <li key={o.id} className={`${selectedId === o.id ? "selected" : ""} ${o.enabled ? "" : "disabled"}`} onClick={() => select(o.id)}>
              <span className="swatch" style={{ background: o.color ?? OBJECT_COLORS[o.type] }} />
              <span className="name">{objectLabel(o)}</span>
              <span className="hint">{OBJECT_TYPE_LABELS[o.type]}</span>
              <button className="btn ghost" title={o.visible ? "Hide" : "Show"} onClick={(e) => { e.stopPropagation(); update(o.id, { visible: !o.visible }); }}>
                {o.visible ? "hide" : "show"}
              </button>
              <button className="btn ghost" title="Delete" onClick={(e) => { e.stopPropagation(); remove(o.id); }}>
                ×
              </button>
            </li>
          ))}
        </ul>
      </Section>
      <Section
        title={`Routes (${doc.routes.length})`}
        right={
          <button
            className="btn ghost sm"
            disabled={gates.length < 2}
            onClick={() => addRoute({ id: newId("route"), name: `Route ${String.fromCharCode(65 + doc.routes.length)}`, enabled: true, color: null, start: gates[0].id, sequence: [], end: gates[1].id, classes: defaultClasses, timeout_s: 60, strict_sequence: true })}
          >
            Add route
          </button>
        }
      >
        {doc.routes.length === 0 && <div className="hint">A route is a path through gates: start → checkpoints → end. Draw at least two gates, then add a route or use the Route tool and click the gates in order.</div>}
        <ul className="obj-list">
          {doc.routes.map((r) => (
            <li key={r.id} className={`${selectedRouteId === r.id ? "selected" : ""} ${r.enabled ? "" : "disabled"}`} onClick={() => select(null, r.id)}>
              <span className="swatch" style={{ background: r.color ?? OBJECT_COLORS.route }} />
              <span className="name">{r.name}</span>
              <span className="hint">
                {[r.start, ...r.sequence, r.end].map((id) => doc.objects.find((o) => o.id === id)?.name ?? "?").join(" → ")}
              </span>
            </li>
          ))}
        </ul>
      </Section>
      <CalibrationInspector />
      <Section title="Overlays">
        <div className="row wrap">
          {(
            [
              ["objects", "Geometry"],
              ["labels", "Names"],
              ["boxes", "Boxes"],
              ["ids", "Track ids"],
              ["trails", "Trajectories"],
              ["conf", "Confidence"],
              ["routeState", "Route state"],
              ["zonesOfTrack", "Current zone"],
              ["identity", "Identities / plates"],
            ] as const
          ).map(([k, label]) => (
            <label key={k} className="check">
              <input type="checkbox" checked={overlays[k]} onChange={(e) => setOverlay(k, e.target.checked)} />
              {label}
            </label>
          ))}
        </div>
      </Section>
    </>
  );
}

export default function Inspector({ defaultClasses }: { defaultClasses: string[] }) {
  const doc = useEditor((s) => s.doc);
  const selectedId = useEditor((s) => s.selectedId);
  const selectedRouteId = useEditor((s) => s.selectedRouteId);
  const select = useEditor((s) => s.select);
  const duplicate = useEditor((s) => s.duplicateObject);
  const remove = useEditor((s) => s.removeObject);
  if (!doc) return <div className="panel-b hint">No scene loaded.</div>;
  const obj = selectedId ? doc.objects.find((o) => o.id === selectedId) : null;
  const route = selectedRouteId ? doc.routes.find((r) => r.id === selectedRouteId) : null;
  return (
    <div>
      <div className="panel-h">
        <span>{obj ? `${OBJECT_TYPE_LABELS[obj.type]}: ${objectLabel(obj)}` : route ? `Route: ${route.name}` : "Scene"}</span>
        {(obj || route) && (
          <span className="actions">
            {obj && (
              <button className="btn ghost sm" onClick={() => duplicate(obj.id)}>
                Duplicate
              </button>
            )}
            {obj && (
              <button className="btn ghost sm" onClick={() => remove(obj.id)}>
                Delete
              </button>
            )}
            <button className="btn ghost sm" onClick={() => select(null)}>
              Back
            </button>
          </span>
        )}
      </div>
      <div className="panel-b">
        {obj ? isLine(obj) ? <LineInspector o={obj} /> : <ZoneInspector o={obj} /> : route ? <RouteInspector r={route} /> : <SceneOverview defaultClasses={defaultClasses} />}
      </div>
    </div>
  );
}
