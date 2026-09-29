/* Guided live enrollment over /ws/recognition/enrollment/{person}. The server
 * watches the camera and says what to do; this hook keeps the latest picture,
 * the latest instruction and what has been captured so far. */

import { useCallback, useEffect, useRef, useState } from "react";
import type { EnrollmentAnalysis, QualityDetail, RecognitionPerson } from "../api/types";
import { recognitionToken } from "../lib/recognitionToken";

export interface GuidedStep {
  view: string;
  label: string;
  instruction: string;
  required: boolean;
}

export interface GuidedReady {
  person: RecognitionPerson;
  camera: { id: number; name: string; source_type: string };
  mirror: boolean;
  hold_needed: number;
  min_views: number;
  min_face_px: number;
  plan: GuidedStep[];
  extras: GuidedStep[];
  captured: string[];
  /** The look being captured; "" is the first enrollment. */
  variant: string;
  baseline: { yaw: number; pitch: number; brightness: number | null } | null;
}

export interface GuidedAnalysis {
  seq: number;
  width: number;
  height: number;
  n_faces: number;
  box: number[] | null;
  center_offset: number;
  quality: QualityDetail | null;
  view: string | null;
  instruction: string;
  direction: string | null;
  ok: boolean;
  hold: number;
  hold_needed: number;
  hold_quality: number | null;
  rel_yaw: number | null;
  rel_pitch: number | null;
  captured_views: string[];
}

export interface GuidedCapture {
  view: string;
  image_id: string | null;
  template_id: string | null;
  analysis: EnrollmentAnalysis;
  person: RecognitionPerson;
  captured: string[];
}

export interface GuidedNote {
  level: "warn" | "err";
  view?: string;
  message: string;
}

export function useGuidedEnrollment(personId: string, cameraId: number | null, active: boolean, onCaptured?: (c: GuidedCapture) => void, look = "") {
  const [ready, setReady] = useState<GuidedReady | null>(null);
  const [frameUrl, setFrameUrl] = useState<string | null>(null);
  const [analysis, setAnalysis] = useState<GuidedAnalysis | null>(null);
  const [captured, setCaptured] = useState<string[]>([]);
  const [note, setNote] = useState<GuidedNote | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const urlRef = useRef<string | null>(null);
  const capturedCb = useRef(onCaptured);
  capturedCb.current = onCaptured;

  useEffect(() => {
    if (!active || cameraId === null) return;
    setReady(null);
    setAnalysis(null);
    setNote(null);
    setError(null);
    setCaptured([]);
    const token = recognitionToken() ?? "";
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/recognition/enrollment/${personId}?camera_id=${cameraId}&rtoken=${encodeURIComponent(token)}&variant=${encodeURIComponent(look)}`);
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
      if (m.type === "ready") {
        setReady(m as GuidedReady);
        setCaptured(m.captured ?? []);
      } else if (m.type === "analysis") {
        setAnalysis(m as GuidedAnalysis);
      } else if (m.type === "captured") {
        setCaptured(m.captured ?? []);
        setNote(null);
        capturedCb.current?.(m as GuidedCapture);
      } else if (m.type === "note") {
        setNote({ level: m.level ?? "warn", view: m.view, message: m.message });
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
    };
  }, [personId, cameraId, active, look]);

  const setTarget = useCallback((view: string | null) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "target", view }));
    setNote(null);
  }, []);

  return { ready, frameUrl, analysis, captured, note, error, connected, setTarget };
}
