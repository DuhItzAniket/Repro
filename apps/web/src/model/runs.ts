/**
 * Test runs and traced observations as append-only tables (indexed state, like GraphIndex):
 * each entry records the store index of the events that started and finished it, so the
 * panels can ask "as of cursor k" without folding.
 */
import type { Side, TestOutcome } from "@repro/events";
import type { EventStore } from "./store";

export interface TestRun {
  readonly test: string;
  readonly side: Side;
  readonly attempt: number;
  /** Store index of `test.started`. */
  readonly started: number;
  /** Store index of `test.finished`, or -1 while running. */
  finished: number;
  outcome: TestOutcome | null;
  durationMs: number;
}

export class TestIndex {
  readonly runs: TestRun[] = [];
  private readonly open = new Map<string, number>();
  private synced = 0;

  constructor(private readonly store: EventStore) {}

  sync(): void {
    for (let i = this.synced; i < this.store.length; i++) {
      const event = this.store.event(i);
      if (event?.kind !== "test.started" && event?.kind !== "test.finished") continue;
      const test = event.target?.test;
      if (test === undefined) continue;
      const { side, attempt } = event.payload;
      const key = `${side}|${attempt}|${test}`;
      if (event.kind === "test.started") {
        this.open.set(key, this.runs.length);
        this.runs.push({
          test,
          side,
          attempt,
          started: i,
          finished: -1,
          outcome: null,
          durationMs: 0,
        });
        continue;
      }
      const open = this.open.get(key);
      const run = open === undefined ? undefined : this.runs[open];
      if (run === undefined) {
        // A finish without a start: record it as instantaneous.
        this.runs.push({
          test,
          side,
          attempt,
          started: i,
          finished: i,
          outcome: event.payload.outcome,
          durationMs: event.payload.duration_ms,
        });
      } else {
        run.finished = i;
        run.outcome = event.payload.outcome;
        run.durationMs = event.payload.duration_ms;
        this.open.delete(key);
      }
    }
    this.synced = this.store.length;
  }
}

export interface Observation {
  /** Store index of the `trace.sample`. */
  readonly index: number;
  readonly cell: number;
  readonly side: Side;
  readonly call: number;
  readonly result: string | null;
  readonly raised: string | null;
}

export interface Cell {
  readonly test: string;
  readonly symbol: string;
  /** Module of the symbol (`module:qualname#n` → module). */
  readonly module: string;
}

/** Every traced (test, function) pair and every sample, in arrival order. */
export class ObservationIndex {
  readonly cells: Cell[] = [];
  readonly samples: Observation[] = [];
  private readonly byKey = new Map<string, number>();
  private synced = 0;

  constructor(private readonly store: EventStore) {}

  cellOf(test: string, symbol: string): number | undefined {
    return this.byKey.get(`${test}|${symbol}`);
  }

  sync(): void {
    for (let i = this.synced; i < this.store.length; i++) {
      const event = this.store.event(i);
      if (event?.kind !== "trace.sample") continue;
      const test = event.target?.test;
      if (test === undefined) continue;
      const symbol = event.payload.symbol_id;
      const key = `${test}|${symbol}`;
      let cell = this.byKey.get(key);
      if (cell === undefined) {
        cell = this.cells.length;
        this.byKey.set(key, cell);
        this.cells.push({ test, symbol, module: symbol.slice(0, symbol.indexOf(":")) });
      }
      this.samples.push({
        index: i,
        cell,
        side: event.payload.side,
        call: event.payload.call_index,
        result: event.payload.result_preview,
        raised: event.payload.raised,
      });
    }
    this.synced = this.store.length;
  }
}
