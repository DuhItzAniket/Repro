import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { cockpitProjection } from "./cockpit";
import { Folder } from "./folder";
import { cloneState, type Projection } from "./projection";
import { linearFold, runEvents, storeOf } from "./test-support";

const store = storeOf(runEvents());
const n = store.length;
const full = linearFold(store, cockpitProjection, n);

describe("Folder (B02 acceptance)", () => {
  it("fold(all) == fold(snapshot_k) + rest, for any k", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: n }), (k) => {
        let state = cloneState(cockpitProjection, linearFold(store, cockpitProjection, k));
        for (let i = k; i < n; i++) {
          const event = store.event(i);
          if (event === null) continue;
          state = cockpitProjection.apply(state, event, {
            index: i,
            time: store.time[i] as number,
          });
        }
        expect(state).toEqual(full);
      }),
      { numRuns: 60 },
    );
  });

  it("random seeks equal a linear fold, whatever the snapshot interval and order of calls", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 700 }),
        fc.array(fc.integer({ min: 0, max: n }), { minLength: 1, maxLength: 12 }),
        (every, cursors) => {
          const folder = new Folder(store, cockpitProjection, every);
          for (const k of cursors) {
            expect(structuredClone(folder.stateAt(k))).toEqual(
              linearFold(store, cockpitProjection, k),
            );
          }
        },
      ),
      { numRuns: 40 },
    );
  });

  it("sequential playback folds only new events from the last result", () => {
    const folder = new Folder(store, cockpitProjection, 256);
    let applied = 0;
    const counting: Projection<unknown> = {
      name: "counting",
      init: () => null,
      apply: (state) => {
        applied++;
        return state;
      },
    };
    const countingFolder = new Folder(store, counting, 256);
    countingFolder.sync();
    applied = 0;
    for (let k = 0; k <= 1000; k += 7) countingFolder.stateAt(k);
    expect(applied).toBeLessThanOrEqual(1000); // a fresh fold per call would be ~70k applies
    expect(folder.stateAt(n)).toEqual(full);
    expect(folder.snapshotCount).toBe(Math.floor(n / 256));
  });

  it("clamps cursors to the data", () => {
    const folder = new Folder(store, cockpitProjection);
    expect(structuredClone(folder.stateAt(-5))).toEqual(cockpitProjection.init());
    expect(folder.stateAt(n + 100)).toEqual(full);
  });

  it("records a throwing projection's errors and keeps folding", () => {
    const fragile: Projection<{ seen: number }> = {
      name: "fragile",
      init: () => ({ seen: 0 }),
      apply: (state, event) => {
        if (event.kind === "claim.extracted") throw new Error("boom");
        state.seen++;
        return state;
      },
    };
    const folder = new Folder(store, fragile, 64);
    const claims = runEvents().filter((e) => e.kind === "claim.extracted").length;
    expect(folder.sync().seen).toBe(n - claims);
    folder.stateAt(10); // re-folding the same events must not duplicate errors
    expect(folder.errors).toHaveLength(claims);
    expect(folder.errors[0]).toMatchObject({ kind: "claim.extracted", message: "boom" });
  });

  it("rejects a snapshot interval below 1", () => {
    expect(() => new Folder(store, cockpitProjection, 0)).toThrow(RangeError);
  });
});
