import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { FrameStats, type Percentiles, RollingSamples } from "./stats";

const blank = (): Percentiles => ({ p50: 0, p95: 0, p99: 0 });

function reference(values: number[], p: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)] as number;
}

describe("RollingSamples", () => {
  it("gives nearest-rank percentiles of the most recent `capacity` samples", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 64 }),
        fc.array(fc.double({ min: 0, max: 100, noNaN: true }), { minLength: 1, maxLength: 200 }),
        (capacity, values) => {
          const samples = new RollingSamples(capacity);
          for (const v of values) samples.push(v);
          const recent = values.slice(-capacity);
          const out = samples.percentiles(blank());
          expect(samples.count).toBe(recent.length);
          expect(out).toEqual({
            p50: reference(recent, 50),
            p95: reference(recent, 95),
            p99: reference(recent, 99),
          });
        },
      ),
    );
  });

  it("reports NaN when empty and can be cleared", () => {
    const samples = new RollingSamples(4);
    expect(Number.isNaN(samples.percentiles(blank()).p50)).toBe(true);
    samples.push(3);
    samples.clear();
    expect(samples.count).toBe(0);
  });

  it("writes into the caller's object instead of allocating a result", () => {
    const samples = new RollingSamples(8);
    samples.push(1);
    const out = blank();
    expect(samples.percentiles(out)).toBe(out);
  });
});

describe("FrameStats", () => {
  it("derives intervals from frame starts and keeps CPU time separately", () => {
    const stats = new FrameStats(16);
    const starts = [0, 16, 33, 50, 100];
    for (const start of starts) stats.record(start, 2);
    const report = stats.summarise();
    expect(report.frames).toBe(5);
    expect(report.interval.p50).toBe(17);
    expect(report.interval.p99).toBe(50);
    expect(report.cpu).toEqual({ p50: 2, p95: 2, p99: 2 });
    expect(stats.summarise()).toBe(report); // the same object, refreshed
    stats.reset();
    expect(stats.summarise().frames).toBe(0);
  });
});
