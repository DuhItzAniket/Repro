import { STRESS } from "@repro/synth";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { kindCode, UNKNOWN_KIND } from "./codes";
import { EventStore } from "./store";
import { renumber, runEvents, storeOf } from "./test-support";

const demo = runEvents();

describe("EventStore", () => {
  it("ingests the demo run into columns", () => {
    const store = storeOf(demo);
    expect(store.length).toBe(demo.length);
    expect(store.runId).toBe(demo[0]?.run_id);
    expect(store.version).toBe(demo.length);
    expect(store.unknownCount).toBe(0);
    for (let i = 0; i < store.length; i++) {
      const event = demo[i];
      if (event === undefined) throw new Error("unreachable");
      expect(store.seq[i]).toBe(event.seq);
      expect(store.kind[i]).toBe(kindCode(event.kind, event.pv));
      expect(store.event(i)).toBe(event);
    }
    const origin = Date.parse(demo[0]?.ts ?? "");
    expect(store.origin).toBe(origin);
    expect(store.endTime).toBe(Date.parse(demo.at(-1)?.ts ?? "") - origin);
  });

  it("grows past its initial capacity (stress run, 18.5k events)", () => {
    const events = runEvents(STRESS);
    const store = storeOf(events);
    expect(store.length).toBe(events.length);
    expect(store.seq[events.length - 1]).toBe(events.length);
  });

  it("ignores duplicates and stops at a gap so the transport can resync", () => {
    const store = new EventStore();
    expect(store.appendAll(demo.slice(0, 10)).appended).toBe(10);
    expect(store.append(demo[4])).toEqual({ status: "duplicate", seq: 5 });
    const summary = store.appendAll([demo[8], demo[9], demo[10], demo[12], demo[13]]);
    expect(summary).toEqual({
      appended: 1,
      duplicates: 2,
      stopped: { status: "gap", expected: 12, got: 13 },
    });
    expect(store.length).toBe(11);
  });

  it("rejects what it cannot hold", () => {
    const store = storeOf(demo.slice(0, 1));
    const next = demo[1] as object;
    const reject = (value: unknown) => store.append(value);
    expect(reject([1, 2])).toMatchObject({ status: "rejected" });
    expect(reject({ ...next, v: 2 })).toEqual({
      status: "rejected",
      reason: "unsupported envelope version 2",
    });
    expect(reject({ ...next, run_id: "run_OTHER" })).toMatchObject({ status: "rejected" });
    expect(reject({ ...next, ts: "yesterday" })).toMatchObject({ status: "rejected" });
    expect(reject({ ...next, stage: "deploy" })).toMatchObject({ status: "rejected" });
    expect(reject({ ...next, payload: null })).toMatchObject({ status: "rejected" });
    expect(store.length).toBe(1);
  });

  it("keeps unknown kinds and unsupported payload versions without interpreting them", () => {
    const events = renumber([
      ...demo.slice(0, 3),
      { ...(demo[3] as object), kind: "future.kind" },
      { ...(demo[4] as object), pv: 2 },
      ...demo.slice(5, 8),
    ]);
    const store = storeOf(events);
    expect(store.length).toBe(8);
    expect(store.unknownCount).toBe(2);
    expect(store.kind[3]).toBe(UNKNOWN_KIND);
    expect(store.kind[4]).toBe(UNKNOWN_KIND);
    expect(store.event(3)).toBeNull();
    expect(store.envelope(3).kind).toBe("future.kind");
  });

  it("keeps presentation time monotone when timestamps go backwards", () => {
    const events = renumber(demo.slice(0, 6)).map((event, i) =>
      i === 3 ? { ...event, ts: "2026-10-13T08:59:59.000Z" } : event,
    );
    const store = storeOf(events);
    expect(store.time[3]).toBe(store.time[2]);
    for (let i = 1; i < store.length; i++) {
      expect(store.time[i]).toBeGreaterThanOrEqual(store.time[i - 1] as number);
    }
  });

  it("finds cursors by time exactly like a linear scan", () => {
    const store = storeOf(demo);
    const end = store.endTime;
    fc.assert(
      fc.property(fc.double({ min: -1000, max: end + 1000, noNaN: true }), (t) => {
        let atOrBefore = 0;
        let firstAfter = store.length;
        for (let i = 0; i < store.length; i++) {
          if ((store.time[i] as number) <= t) atOrBefore = i + 1;
          if (firstAfter === store.length && (store.time[i] as number) >= t) firstAfter = i;
        }
        expect(store.cursorAt(t)).toBe(atOrBefore);
        expect(store.firstAtOrAfter(t)).toBe(firstAfter);
      }),
      { numRuns: 200 },
    );
  });
});
