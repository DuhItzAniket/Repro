/**
 * Time and kind lookups over the EventStore. Transient visuals (streaks, bundles, ring snaps)
 * are pure functions of the events whose visual window contains `t` (ARCHITECTURE §13), and
 * append-only lists (the feed, waveforms) are prefixes of a per-kind index. Neither needs
 * folding or snapshots: a binary search answers "as of cursor k" directly.
 */
import type { EventKind } from "@repro/events";
import { kindCode, SUPPORTED_PV, UNKNOWN_KIND } from "./codes";
import type { EventStore } from "./store";

/** Half-open index range `[start, end)` into the store. */
export type IndexRange = readonly [start: number, end: number];

export class WindowIndex {
  constructor(private readonly store: EventStore) {}

  /** Events with presentation time in `[from, to]`. */
  range(from: number, to: number): IndexRange {
    if (to < from) return [0, 0];
    return [this.store.firstAtOrAfter(from), this.store.cursorAt(to)];
  }

  /** Events whose visual window `[time, time + span]` contains `t`. */
  active(t: number, span: number): IndexRange {
    return this.range(t - span, t);
  }
}

/** Number of entries of the sorted `list` below `value`. */
function countBelow(list: Int32Array, length: number, value: number): number {
  let lo = 0;
  let hi = length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((list[mid] as number) < value) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** Store indices of every event, grouped by kind, in store order. */
export class KindIndex {
  private readonly lists = new Map<number, { indices: Int32Array; length: number }>();
  private synced = 0;

  constructor(private readonly store: EventStore) {}

  /** Indexes events appended since the last call. */
  sync(): void {
    for (let i = this.synced; i < this.store.length; i++) {
      const code = this.store.kind[i] as number;
      let list = this.lists.get(code);
      if (list === undefined) {
        list = { indices: new Int32Array(256), length: 0 };
        this.lists.set(code, list);
      }
      if (list.length === list.indices.length) {
        const bigger = new Int32Array(list.indices.length * 2);
        bigger.set(list.indices);
        list.indices = bigger;
      }
      list.indices[list.length++] = i;
    }
    this.synced = this.store.length;
  }

  private list(kind: EventKind | "unknown"): { indices: Int32Array; length: number } | undefined {
    return this.lists.get(kind === "unknown" ? UNKNOWN_KIND : kindCode(kind, SUPPORTED_PV));
  }

  /** How many events of `kind` sit before `cursor` (store index, exclusive). */
  count(kind: EventKind | "unknown", cursor: number): number {
    const list = this.list(kind);
    return list === undefined ? 0 : countBelow(list.indices, list.length, cursor);
  }

  /** Store indices of the last `k` events of `kind` before `cursor`, oldest first. */
  last(kind: EventKind | "unknown", cursor: number, k: number): number[] {
    const list = this.list(kind);
    if (list === undefined) return [];
    const end = countBelow(list.indices, list.length, cursor);
    const out: number[] = [];
    for (let i = Math.max(0, end - k); i < end; i++) out.push(list.indices[i] as number);
    return out;
  }
}
