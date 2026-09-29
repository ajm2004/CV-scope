/* Reading state for the guides, kept in this browser only: which guides are
 * done, which steps are ticked, and the guide open in the side panel. */

import { create } from "zustand";

const KEY = "pathscope.guides.v1";

interface Saved {
  done: Record<string, boolean>;
  steps: Record<string, Record<string, boolean>>;
  opened: Record<string, number>;
  panel: string | null;
  collapsed: boolean;
}

function load(): Saved {
  const empty: Saved = { done: {}, steps: {}, opened: {}, panel: null, collapsed: false };
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return empty;
    const v = JSON.parse(raw) as Partial<Saved>;
    return { ...empty, ...v, done: v.done ?? {}, steps: v.steps ?? {}, opened: v.opened ?? {} };
  } catch {
    return empty;
  }
}

function save(s: Saved) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    /* private window or blocked storage: progress lasts for this visit only */
  }
}

interface GuideState extends Saved {
  toggleStep: (slug: string, key: string) => void;
  setDone: (slug: string, done: boolean) => void;
  markOpened: (slug: string) => void;
  resetGuide: (slug: string) => void;
  openPanel: (slug: string) => void;
  closePanel: () => void;
  setCollapsed: (collapsed: boolean) => void;
}

const initial = typeof window === "undefined" ? { done: {}, steps: {}, opened: {}, panel: null, collapsed: false } : load();

export const useGuideState = create<GuideState>((set, get) => {
  const persist = () => {
    const { done, steps, opened, panel, collapsed } = get();
    save({ done, steps, opened, panel, collapsed });
  };
  return {
    ...initial,
    toggleStep: (slug, key) => {
      const cur = get().steps[slug] ?? {};
      set({ steps: { ...get().steps, [slug]: { ...cur, [key]: !cur[key] } } });
      persist();
    },
    setDone: (slug, done) => {
      set({ done: { ...get().done, [slug]: done } });
      persist();
    },
    markOpened: (slug) => {
      if (get().opened[slug]) return;
      set({ opened: { ...get().opened, [slug]: Date.now() } });
      persist();
    },
    resetGuide: (slug) => {
      const steps = { ...get().steps };
      delete steps[slug];
      set({ steps, done: { ...get().done, [slug]: false } });
      persist();
    },
    openPanel: (slug) => {
      set({ panel: slug, collapsed: false });
      persist();
    },
    closePanel: () => {
      set({ panel: null });
      persist();
    },
    setCollapsed: (collapsed) => {
      set({ collapsed });
      persist();
    },
  };
});

export type GuideStatus = "done" | "started" | "new";

export function guideStatus(s: Pick<Saved, "done" | "steps" | "opened">, slug: string): GuideStatus {
  if (s.done[slug]) return "done";
  const ticked = Object.values(s.steps[slug] ?? {}).some(Boolean);
  return ticked || s.opened[slug] ? "started" : "new";
}

export function tickedCount(s: Pick<Saved, "steps">, slug: string): number {
  return Object.values(s.steps[slug] ?? {}).filter(Boolean).length;
}
