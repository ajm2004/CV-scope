import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { AnomalySettings, AnomalyZoneSettings, SceneObject } from "../api/types";
import { ANOMALY_KINDS, DEFAULT_ANOMALY, effectiveThresholds, FRAME_ZONE_ID, newAnomalyZone, SENSITIVITY_PRESETS } from "../lib/anomaly";
import { CLASS_OPTIONS } from "../lib/format";
import { ClassPicker, Field, Notice, Panel, Pill } from "./ui";

export { DEFAULT_ANOMALY };

/** Anomaly Assistant settings of an experiment: what to watch, how strict, and how a vision model takes part. */
export function AnomalyPanel({ value, onChange, sceneObjects, classes }: { value: AnomalySettings; onChange: (v: AnomalySettings) => void; sceneObjects: SceneObject[]; classes: string[] }) {
  const [advanced, setAdvanced] = useState(false);
  const assistant = useQuery({ queryKey: ["anomaly-assistant"], queryFn: api.anomalyAssistant.get, staleTime: 30_000 });
  const set = (patch: Partial<AnomalySettings>) => onChange({ ...value, ...patch });
  const zones = sceneObjects.filter((o) => o.type === "zone" || o.type === "checkpoint");
  const watched = (id: string) => value.zones.find((z) => z.id === id);
  const toggle = (id: string, name: string, on: boolean) =>
    set({ zones: on ? [...value.zones, newAnomalyZone(id, name)] : value.zones.filter((z) => z.id !== id) });
  const setZone = (id: string, patch: Partial<AnomalyZoneSettings>) => set({ zones: value.zones.map((z) => (z.id === id ? { ...z, ...patch } : z)) });
  const provider = assistant.data?.settings.provider ?? "none";
  const providerName = assistant.data?.providers.find((p) => p.id === provider)?.name ?? provider;
  const usesModel = value.zones.some((z) => z.validation !== "deterministic");
  const missing = value.zones.filter((z) => z.id !== FRAME_ZONE_ID && !zones.some((o) => o.id === z.id));

  return (
    <Panel title="Anomaly Assistant" actions={value.enabled ? <Pill tone="accent">{value.zones.filter((z) => z.enabled).length} watched</Pill> : undefined}>
      <div className="stack" style={{ gap: 10 }}>
        <label className="check">
          <input type="checkbox" checked={value.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          Watch for meaningful change from the normal, empty or static scene
        </label>
        {!value.enabled && (
          <div className="hint">
            For rooms, vaults, stalls or beds that should stay as they are: the assistant learns the normal picture and reports objects that appear, disappear or move, people or animals where nobody should be, and a covered or turned camera. Dust, noise, shadows,
            small lighting changes and insects are filtered out.
          </div>
        )}
        {value.enabled && (
          <>
            <Field label="Watch" help="The whole picture, or zones drawn in the Scene Builder (each with its own settings). Ignore regions of the scene are never watched.">
              <div className="stack" style={{ gap: 4 }}>
                <label className="check">
                  <input type="checkbox" checked={!!watched(FRAME_ZONE_ID)} onChange={(e) => toggle(FRAME_ZONE_ID, "Whole picture", e.target.checked)} />
                  The whole picture
                </label>
                {zones.map((o) => (
                  <label key={o.id} className="check">
                    <input type="checkbox" checked={!!watched(o.id)} onChange={(e) => toggle(o.id, o.name || o.id, e.target.checked)} />
                    Zone “{o.name || o.id}”
                  </label>
                ))}
                {zones.length === 0 && <div className="hint">The scene has no zones yet. Draw one in the Scene Builder to watch part of the picture (a bed, a stall, a doorway).</div>}
              </div>
            </Field>
            {missing.length > 0 && <Notice tone="warn">Not in the chosen scene version: {missing.map((z) => z.name || z.id).join(", ")}. They are skipped when a run starts.</Notice>}
            {value.zones.length === 0 && <Notice tone="warn">Choose at least one area to watch.</Notice>}
            {value.zones.map((z) => (
              <ZoneCard key={z.id} zone={z} title={z.name || zones.find((o) => o.id === z.id)?.name || (z.id === FRAME_ZONE_ID ? "Whole picture" : z.id)} classes={classes} onChange={(patch) => setZone(z.id, patch)} />
            ))}
            {usesModel && provider === "none" && (
              <Notice tone="warn">
                Some areas use a vision model, but none is selected. Choose one on the <Link to="/anomalies/assistant">Anomaly Assistant</Link> page; until then those events follow “When the model cannot answer” below.
              </Notice>
            )}
            {usesModel && provider !== "none" && (
              <div className="hint">
                Model: {providerName} · {assistant.data?.resolved.model}. <Link to="/anomalies/assistant">Change</Link>
              </div>
            )}
            <label className="check">
              <input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} />
              Settings for the whole camera
            </label>
            {advanced && (
              <div className="form-grid">
                <Field label="Learn the normal picture for (s)" help="At the start of every run. Keep the scene as it should be.">
                  <input type="number" min={2} max={300} step={1} value={value.learn_s} onChange={(e) => set({ learn_s: Number(e.target.value) })} />
                </Field>
                <Field label="Analyses per second" help="Independent of the detector's frame rate. 2 to 4 is plenty for rooms.">
                  <input type="number" min={0.5} max={15} step={0.5} value={value.analysis_fps} onChange={(e) => set({ analysis_fps: Number(e.target.value) })} />
                </Field>
                <Field label="Follow slow daylight over (minutes)" help="How fast the normal picture follows gradual light. Never where something is currently different.">
                  <input type="number" min={0.5} max={240} step={0.5} value={value.adapt_minutes} onChange={(e) => set({ adapt_minutes: Number(e.target.value) })} />
                </Field>
                <Field label="Analysed width (px)" help="Smaller is faster and ignores finer detail; larger finds smaller objects.">
                  <select value={value.working_width} onChange={(e) => set({ working_width: Number(e.target.value) })}>
                    {[240, 320, 480, 640].map((w) => (
                      <option key={w} value={w}>
                        {w}
                        {w === 320 ? " (default)" : ""}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="When the model cannot answer" help="For areas where the model must confirm: no model, an error, the budget or the queue is full.">
                  <select value={value.on_llm_failure} onChange={(e) => set({ on_llm_failure: e.target.value as AnomalySettings["on_llm_failure"] })}>
                    <option value="raise">Raise the event anyway (safer)</option>
                    <option value="hold">Hold it for review</option>
                  </select>
                </Field>
                <div className="stack" style={{ gap: 4, gridColumn: "1 / -1" }}>
                  <label className="check">
                    <input type="checkbox" checked={value.tamper_events} onChange={(e) => set({ tamper_events: e.target.checked })} />
                    Report a covered, blinded or turned camera
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={value.lighting_events} onChange={(e) => set({ lighting_events: e.target.checked })} />
                    Report lights switched on or off
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={value.use_ignore_regions} onChange={(e) => set({ use_ignore_regions: e.target.checked })} />
                    Never watch the scene's ignore regions (screens, windows with trees)
                  </label>
                  <label className="check">
                    <input type="checkbox" checked={value.recognition} onChange={(e) => set({ recognition: e.target.checked })} />
                    Include recognition results (known or unknown person, registered vehicle) where the licensed modules run
                  </label>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </Panel>
  );
}

function num(v: string): number | null {
  return v === "" ? null : Number(v);
}

function ZoneCard({ zone, title, classes, onChange }: { zone: AnomalyZoneSettings; title: string; classes: string[]; onChange: (patch: Partial<AnomalyZoneSettings>) => void }) {
  const [open, setOpen] = useState(zone.expected_state === "");
  const [hooks, setHooks] = useState(zone.webhooks.join("\n"));
  const th = effectiveThresholds(zone);
  const preset = SENSITIVITY_PRESETS[zone.sensitivity === "custom" ? "medium" : zone.sensitivity];
  const classOptions = CLASS_OPTIONS.filter((c) => classes.length === 0 || classes.includes(c.id));
  const summary = `${zone.sensitivity} sensitivity · lasts ${th.persistence_s} s · ${zone.validation === "deterministic" ? "computer vision only" : zone.validation === "assisted" ? "model describes" : "model must confirm"}`;
  return (
    <div className="panel" style={{ margin: 0 }}>
      <div className="panel-h" style={{ cursor: "pointer" }} onClick={() => setOpen(!open)}>
        <span className="row" style={{ gap: 8 }}>
          <strong>{title}</strong>
          <span className="hint">{summary}</span>
        </span>
        <span className="row" style={{ gap: 6 }}>
          <label className="check" onClick={(e) => e.stopPropagation()}>
            <input type="checkbox" checked={zone.enabled} onChange={(e) => onChange({ enabled: e.target.checked })} />
            On
          </label>
          <span className="muted">{open ? "▾" : "▸"}</span>
        </span>
      </div>
      {open && (
        <div className="panel-b">
          <div className="form-grid">
            <Field label="Normal state, in plain words" className="span-2" help="Shown with every event and given to the vision model, for example “The stall is empty.” or “The bed is made; nobody is here at night.”">
              <textarea rows={2} value={zone.expected_state} onChange={(e) => onChange({ expected_state: e.target.value })} />
            </Field>
            <Field label="Sensitivity" help="High finds smaller and shorter changes; low only large, lasting ones.">
              <select value={zone.sensitivity} onChange={(e) => onChange({ sensitivity: e.target.value as AnomalyZoneSettings["sensitivity"] })}>
                <option value="low">Low: large, lasting changes</option>
                <option value="medium">Medium (default)</option>
                <option value="high">High: small or brief changes</option>
                <option value="custom">Custom thresholds</option>
              </select>
            </Field>
            <Field label="Only when it lasts at least (s)" help={`Persistence. Empty: ${preset.persistence_s} s from the sensitivity.`}>
              <input type="number" min={0} max={600} step={0.5} placeholder={String(preset.persistence_s)} value={zone.persistence_s ?? ""} onChange={(e) => onChange({ persistence_s: num(e.target.value) })} />
            </Field>
            {zone.sensitivity === "custom" && (
              <>
                <Field label="Smallest change (% of the area)" help={`Default ${preset.min_area_pct}`}>
                  <input type="number" min={0.05} max={80} step={0.05} placeholder={String(preset.min_area_pct)} value={zone.min_area_pct ?? ""} onChange={(e) => onChange({ min_area_pct: num(e.target.value) })} />
                </Field>
                <Field label="Smallest brightness difference (0-255)" help={`Default ${preset.min_contrast}`}>
                  <input type="number" min={4} max={120} step={1} placeholder={String(preset.min_contrast)} value={zone.min_contrast ?? ""} onChange={(e) => onChange({ min_contrast: num(e.target.value) })} />
                </Field>
                <Field label="Above camera noise (× noise level)" help={`Default ${preset.k_sigma}`}>
                  <input type="number" min={1} max={12} step={0.5} placeholder={String(preset.k_sigma)} value={zone.k_sigma ?? ""} onChange={(e) => onChange({ k_sigma: num(e.target.value) })} />
                </Field>
                <Field label="Minimum confidence (0-1)" help={`Default ${preset.min_confidence}`}>
                  <input type="number" min={0} max={1} step={0.05} placeholder={String(preset.min_confidence)} value={zone.min_confidence ?? ""} onChange={(e) => onChange({ min_confidence: num(e.target.value) })} />
                </Field>
              </>
            )}
            <Field label="Report" className="span-2">
              <div className="row wrap">
                {ANOMALY_KINDS.map((k) => (
                  <label key={k.id} className="check" title={k.help}>
                    <input
                      type="checkbox"
                      checked={zone.detect.includes(k.id)}
                      onChange={(e) => onChange({ detect: e.target.checked ? [...new Set([...zone.detect, k.id])] : zone.detect.filter((x) => x !== k.id) })}
                    />
                    {k.label}
                  </label>
                ))}
              </div>
            </Field>
            {zone.detect.includes("presence") && (
              <Field label="Presence of" className="span-2" help="None ticked: any object the experiment tracks. Presence needs the class among Objects to track.">
                <ClassPicker value={zone.presence_classes} onChange={(v) => onChange({ presence_classes: v })} options={classOptions} />
              </Field>
            )}
            <Field label="Accept a still change as normal after (s)" help="A moved chair stops being an event after this long. 0 keeps it an event until it is undone.">
              <input type="number" min={0} max={86400} step={10} value={zone.accept_after_s} onChange={(e) => onChange({ accept_after_s: Number(e.target.value) })} />
            </Field>
            <Field label="Quiet time after an event (s)">
              <input type="number" min={0} max={3600} step={1} value={zone.cooldown_s} onChange={(e) => onChange({ cooldown_s: Number(e.target.value) })} />
            </Field>
            <Field label="Vision model" help="The model interprets the evidence the computer vision found; it never replaces the detection.">
              <select value={zone.validation} onChange={(e) => onChange({ validation: e.target.value as AnomalyZoneSettings["validation"] })}>
                <option value="deterministic">Computer vision only</option>
                <option value="assisted">Raise at once, the model adds a description</option>
                <option value="confirmed">Raise only when the model confirms</option>
              </select>
            </Field>
            {zone.validation === "assisted" && (
              <Field label="Describe" help="At the end the description can include how long it lasted.">
                <select value={zone.interpret_at} onChange={(e) => onChange({ interpret_at: e.target.value as AnomalyZoneSettings["interpret_at"] })}>
                  <option value="confirm">When the event is confirmed</option>
                  <option value="end">When the event ends</option>
                </select>
              </Field>
            )}
            <Field label="Webhooks (one per line)" className="span-2" help="Receive the event, then its description and its end. Settings: Allow webhook actions must be on.">
              <textarea
                rows={2}
                placeholder="https://example.org/alerts"
                value={hooks}
                onChange={(e) => setHooks(e.target.value)}
                onBlur={() => onChange({ webhooks: hooks.split("\n").map((s) => s.trim()).filter(Boolean) })}
              />
            </Field>
            <label className="check" style={{ gridColumn: "1 / -1" }}>
              <input type="checkbox" checked={zone.record_clip} onChange={(e) => onChange({ record_clip: e.target.checked })} />
              Start a video clip (when the experiment records clips of events)
            </label>
          </div>
        </div>
      )}
    </div>
  );
}
