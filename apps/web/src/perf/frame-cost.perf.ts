// B12 performance gate (nightly, and self-tested in CI): the CPU cost of a frame (stage layers,
// callouts, panels) while replaying the stress run's burst at ×1, measured relative to a fixed
// calibration workload timed in the same process, so runner speed largely cancels out. It fails
// when the calibrated p50 or p95 is more than TOLERANCE above the baseline recorded in CI.
//   REPRO_PERF_RECORD=1  writes a new baseline candidate instead of comparing.
//   REPRO_INJECT=perf    adds 2 ms of work to every frame (CI checks that this fails).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parseJsonl } from "../model/jsonl";
import { pipeline } from "./pipeline";

const TOLERANCE = 1.3;
const BASELINE = new URL("../../perf/frame-cost-baseline.json", import.meta.url);
const RESULTS_DIR = new URL("../../perf-results/", import.meta.url);
const FRAME_MS = 1000 / 60;
const WARM_FRAMES = 600;
const ROUNDS = 5;
const ROUND_FRAMES = 300;

interface Measurement {
  readonly p50: number;
  readonly p95: number;
  readonly calibration: number;
  readonly ratioP50: number;
  readonly ratioP95: number;
}

/** A fixed, deterministic CPU workload (floating point and typed arrays, like the layers). */
function calibrate(): number {
  const data = new Float64Array(1 << 16);
  for (let i = 0; i < data.length; i++) data[i] = i * 0.5;
  const start = performance.now();
  let sum = 0;
  for (let pass = 0; pass < 48; pass++) {
    for (let i = 0; i < data.length; i++) {
      const v = Math.sqrt((data[i] as number) * 1.0001 + pass);
      data[i] = v;
      sum += v;
    }
  }
  if (sum === 0) throw new Error("unreachable"); // keeps the loop from being optimised away
  return performance.now() - start;
}

const percentile = (sorted: readonly number[], p: number) =>
  sorted[Math.min(sorted.length - 1, Math.ceil(p * sorted.length) - 1)] as number;
const median = (values: readonly number[]) =>
  percentile(
    [...values].sort((a, b) => a - b),
    0.5,
  );

async function measure(): Promise<Measurement> {
  const text = readFileSync(new URL("../../fixtures/stress-run.jsonl", import.meta.url), "utf8");
  const run = await pipeline(parseJsonl(text).values);
  const inject = process.env.REPRO_INJECT === "perf";
  const timeOf = (k: number) => run.burst - 400 + (k % ROUND_FRAMES) * FRAME_MS;
  const frame = (k: number) => {
    run.frame(timeOf(k));
    if (inject) {
      const until = performance.now() + 2;
      while (performance.now() < until) {
        // an injected regression: 2 ms of extra work per frame
      }
    }
  };
  for (let k = 0; k < WARM_FRAMES; k++) frame(k);
  const samples: number[] = [];
  const calibrations: number[] = [calibrate()];
  for (let round = 0; round < ROUNDS; round++) {
    for (let k = 0; k < ROUND_FRAMES; k++) {
      const start = performance.now();
      frame(k);
      samples.push(performance.now() - start);
    }
    calibrations.push(calibrate());
  }
  samples.sort((a, b) => a - b);
  const p50 = percentile(samples, 0.5);
  const p95 = percentile(samples, 0.95);
  const calibration = median(calibrations);
  return { p50, p95, calibration, ratioP50: p50 / calibration, ratioP95: p95 / calibration };
}

describe("frame-cost gate (B12)", () => {
  it("keeps the calibrated frame cost within 30% of the CI baseline", async () => {
    const m = await measure();
    const report = {
      date: new Date().toISOString(),
      node: process.version,
      platform: `${process.platform}-${process.arch}`,
      ...Object.fromEntries(Object.entries(m).map(([k, v]) => [k, Number(v.toFixed(4))])),
    };
    mkdirSync(RESULTS_DIR, { recursive: true });
    writeFileSync(new URL("frame-cost.json", RESULTS_DIR), `${JSON.stringify(report, null, 2)}\n`);
    if (process.env.REPRO_PERF_RECORD === "1") {
      writeFileSync(
        new URL("frame-cost-baseline.json", RESULTS_DIR),
        `${JSON.stringify(report, null, 2)}\n`,
      );
      return;
    }
    const baseline = JSON.parse(readFileSync(BASELINE, "utf8")) as Measurement;
    const detail = `p50 ${m.p50.toFixed(3)} ms, p95 ${m.p95.toFixed(3)} ms, calibration ${m.calibration.toFixed(2)} ms`;
    expect(m.ratioP50, `calibrated p50 (${detail})`).toBeLessThanOrEqual(
      baseline.ratioP50 * TOLERANCE,
    );
    expect(m.ratioP95, `calibrated p95 (${detail})`).toBeLessThanOrEqual(
      baseline.ratioP95 * TOLERANCE,
    );
  }, 180_000);
});
