/* The recognition access token of this browser (licensed modules). Kept in
 * localStorage; sent as a header on /api/recognition requests and as a query
 * parameter on WebSocket and image URLs. No other API uses it. */

import { create } from "zustand";

const KEY = "pathscope.recognitionToken";

function read(): string | null {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export const useRecognitionAuth = create<{ token: string | null; setToken: (t: string | null) => void }>((set) => ({
  token: read(),
  setToken: (t) => {
    try {
      if (t) localStorage.setItem(KEY, t);
      else localStorage.removeItem(KEY);
    } catch {
      /* ignore */
    }
    set({ token: t });
  },
}));

export function recognitionToken(): string | null {
  return useRecognitionAuth.getState().token;
}

export const MODULE_STATE_LABEL: Record<string, string> = {
  not_licensed: "Not licensed",
  licensed: "Licensed",
  expired: "Expired",
  disabled: "Disabled",
};

export function moduleStateTone(state: string): "" | "ok" | "warn" | "err" | "accent" {
  if (state === "licensed") return "ok";
  if (state === "expired") return "err";
  if (state === "disabled") return "warn";
  return "";
}

export const ROLE_LABEL: Record<string, string> = { viewer: "Viewer", operator: "Operator", admin: "Administrator" };

export function roleAtLeast(role: string | undefined, min: "viewer" | "operator" | "admin"): boolean {
  const order = { viewer: 1, operator: 2, admin: 3 } as Record<string, number>;
  return (order[role ?? ""] ?? 0) >= order[min];
}
