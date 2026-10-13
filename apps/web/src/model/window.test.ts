import type { EventKind } from "@repro/events";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { renumber, runEvents, storeOf } from "./test-support";
import { KindIndex, WindowIndex } from "./window";

const events = runEvents();
const store = storeOf(events);
const kinds = new KindIndex(store);
kinds.sync();
const window = new WindowIndex(store);
const KINDS: EventKind[] = [
  "log.line",
  "test.finished",
  "trace.sample",
  "verdict.issued",
  "graph.edge",
];

describe("KindIndex", () => {
  it("counts and lists like a linear filter, for any cursor", () => {
    fc.assert(
      fc.property(
        fc.constantFrom(...KINDS),
        fc.integer({ min: 0, max: store.length }),
        fc.nat({ max: 30 }),
        (kind, cursor, k) => {
          const linear = events.slice(0, cursor).flatMap((e, i) => (e.kind === kind ? [i] : []));
          expect(kinds.count(kind, cursor)).toBe(linear.length);
          expect(kinds.last(kind, cursor, k)).toEqual(linear.slice(Math.max(0, linear.length - k)));
        },
      ),
      { numRuns: 300 },
    );
  });

  it("indexes unknown kinds separately and syncs incrementally", () => {
    const mixed = renumber([
      ...events.slice(0, 50),
      { ...(events[50] as object), kind: "future.kind" },
    ]);
    const partial = storeOf(mixed.slice(0, 20));
    const index = new KindIndex(partial);
    index.sync();
    partial.appendAll(mixed.slice(20));
    expect(index.count("unknown", partial.length)).toBe(0);
    index.sync();
    expect(index.count("unknown", partial.length)).toBe(1);
    expect(index.count("log.line", partial.length)).toBe(
      events.slice(0, 50).filter((e) => e.kind === "log.line").length,
    );
  });
});

describe("WindowIndex", () => {
  it("returns exactly the events whose time lies in the window", () => {
    fc.assert(
      fc.property(
        fc.double({ min: 0, max: store.endTime, noNaN: true }),
        fc.double({ min: 0, max: 3000, noNaN: true }),
        (t, span) => {
          const [start, end] = window.active(t, span);
          for (let i = 0; i < store.length; i++) {
            const time = store.time[i] as number;
            expect(i >= start && i < end).toBe(time >= t - span && time <= t);
          }
        },
      ),
      { numRuns: 50 },
    );
  });

  it("returns an empty range for an inverted window", () => {
    expect(window.range(10, 5)).toEqual([0, 0]);
  });
});
