/**
 * The relations strands are drawn from (B14). A bunch of strands fires from the nodes connected
 * to what an event is about, at that thing's section of the wheel:
 * - a function: the nodes that reach it, its tests (by `covers` edges and trace samples) and its
 *   callers (by `calls` edges);
 * - a test: the functions it reaches (the same relations, the other way);
 * - a file: its own functions, classes and tests.
 *
 * Each section's outside lines show the file's recent activity: its streaming events.
 *
 * Every entry records the store index at which it joined, so a bunch for an event uses only what
 * the log said up to that event: a pure function of the log prefix, identical when playing,
 * scrubbing or replaying live.
 */
import type { CockpitModel } from "../../model/cockpit";
import { eventFile } from "../ring/sections";
import { streams } from "../streams/style";

/** Most strands in one bunch: the nearest of the connected nodes. */
export const MAX_BUNCH = 8;

/** Append-only lists per key, each entry with the store index at which it joined. */
class JoinedLists<K> {
  private readonly items = new Map<K, number[]>();
  private readonly joined = new Map<K, number[]>();

  add(key: K, item: number, index: number): void {
    let items = this.items.get(key);
    let joined = this.joined.get(key);
    if (items === undefined || joined === undefined) {
      items = [];
      joined = [];
      this.items.set(key, items);
      this.joined.set(key, joined);
    }
    items.push(item);
    joined.push(index);
  }

  /**
   * Appends to `out` from position `n` the items of `key` that joined by store index `at`,
   * skipping `skip`, until `out` is full; returns the new count.
   */
  collect(key: K, at: number, skip: number, out: Int32Array, n: number): number {
    const items = this.items.get(key);
    const joined = this.joined.get(key);
    if (items === undefined || joined === undefined) return n;
    let count = n;
    for (let k = 0; k < items.length && count < out.length; k++) {
      if ((joined[k] as number) > at) break; // joined later: entries are in log order
      const item = items[k] as number;
      if (item !== skip) out[count++] = item;
    }
    return count;
  }

  /** Writes to `out` the items of `key` that joined by store index `at`, newest first. */
  latest(key: K, at: number, out: Int32Array): number {
    const items = this.items.get(key);
    const joined = this.joined.get(key);
    if (items === undefined || joined === undefined) return 0;
    let end = items.length;
    while (end > 0 && (joined[end - 1] as number) > at) end--;
    let count = 0;
    for (let k = end - 1; k >= 0 && count < out.length; k--) out[count++] = items[k] as number;
    return count;
  }
}

export class ReachIndex {
  /** Function node → the nodes that reach it. */
  private readonly reachers = new JoinedLists<number>();
  /** Test (or caller) node → the nodes it reaches. */
  private readonly reaches = new JoinedLists<number>();
  /** File → its functions, classes and tests. */
  private readonly members = new JoinedLists<string>();
  /** File → its streaming events (store indices). */
  private readonly events = new JoinedLists<string>();
  private readonly seen = new Set<number>();
  private synced = 0;

  constructor(private readonly model: CockpitModel) {}

  /** Indexes events appended since the last call. */
  sync(): void {
    const { store, graph } = this.model;
    for (let i = this.synced; i < store.length; i++) {
      const event = store.event(i);
      if (event === null) continue;
      if (event.kind === "graph.node") {
        const node = graph.byId.get(event.payload.node.id);
        if (node !== undefined && event.payload.node.type !== "module")
          this.members.add(event.payload.node.file, node, i);
        continue;
      }
      if (event.kind === "graph.edge") {
        const { type } = event.payload;
        if (type !== "covers" && type !== "calls") continue;
        const source = graph.byId.get(event.payload.source);
        const target = graph.byId.get(event.payload.target);
        if (source !== undefined && target !== undefined) this.link(source, target, i);
        continue;
      }
      if (event.kind === "trace.sample" || event.kind === "diff.behaviour") {
        const test = event.target?.test;
        const source = test === undefined ? undefined : graph.byId.get(test);
        const target = graph.nodeForSymbol(event.payload.symbol_id);
        if (source !== undefined && target !== undefined) this.link(source, target, i);
      }
      if (streams(event)) {
        const file = eventFile(this.model, event);
        if (file !== undefined) this.events.add(file, i, i);
      }
    }
    this.synced = store.length;
  }

  private link(source: number, target: number, index: number): void {
    if (source === target) return;
    // A pair key: node indices stay far below 2^21 for any graph the stage can draw.
    const key = target * 2_097_152 + source;
    if (this.seen.has(key)) return;
    this.seen.add(key);
    this.reachers.add(target, source, index);
    this.reaches.add(source, target, index);
  }

  /** Appends the nodes that had reached function `target` by store index `at`. */
  reachersOf(target: number, at: number, skip: number, out: Int32Array, n: number): number {
    return this.reachers.collect(target, at, skip, out, n);
  }

  /** Appends the nodes `source` (a test) had reached by store index `at`. */
  reachedBy(source: number, at: number, skip: number, out: Int32Array, n: number): number {
    return this.reaches.collect(source, at, skip, out, n);
  }

  /** Appends a file's functions, classes and tests known by store index `at`. */
  membersOf(file: string, at: number, skip: number, out: Int32Array, n: number): number {
    return this.members.collect(file, at, skip, out, n);
  }

  /** Writes a file's most recent streaming events up to store index `at`, newest first. */
  recentEvents(file: string, at: number, out: Int32Array): number {
    return this.events.latest(file, at, out);
  }
}
