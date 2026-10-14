// B12 allocation gate: the cockpit's frame work must not grow the heap (no leaks), and the stage
// layers must stay within a per-frame allocation budget. REPRO_INJECT=alloc injects a leak, which
// the first test must catch (CI runs that as a self-test of the gate).
import { readFileSync } from "node:fs";
import v8 from "node:v8";
import vm from "node:vm";
import { beforeAll, describe, expect, it } from "vitest";
import { parseJsonl } from "../model/jsonl";
import { type Pipeline, pipeline } from "./pipeline";

v8.setFlagsFromString("--expose-gc");
const gc = vm.runInNewContext("gc") as () => void;

/** Retained-heap growth allowed over 1,000 frames after warm-up: about 0.5 kB a frame. */
const LEAK_BUDGET_BYTES = 512 * 1024;
/**
 * Bytes the stage layers may allocate per frame at the stress burst, once optimised. They
 * allocate no objects; what remains is V8 boxing doubles at calls it does not inline (about
 * 22 kB a frame, measured in B12 with 2,048 live streaks, since removed). New per-event objects
 * would exceed it.
 */
const STAGE_ALLOC_BUDGET = 40 * 1024;
const FRAMES = 1000;
/** V8's cumulative allocation counter, where this Node exposes it (@types/node 24 does not declare it). */
const allocatedBytes = (): number | undefined =>
  (v8.getHeapStatistics() as unknown as { total_allocated_bytes?: number }).total_allocated_bytes;
const FRAME_MS = 1000 / 60;

let run: Pipeline;
beforeAll(async () => {
  const text = readFileSync(new URL("../../fixtures/stress-run.jsonl", import.meta.url), "utf8");
  run = await pipeline(parseJsonl(text).values);
}, 120_000);

/** Playback through the burst, looping over 5 s of run time. */
const timeOf = (k: number) => run.burst - 400 + (k % 300) * FRAME_MS;

/** Live memory after a full collection: the JS heap plus ArrayBuffer backing stores (typed arrays live outside the heap). */
const usedAfterGc = () => {
  gc();
  gc();
  const { heapUsed, arrayBuffers } = process.memoryUsage();
  return heapUsed + arrayBuffers;
};

describe("allocation gate (B12)", () => {
  it("keeps the heap flat over 1,000 frames of the stress burst", () => {
    const leaked: Float64Array[] = [];
    const inject = process.env.REPRO_INJECT === "alloc";
    const frame = (k: number) => {
      run.frame(timeOf(k));
      if (inject) leaked.push(new Float64Array(256)); // an injected leak: 2 kB a frame
    };
    // Warm up: caches (folded snapshots, routes, ring rotations) fill once, then stay.
    for (let k = 0; k < FRAMES; k++) frame(k);
    const before = usedAfterGc();
    for (let k = 0; k < FRAMES; k++) frame(k);
    const growth = usedAfterGc() - before;
    expect(growth, `retained ${growth} bytes over ${FRAMES} frames`).toBeLessThan(
      LEAK_BUDGET_BYTES,
    );
    expect(leaked.length).toBe(inject ? 2 * FRAMES : 0);
  }, 120_000);

  it.skipIf(allocatedBytes() === undefined)(
    "allocates within budget per stage frame once optimised (where V8 reports allocations)",
    () => {
      for (let k = 0; k < 3 * FRAMES; k++) run.stage(timeOf(k)); // let TurboFan optimise
      const start = allocatedBytes() as number;
      for (let k = 0; k < FRAMES; k++) run.stage(timeOf(k));
      const perFrame = ((allocatedBytes() as number) - start) / FRAMES;
      expect(perFrame, `${Math.round(perFrame)} bytes per frame`).toBeLessThan(STAGE_ALLOC_BUDGET);
    },
    120_000,
  );
});
