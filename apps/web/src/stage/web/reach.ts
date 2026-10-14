/**
 * Which nodes reach a function (B14): its tests, by `covers` edges and by `trace.sample` events,
 * and its callers, by `calls` edges. When a function runs, a bunch of strands fires from these
 * nodes to its ring card, like the reference's bunches that converge on one section of the wheel.
 *
 * The index is append-only and records the store index at which each node joined, so the bunch
 * for an event uses only what the log said up to that event: a pure function of the log prefix,
 * identical when playing, scrubbing or replaying live.
 */
import type { CockpitModel } from "../../model/cockpit";

/** Most strands in one bunch: the nearest of the nodes that reach the function. */
export const MAX_BUNCH = 8;

export class ReachIndex {
  /** Per function node: the nodes that reach it, in the order they joined, and at which event. */
  private readonly origins = new Map<number, number[]>();
  private readonly joined = new Map<number, number[]>();
  private readonly seen = new Set<number>();
  private synced = 0;

  constructor(private readonly model: CockpitModel) {}

  /** Indexes events appended since the last call. */
  sync(): void {
    const { store, graph } = this.model;
    for (let i = this.synced; i < store.length; i++) {
      const event = store.event(i);
      if (event === null) continue;
      if (event.kind === "graph.edge") {
        const { type } = event.payload;
        if (type !== "covers" && type !== "calls") continue;
        const source = graph.byId.get(event.payload.source);
        const target = graph.byId.get(event.payload.target);
        if (source !== undefined && target !== undefined) this.add(target, source, i);
      } else if (event.kind === "trace.sample" || event.kind === "diff.behaviour") {
        const test = event.target?.test;
        const source = test === undefined ? undefined : graph.byId.get(test);
        const target = graph.nodeForSymbol(event.payload.symbol_id);
        if (source !== undefined && target !== undefined) this.add(target, source, i);
      }
    }
    this.synced = store.length;
  }

  private add(target: number, source: number, index: number): void {
    if (source === target) return;
    // A pair key: node indices stay far below 2^21 for any graph the stage can draw.
    const key = target * 2_097_152 + source;
    if (this.seen.has(key)) return;
    this.seen.add(key);
    let origins = this.origins.get(target);
    let joined = this.joined.get(target);
    if (origins === undefined || joined === undefined) {
      origins = [];
      joined = [];
      this.origins.set(target, origins);
      this.joined.set(target, joined);
    }
    origins.push(source);
    joined.push(index);
  }

  /**
   * The bunch that fires at `target` with the event at store index `at`: `first` (the node that
   * fired), then the other nodes that had reached the target by that event, in the order they
   * joined, at most `out.length`. Returns how many it wrote. Allocation-free.
   */
  bunch(target: number, at: number, first: number | undefined, out: Int32Array): number {
    const origins = this.origins.get(target);
    const joined = this.joined.get(target);
    let n = 0;
    if (first !== undefined && first !== target && n < out.length) out[n++] = first;
    if (origins === undefined || joined === undefined) return n;
    for (let k = 0; k < origins.length && n < out.length; k++) {
      if ((joined[k] as number) > at) break; // joined later: entries are in log order
      const node = origins[k] as number;
      if (node !== first) out[n++] = node;
    }
    return n;
  }
}
