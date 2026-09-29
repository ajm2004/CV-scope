/* Names for the opaque entity ids that ordinary events carry.
 *
 * A stored event never holds a name: its context has `entity` with the kind
 * and the stable ids only, so the core API, the CSV export and every
 * unauthenticated viewer stay anonymous. A browser that holds a recognition
 * token can ask the recognition API what those ids stand for, which is what
 * this hook does, and the name then appears in the table for that viewer
 * alone. */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { api } from "../api/client";
import type { ResolvedNames } from "../api/types";
import { useRecognitionAuth } from "../lib/recognitionToken";

export interface EntityContext {
  kind?: string;
  identity_id?: string;
  vehicle_id?: string;
  status?: string;
  confidence?: number;
  recognition_event_id?: number;
}

export function eventEntity(context: Record<string, unknown> | undefined | null): EntityContext | null {
  const e = context?.entity as EntityContext | undefined;
  return e && typeof e === "object" ? e : null;
}

/** Ask the recognition API for the names behind the ids in these events. */
export function useEntityNames(events: { context?: Record<string, unknown> }[] | undefined) {
  const token = useRecognitionAuth((s) => s.token);
  const { identity_ids, vehicle_ids } = useMemo(() => {
    const people = new Set<string>();
    const vehicles = new Set<string>();
    for (const e of events ?? []) {
      const ent = eventEntity(e.context);
      if (ent?.identity_id) people.add(ent.identity_id);
      if (ent?.vehicle_id) vehicles.add(ent.vehicle_id);
    }
    return { identity_ids: [...people].sort(), vehicle_ids: [...vehicles].sort() };
  }, [events]);
  const any = identity_ids.length > 0 || vehicle_ids.length > 0;
  return useQuery({
    queryKey: ["recognition-resolve", identity_ids, vehicle_ids],
    queryFn: () => api.recognition.resolve({ identity_ids, vehicle_ids }),
    enabled: !!token && any,
    staleTime: 60_000,
    retry: 0,
  });
}

export interface EntityLabel {
  text: string;
  /** A possible match is never an identity; it is shown with a question mark. */
  possible: boolean;
  known: boolean;
  status: string | null;
}

const KIND_TEXT: Record<string, string> = {
  anonymous_person: "Anonymous",
  anonymous_vehicle: "Anonymous",
  anonymous_object: "Anonymous",
};

/** What to show in an Identity column for one event. */
export function entityLabel(context: Record<string, unknown> | undefined | null, names: ResolvedNames | undefined): EntityLabel | null {
  const ent = eventEntity(context);
  if (!ent) return null;
  const possible = ent.status === "possible_match";
  if (ent.identity_id) {
    const person = names?.identities[ent.identity_id];
    return { text: person ? person.display_name : "Enrolled person", possible, known: !!person, status: ent.status ?? null };
  }
  if (ent.vehicle_id) {
    const v = names?.vehicles[ent.vehicle_id];
    return { text: v ? v.label || v.plate : "Registered vehicle", possible, known: !!v, status: ent.status ?? null };
  }
  const text = KIND_TEXT[ent.kind ?? ""] ?? null;
  return text ? { text, possible: false, known: true, status: ent.status ?? null } : null;
}
