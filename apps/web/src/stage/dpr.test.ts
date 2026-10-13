import { describe, expect, it } from "vitest";
import { AdaptiveDpr, dprLevels, FRAME_BUDGET_MS } from "./dpr";

const VSYNC = FRAME_BUDGET_MS;

/** Feeds `windows` windows of `size` intervals each; every `missEvery`-th frame takes two vsyncs. */
function feed(dpr: AdaptiveDpr, windows: number, missEvery: number, size = 90): number[] {
  const seen: number[] = [];
  for (let w = 0; w < windows; w++) {
    for (let i = 0; i < size; i++) {
      dpr.sample(missEvery > 0 && i % missEvery === 0 ? 2 * VSYNC : VSYNC + 0.4);
    }
    seen.push(dpr.dpr);
  }
  return seen;
}

describe("dprLevels", () => {
  it("caps at 2 and steps through 1.5 and 1", () => {
    expect(dprLevels(3)).toEqual([2, 1.5, 1]);
    expect(dprLevels(1.75)).toEqual([1.75, 1.5, 1]);
    expect(dprLevels(1.25)).toEqual([1.25, 1]);
    expect(dprLevels(1)).toEqual([1]);
    expect(dprLevels(0.5)).toEqual([1]);
  });
});

describe("AdaptiveDpr", () => {
  it("ignores vsync jitter (p95 ≈ 18 ms on an idle stage)", () => {
    const dpr = new AdaptiveDpr({ device: 2, warmup: 0 });
    for (let i = 0; i < 900; i++) dpr.sample(i % 10 === 0 ? 18.2 : 16.6);
    expect(dpr.dpr).toBe(2);
  });

  it("steps down when frames are visibly dropped, one level per window", () => {
    const dpr = new AdaptiveDpr({ device: 2, warmup: 0 });
    expect(feed(dpr, 3, 10)).toEqual([1.5, 1, 1]); // 10% of frames take two refreshes
  });

  it("ignores the warm-up frames", () => {
    const dpr = new AdaptiveDpr({ device: 2, warmup: 90 });
    for (let i = 0; i < 90; i++) dpr.sample(200); // loading
    expect(feed(dpr, 2, 0)).toEqual([2, 2]);
  });

  it("probes back up after enough good windows, and backs off when the probe fails", () => {
    const dpr = new AdaptiveDpr({ device: 2, warmup: 0, recoverAfter: 2 });
    feed(dpr, 1, 5); // drop to 1.5
    expect(dpr.dpr).toBe(1.5);
    expect(feed(dpr, 2, 0)).toEqual([1.5, 2]); // two good windows → probe 2
    expect(feed(dpr, 1, 5)).toEqual([1.5]); // the probe drops frames → back down
    // The next probe now needs twice as many good windows (4).
    expect(feed(dpr, 4, 0)).toEqual([1.5, 1.5, 1.5, 2]);
  });

  it("never goes below 1 or above the display's ratio", () => {
    const low = new AdaptiveDpr({ device: 1, warmup: 0 });
    feed(low, 5, 3);
    expect(low.dpr).toBe(1);
    const high = new AdaptiveDpr({ device: 1.25, warmup: 0, recoverAfter: 1 });
    feed(high, 10, 0);
    expect(high.dpr).toBe(1.25);
  });
});
