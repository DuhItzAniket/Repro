/**
 * Folds a projection over the EventStore with periodic snapshots, so any point of a run can be
 * reached by cloning the nearest earlier snapshot and folding at most `every` events. Sequential
 * playback reuses the last result and folds only the new events.
 *
 * Invariant (property-tested): `stateAt(k)` equals a linear fold of the first k events, for any
 * k and any order of calls.
 */
import { cloneState, type Projection } from "./projection";
import type { EventStore } from "./store";

export interface ProjectionError {
  readonly seq: number;
  readonly kind: string;
  readonly message: string;
}

export class Folder<S> {
  /** `snapshots[j]` is the state after the first `(j + 1) * every` events. */
  private readonly snapshots: S[] = [];
  private head: S;
  private headCursor = 0;
  private scratch: { cursor: number; state: S } | null = null;
  private readonly failures = new Map<number, ProjectionError>();

  constructor(
    private readonly store: EventStore,
    readonly projection: Projection<S>,
    readonly every = 256,
  ) {
    if (!Number.isInteger(every) || every < 1) {
      throw new RangeError(`snapshot interval must be ≥ 1, got ${every}`);
    }
    this.head = projection.init();
  }

  /**
   * Events that made the projection throw. They are skipped (the state keeps whatever the
   * projection did before throwing). A malformed event must never take the cockpit down.
   */
  get errors(): readonly ProjectionError[] {
    return [...this.failures.values()];
  }

  get cursor(): number {
    return this.headCursor;
  }

  /** Number of snapshots held (for tests and the perf HUD). */
  get snapshotCount(): number {
    return this.snapshots.length;
  }

  private applyAt(state: S, index: number): S {
    const event = this.store.event(index);
    if (event === null) return state; // unknown kind or payload version: tolerated, not interpreted
    try {
      return this.projection.apply(state, event, { index, time: this.store.time[index] as number });
    } catch (error) {
      this.failures.set(event.seq, {
        seq: event.seq,
        kind: event.kind,
        message: error instanceof Error ? error.message : String(error),
      });
      return state;
    }
  }

  /** Folds events appended since the last call into the head state, snapshotting on the way. */
  sync(): S {
    while (this.headCursor < this.store.length) {
      this.head = this.applyAt(this.head, this.headCursor);
      this.headCursor++;
      if (this.headCursor % this.every === 0) {
        this.snapshots.push(cloneState(this.projection, this.head));
      }
    }
    return this.head;
  }

  /**
   * The state after the first `cursor` events. The returned object is owned by the folder and
   * is only valid until the next call. Read from it, never keep or mutate it.
   */
  stateAt(cursor: number): S {
    this.sync();
    const target = Math.max(0, Math.min(Math.floor(cursor), this.headCursor));
    if (target === this.headCursor) return this.head;
    const scratch = this.scratch;
    if (scratch === null || scratch.cursor > target || target - scratch.cursor > this.every) {
      const j = Math.floor(target / this.every) - 1;
      const base = j >= 0 ? this.snapshots[j] : undefined;
      this.scratch = {
        cursor: base === undefined ? 0 : (j + 1) * this.every,
        state: base === undefined ? this.projection.init() : cloneState(this.projection, base),
      };
    }
    const work = this.scratch as { cursor: number; state: S };
    while (work.cursor < target) {
      work.state = this.applyAt(work.state, work.cursor);
      work.cursor++;
    }
    return work.state;
  }
}
