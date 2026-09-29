import { useEffect, useRef, useState } from "react";

export interface PreviewFrame {
  img: HTMLImageElement;
  width: number;
  height: number;
  source_width: number;
  source_height: number;
}

export interface PreviewStatus {
  state: string; // opening | live | error | stopped
  error: string | null;
  fps: number;
  backend: string;
  frame_width: number;
  frame_height: number;
  source_width: number;
  source_height: number;
  source_fps: number;
  viewers: number;
}

/** Live picture of a camera outside a run, over /ws/cameras/{id}/preview.
 *  The camera stays open while this hook is enabled and is released by the
 *  server a few seconds after the last viewer leaves. */
export function useCameraPreview(cameraId: number | null, enabled: boolean) {
  const [frame, setFrame] = useState<PreviewFrame | null>(null);
  const [status, setStatus] = useState<PreviewStatus | null>(null);
  const [runActive, setRunActive] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const lastUrl = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || cameraId === null) return;
    setRunActive(null);
    setError(null);
    let closed = false;
    let retry: number | undefined;
    let ws: WebSocket | null = null;
    let stopReconnecting = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws/cameras/${cameraId}/preview`);
      ws.binaryType = "blob";
      let pending: Omit<PreviewFrame, "img"> | null = null;
      ws.onmessage = (ev) => {
        if (typeof ev.data === "string") {
          const m = JSON.parse(ev.data);
          if (m.type === "frame") pending = m;
          else if (m.type === "status") setStatus(m as PreviewStatus);
          else if (m.type === "run_active") {
            stopReconnecting = true;
            setRunActive(m.run_id);
          } else if (m.type === "error") {
            stopReconnecting = true;
            setError(m.message);
          }
          return;
        }
        const meta = pending;
        pending = null;
        if (!meta) return;
        const url = URL.createObjectURL(ev.data as Blob);
        const img = new Image();
        img.onload = () => {
          if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
          lastUrl.current = url;
          setFrame({ img, ...meta });
        };
        img.src = url;
      };
      ws.onclose = () => {
        if (!closed && !stopReconnecting) retry = window.setTimeout(connect, 1500); // server restart, network hiccup
      };
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      ws?.close();
    };
  }, [cameraId, enabled]);

  useEffect(
    () => () => {
      if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
    },
    [],
  );

  return { frame, status, runActive, error };
}
