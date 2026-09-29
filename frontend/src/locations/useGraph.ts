/* State of one graph view: the merged model (with expansions), node positions
 * and the nodes the user pinned by dragging. */

import { useCallback, useRef, useState } from "react";
import type { VGraph } from "./api";
import { collapse, layout, merge, type Model, type Pos } from "./graphModel";

export function useGraph() {
  const [model, setModel] = useState<Model | null>(null);
  const [positions, setPositions] = useState<Record<string, Pos>>({});
  const pinned = useRef<Set<string>>(new Set());
  const posRef = useRef<Record<string, Pos>>({});

  const apply = useCallback((m: Model, fresh: boolean) => {
    const prev = fresh ? {} : posRef.current;
    const next = layout(m.graph.nodes, m.graph.edges, prev, pinned.current, m.graph.center);
    posRef.current = next;
    setPositions(next);
    setModel(m);
  }, []);

  const reset = useCallback((g: VGraph) => {
    pinned.current = new Set();
    apply({ graph: g, addedBy: {} }, true);
  }, [apply]);

  const add = useCallback((g: VGraph, expander?: string) => {
    setModel((cur) => {
      const m = merge(cur, g, expander);
      const next = layout(m.graph.nodes, m.graph.edges, posRef.current, pinned.current, m.graph.center);
      posRef.current = next;
      setPositions(next);
      return m;
    });
  }, []);

  const collapseNode = useCallback((key: string) => {
    setModel((cur) => (cur ? collapse(cur, key) : cur));
  }, []);

  const move = useCallback((key: string, p: Pos) => {
    pinned.current = new Set(pinned.current).add(key);
    posRef.current = { ...posRef.current, [key]: p };
    setPositions(posRef.current);
  }, []);

  const relayout = useCallback(() => {
    pinned.current = new Set();
    setModel((cur) => {
      if (cur) {
        const next = layout(cur.graph.nodes, cur.graph.edges, {}, new Set(), cur.graph.center);
        posRef.current = next;
        setPositions(next);
      }
      return cur;
    });
  }, []);

  return { model, positions, reset, add, collapseNode, move, relayout };
}
