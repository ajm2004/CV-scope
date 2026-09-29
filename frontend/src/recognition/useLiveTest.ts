/* Live recognition test over /ws/recognition/test/live.
 *
 * The server takes the camera picture, runs the same chain a run would use and
 * sends back what it found: the faces, their quality and the ranked candidates
 * with their similarity. It stores nothing by itself. The operator can answer,
 * and only an answer writes something: a verdict goes to the audit trail, and
 * a confirmation adds the frame on screen to that person's enrollment. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { IdentifyResult, RecognitionPerson } from "../api/types";
import { recognitionToken } from "../lib/recognitionToken";

export interface LiveTestReady {
  camera: { id: number; name: string; source_type: string };
  mirror: boolean;
  model_version: string;
  identities: number;
  templates: number;
  identities_other_model: number;
  thresholds: IdentifyResult["thresholds"];
}

export interface FeedbackCounts {
  checked: number;
  correct: number;
  wrong: number;
  unknown_person: number;
  taught: number;
}

export interface TaughtResult {
  person: RecognitionPerson;
  similarity: number | null;
  look: string;
  enrollment: { status: string; quality: number | null; templates: number };
}

export interface RefusedTeach {
  code: "quality" | "mismatch";
  message: string;
  similarity: number | null;
}

export interface LiveTestNote {
  level: "warn" | "err";
  message: string;
}

export type LiveTestCommand =
  | { type: "feedback"; verdict: "correct" | "wrong" | "unknown_person"; person_id?: string | null; similarity?: number | null; corrected_person_id?: string | null }
  | { type: "confirm"; person_id: string; force?: boolean }
  | { type: "reload" };

export function useLiveTest(cameraId: number | null, active: boolean, onTaught?: (t: TaughtResult) => void) {
  const [ready, setReady] = useState<LiveTestReady | null>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [result, setResult] = useState<(IdentifyResult & { seq: number }) | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [counts, setCounts] = useState<FeedbackCounts | null>(null);
  const [taught, setTaught] = useState<TaughtResult | null>(null);
  const [refused, setRefused] = useState<RefusedTeach | null>(null);
  const [note, setNote] = useState<LiveTestNote | null>(null);
  const urlRef = useRef<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const taughtCb = useRef(onTaught);
  taughtCb.current = onTaught;

  useEffect(() => {
    if (!active || cameraId === null) return;
    setReady(null);
    setResult(null);
    setError(null);
    setTaught(null);
    setRefused(null);
    setNote(null);
    const token = recognitionToken() ?? "";
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/recognition/test/live?camera_id=${cameraId}&rtoken=${encodeURIComponent(token)}`);
    ws.binaryType = "blob";
    wsRef.current = ws;
    let closed = false;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      if (!closed) setError((e) => e ?? "The connection to the camera ended.");
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") {
        const url = URL.createObjectURL(ev.data as Blob);
        const previous = urlRef.current;
        urlRef.current = url;
        setFrameUrl(url);
        // Free the old picture only after this one is on screen; revoking it
        // straight away can cancel a paint that is still in flight.
        if (previous) requestAnimationFrame(() => URL.revokeObjectURL(previous));
        return;
      }
      const m = JSON.parse(ev.data);
      if (m.type === "ready" || m.type === "reloaded") {
        setReady((r) => ({ ...(r ?? ({} as LiveTestReady)), ...m }) as LiveTestReady);
      } else if (m.type === "result") {
        setResult(m as IdentifyResult & { seq: number });
      } else if (m.type === "feedback") {
        setCounts({ checked: m.checked, correct: m.correct, wrong: m.wrong, unknown_person: m.unknown_person, taught: m.taught });
      } else if (m.type === "taught") {
        setRefused(null);
        setNote(null);
        const t = { person: m.person, similarity: m.similarity, look: m.look, enrollment: m.enrollment } as TaughtResult;
        setTaught(t);
        taughtCb.current?.(t);
      } else if (m.type === "refused") {
        setRefused({ code: m.code, message: m.message, similarity: m.similarity ?? null });
      } else if (m.type === "note") {
        setNote({ level: m.level ?? "warn", message: m.message });
      } else if (m.type === "error") {
        closed = true;
        setError(m.message);
      }
    };
    return () => {
      closed = true;
      try {
        ws.send(JSON.stringify({ type: "stop" }));
      } catch {
        /* already closing */
      }
      ws.close();
      wsRef.current = null;
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
      setFrameUrl(null);
      setConnected(false);
    };
  }, [cameraId, active]);

  const send = useCallback((cmd: LiveTestCommand) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(cmd));
    if (cmd.type !== "confirm") setRefused(null);
  }, []);

  return { ready, frameUrl, result, error, connected, counts, taught, refused, note, send, setTaught, setRefused };
}
