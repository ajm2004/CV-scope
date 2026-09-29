/* The video recorded during a run, next to its results.
 *
 * A run on a live camera can record the whole run or a clip around every
 * event (Video recording on the experiment page). This panel lists what was
 * recorded, plays a clip in place and lets an event be jumped to, so the
 * numbers in the analysis can be checked against the picture without leaving
 * the page. The full timeline with overlays stays on the Video review page. */

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { api } from "../api/client";
import type { EventRecord, Recording } from "../api/types";
import { entityLabel, useEntityNames } from "../recognition/useEntityNames";
import { bytes, clock, dateTime, eventLabel, seconds } from "../lib/format";
import { Empty, Notice, Panel, Pill } from "./ui";

function triggerLabel(r: Recording): string {
  if (r.kind === "continuous") return "Whole run";
  if (!r.triggers.length) return r.kind === "presence" ? "Visit" : "Event";
  const t = r.triggers[0];
  const prefix = r.kind === "presence" ? "Visit from " : "";
  return `${prefix}${t.label}${t.track_id ? ` #${t.track_id}` : ""}${r.trigger_count > 1 ? ` and ${r.trigger_count - 1} more` : ""}`;
}

export default function RunVideo({ runId, isFile }: { runId: number; isFile: boolean }) {
  const recordings = useQuery({ queryKey: ["recordings", runId], queryFn: () => api.recordings.forRun(runId) });
  const events = useQuery({ queryKey: ["events", "video", runId], queryFn: () => api.events.list({ run_id: runId, page_size: 500, sort: "media_time_s", order: "asc" }) });
  const [current, setCurrent] = useState<Recording | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const recs = recordings.data ?? [];
  const playable = recs.filter((r) => r.playable);
  const items = (events.data?.items ?? []) as EventRecord[];
  const names = useEntityNames(items);

  useEffect(() => {
    if (!current && playable.length) setCurrent(playable[0]);
  }, [recordings.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const inClip = current ? items.filter((e) => e.media_time_s >= current.media_start_s - 0.05 && e.media_time_s <= current.media_end_s + 0.05) : [];
  const seek = (mediaTime: number) => {
    const v = videoRef.current;
    if (!v || !current) return;
    v.currentTime = Math.max(0, mediaTime - current.media_start_s - 1.0);
    void v.play();
  };

  if (recordings.isSuccess && recs.length === 0)
    return (
      <Panel title="Video">
        <Empty>
          {isFile ? (
            <>
              This run analysed an uploaded video. Play it with the overlays on the <Link to={`/review/${runId}`}>Video review</Link> page.
            </>
          ) : (
            <>No video was recorded for this run. Turn on Video recording on the experiment page to keep clips around events, or the whole run.</>
          )}
        </Empty>
      </Panel>
    );

  return (
    <div className="stack">
      <Panel
        title={current ? `Playing: ${triggerLabel(current)}` : "Recorded video"}
        actions={
          <Link className="btn sm" to={`/review/${runId}`}>
            Video review with overlays
          </Link>
        }
      >
        {current ? (
          <div className="grid-2">
            <div className="stack">
              <div className="video-stage">
                <video ref={videoRef} src={api.recordings.fileUrl(current.id)} controls autoPlay={false} preload="metadata" style={{ width: "100%", display: "block" }} />
              </div>
              <div className="hint">
                Run time {clock(current.media_start_s)}–{clock(current.media_end_s)} · {seconds(current.duration_s, 1)} · {current.width}×{current.height} at {current.fps} fps · {bytes(current.size_bytes)}
                {current.overlay ? " · boxes, track numbers and zones are in the picture" : ""}
              </div>
            </div>
            <div className="stack" style={{ gap: 6 }}>
              <div className="section-title">Events in this clip ({inClip.length})</div>
              {inClip.length === 0 ? (
                <div className="hint">No stored event falls inside this clip.</div>
              ) : (
                <div className="table-wrap" style={{ maxHeight: 260 }}>
                  <table className="table">
                    <tbody>
                      {inClip.map((e) => {
                        const label = entityLabel(e.context, names.data);
                        return (
                          <tr key={e.id} className="clickable" onClick={() => seek(e.media_time_s)}>
                            <td className="num">{clock(e.media_time_s)}</td>
                            <td>{eventLabel(e.event_type)}</td>
                            <td>{e.route ?? e.object_name ?? "–"}</td>
                            <td className="num">#{e.track_id}</td>
                            <td>{label && (label.known || label.possible) ? <Pill tone={label.possible ? "warn" : "accent"}>{label.possible ? "? " : ""}{label.text}</Pill> : null}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        ) : (
          <Notice tone="warn">The recorded files are in a format this browser cannot play. Download one below, or open the Video review page.</Notice>
        )}
      </Panel>
      <Panel title={`Recorded files (${recs.length})`} flush>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Recorded</th>
                <th className="num">Run time</th>
                <th className="num">Length</th>
                <th>Started by</th>
                <th className="num">Size</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {recs.map((r) => (
                <tr key={r.id} className={current?.id === r.id ? "selected" : ""}>
                  <td className="muted">{dateTime(r.started_at)}</td>
                  <td className="num">{clock(r.media_start_s)}</td>
                  <td className="num">{seconds(r.duration_s, 1)}</td>
                  <td>{triggerLabel(r)}</td>
                  <td className="num">{bytes(r.size_bytes)}</td>
                  <td className="row" style={{ gap: 4 }}>
                    {r.playable ? (
                      <button className="btn sm" onClick={() => setCurrent(r)}>
                        Play here
                      </button>
                    ) : (
                      <span className="hint">not playable in the browser</span>
                    )}
                    <a className="btn sm" href={api.recordings.fileUrl(r.id, true)}>
                      Download
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
