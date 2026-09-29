import type { RecordingSettings } from "../api/types";
import { eventLabel } from "../lib/format";
import { Field, Notice, Panel } from "./ui";

export const DEFAULT_RECORDING: RecordingSettings = { mode: "off", pre_s: 5, post_s: 10, event_types: [], presence_grace_s: 3, overlay: true, fps: 10, segment_minutes: 10, max_clip_s: 300 };

// Event types a clip can start from, in the order users meet them
const TRIGGER_TYPES = ["zone_entry", "zone_exit", "crossing", "dwell", "dwell_exceeded", "occupancy_exceeded", "route", "sequence", "rule", "anomaly"];

/** Video recording of live runs (experiment page). Off unless the user turns it on. */
export function RecordingPanel({ value, onChange, sourceType }: { value: RecordingSettings; onChange: (v: RecordingSettings) => void; sourceType?: string }) {
  const set = (patch: Partial<RecordingSettings>) => onChange({ ...value, ...patch });
  const toggleType = (t: string, on: boolean) => set({ event_types: on ? [...new Set([...value.event_types, t])] : value.event_types.filter((x) => x !== t) });
  if (sourceType === "file") {
    return (
      <Panel title="Video recording">
        <Notice>This camera plays an uploaded video, which is kept already and can be reviewed. Recording is for live cameras: USB, built-in and network cameras.</Notice>
      </Panel>
    );
  }
  return (
    <Panel title="Video recording">
      <div className="stack" style={{ gap: 8 }}>
        <Field label="Record video">
          <select value={value.mode} onChange={(e) => set({ mode: e.target.value as RecordingSettings["mode"] })}>
            <option value="off">No video (default)</option>
            <option value="events">A clip around each event</option>
            <option value="presence">From entry to exit (one clip per visit)</option>
            <option value="continuous">The whole run</option>
          </select>
        </Field>
        {value.mode === "presence" && (
          <Notice>
            One clip per visit: it starts when an object triggers an event and runs until that object leaves the zone or the picture, so the whole stay is in one file instead of an entry clip and an exit clip with a hole between them. A visit longer than the maximum clip length continues in the next file.
          </Notice>
        )}
        {(value.mode === "events" || value.mode === "presence") && (
          <>
            <div className="form-grid">
              <Field label="Seconds before the event">
                <input type="number" min={0} max={60} step={1} value={value.pre_s} onChange={(e) => set({ pre_s: Number(e.target.value) })} />
              </Field>
              <Field label={value.mode === "presence" ? "Seconds after the exit" : "Seconds after the last event"}>
                <input type="number" min={0} max={600} step={1} value={value.post_s} onChange={(e) => set({ post_s: Number(e.target.value) })} />
              </Field>
              {value.mode === "presence" && (
                <Field label="Out of sight before a visit counts as over (s)" help="Covers tracker gaps: someone behind a pillar keeps the same visit.">
                  <input type="number" min={0} max={60} step={1} value={value.presence_grace_s} onChange={(e) => set({ presence_grace_s: Number(e.target.value) })} />
                </Field>
              )}
            </div>
            <Field
              label={value.mode === "presence" ? "Events that start a visit" : "Events that start a clip"}
              help={
                value.mode === "presence"
                  ? "None ticked: any recorded event starts the visit. A zone exit or a finished route ends it, and so does the object leaving the picture."
                  : "None ticked: every recorded event starts one. Events close together share a clip, which is at most 5 minutes long."
              }
            >
              <div className="row wrap">
                {TRIGGER_TYPES.map((t) => (
                  <label key={t} className="check">
                    <input type="checkbox" checked={value.event_types.includes(t)} onChange={(e) => toggleType(t, e.target.checked)} />
                    {eventLabel(t)}
                  </label>
                ))}
              </div>
            </Field>
          </>
        )}
        {value.mode === "continuous" && (
          <Field label="New file every (minutes)">
            <input type="number" min={1} max={60} step={1} value={value.segment_minutes} onChange={(e) => set({ segment_minutes: Number(e.target.value) })} />
          </Field>
        )}
        {value.mode !== "off" && (
          <>
            <Field
              label="Video frame rate (frames per second)"
              help={
                value.mode === "continuous"
                  ? "At most the processing rate. The whole run takes about 0.6 GB per hour at 640 × 480 and 10 frames per second."
                  : value.mode === "presence"
                    ? "At most the processing rate. A visit lasts as long as the person stays: a two-minute visit at 640 × 480 and 10 frames per second is about 40 MB."
                    : "At most the processing rate. A 20-second clip at 640 × 480 and 10 frames per second is about 7 MB."
              }
            >
              <input type="number" min={1} max={30} step={1} value={value.fps} onChange={(e) => set({ fps: Number(e.target.value) })} />
            </Field>
            <label className="check">
              <input type="checkbox" checked={value.overlay} onChange={(e) => set({ overlay: e.target.checked })} />
              Draw boxes, track numbers, zones, lines and the time into the video
            </label>
            <div className="hint">
              Video is saved in the data folder and played on the run's Review page. Settings lists it under What this installation stores; set Video retention (days) there to delete old video automatically. Tell the people you record.
            </div>
          </>
        )}
      </div>
    </Panel>
  );
}
