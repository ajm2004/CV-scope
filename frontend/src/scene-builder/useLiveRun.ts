import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { LiveStatus } from "../api/types";

export interface LiveTrack {
  id: number;
  cls: string;
  conf: number;
  box: [number, number, number, number];
  state: string;
  age: number;
  updated: boolean;
  trail?: [number, number][];
  zones?: string[];
  route_state?: { group: string; since_s: number; candidate: string | null; checkpoints: number } | null;
  /** Licensed recognition modules; present only for viewers with a recognition token. */
  recognition?: { status: string; identity?: string; identity_id?: string; plate?: string; vehicle?: string; vehicle_id?: string; confidence?: number } | null;
}

export interface FrameMeta {
  frame_index: number;
  media_time_s: number;
  width: number;
  height: number;
  source_width: number;
  source_height: number;
  tracks: LiveTrack[];
  interactions: { kind: string; track_id: number; object_id: string | null; object_name: string | null; direction: string | null; t: number }[];
  events: { type: string; label: string; track_id: number; route: string | null }[];
  processed: boolean;
}

export interface LiveFrame {
  img: HTMLImageElement;
  meta: FrameMeta;
}

export interface LiveEvent {
  seq: number;
  event_type: string;
  label: string;
  track_id: number;
  route: string | null;
  media_time_s: number;
  object_name: string | null;
  object_class: string;
}

export function useLiveRun(runId: number | null) {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [finished, setFinished] = useState(false);
  const [frame, setFrame] = useState<LiveFrame | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const pendingMeta = useRef<FrameMeta | null>(null);
  const lastUrl = useRef<string | null>(null);

  useEffect(() => {
    setStatus(null);
    setFinished(false);
    setFrame(null);
    setEvents([]);
    if (runId === null) return;
    let closed = false;
    const ws = new WebSocket(api.runs.wsUrl(runId));
    ws.binaryType = "blob";
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      if (!closed) setFinished(true);
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        const msg = JSON.parse(ev.data);
        if (msg.type === "frame") pendingMeta.current = msg as FrameMeta;
        else if (msg.type === "status") {
          setStatus(msg.live as LiveStatus);
          if (msg.finished) setFinished(true);
        } else if (msg.type === "events") {
          setEvents((prev) => [...prev, ...(msg.events as LiveEvent[])].slice(-300));
        }
        return;
      }
      const meta = pendingMeta.current;
      if (!meta) return;
      const blob = ev.data as Blob;
      const url = URL.createObjectURL(blob);
      const img = new Image();
      img.onload = () => {
        if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
        lastUrl.current = url;
        setFrame({ img, meta });
      };
      img.src = url;
    };
    return () => {
      closed = true;
      ws.close();
      wsRef.current = null;
      if (lastUrl.current) URL.revokeObjectURL(lastUrl.current);
      lastUrl.current = null;
    };
  }, [runId]);

  const send = (type: string, payload?: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type, payload }));
  };

  return { status, finished, frame, events, connected, send };
}

export function useImage(url: string | null): HTMLImageElement | null {
  const [img, setImg] = useState<HTMLImageElement | null>(null);
  useEffect(() => {
    if (!url) {
      setImg(null);
      return;
    }
    let cancelled = false;
    const im = new Image();
    im.onload = () => {
      if (!cancelled) setImg(im);
    };
    im.onerror = () => {
      if (!cancelled) setImg(null);
    };
    im.src = url;
    return () => {
      cancelled = true;
    };
  }, [url]);
  return img;
}
