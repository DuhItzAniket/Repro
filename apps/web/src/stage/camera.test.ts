// B15: how much of the wheel the stage shows.
import { describe, expect, it } from "vitest";
import { computeLayout } from "../shell/layout";
import { meshDensity, viewRing, WHOLE_MARGIN, wholeRing } from "./camera";
import { outerRadius } from "./geometry";
import { RAY_ROOM } from "./web/layers";

const { stage, ring } = computeLayout(1440, 900);

describe("view ring", () => {
  it("is the layout's arc at zoom 0 and the whole wheel at zoom 1", () => {
    expect(viewRing(ring, stage.w, stage.h, 0)).toBe(ring);
    expect(viewRing(ring, stage.w, stage.h, -1)).toBe(ring);
    expect(viewRing(ring, stage.w, stage.h, 1)).toEqual(wholeRing(stage.w, stage.h));
    expect(viewRing(ring, stage.w, stage.h, 2)).toEqual(wholeRing(stage.w, stage.h));
  });

  it("fits the whole wheel, with room for the lines outside it, inside the stage", () => {
    for (const [w, h] of [
      [stage.w, stage.h],
      [1200, 500],
      [400, 900],
    ] as const) {
      const whole = wholeRing(w, h);
      const reach = outerRadius(whole) + RAY_ROOM * whole.r;
      expect(whole.cx - reach).toBeGreaterThanOrEqual(WHOLE_MARGIN - 1e-9);
      expect(whole.cy - reach).toBeGreaterThanOrEqual(WHOLE_MARGIN - 1e-9);
      expect(whole.cx + reach).toBeLessThanOrEqual(w - WHOLE_MARGIN + 1e-9);
      expect(whole.cy + reach).toBeLessThanOrEqual(h - WHOLE_MARGIN + 1e-9);
    }
  });

  it("zooms out smoothly: the radius shrinks and the centre moves steadily towards the middle", () => {
    let last = viewRing(ring, stage.w, stage.h, 0);
    for (let z = 0.05; z <= 1 + 1e-9; z += 0.05) {
      const next = viewRing(ring, stage.w, stage.h, z);
      expect(next.r).toBeLessThan(last.r);
      expect(next.cx).toBeGreaterThan(last.cx); // the arc's centre is left of the stage
      expect(next.r / last.r).toBeGreaterThan(0.9); // no jumps
      last = next;
    }
  });

  it("dims the mesh as the same arcs crowd a smaller disc, never brightening it", () => {
    expect(meshDensity(ring, ring)).toBe(1);
    const whole = wholeRing(stage.w, stage.h);
    expect(meshDensity(ring, whole)).toBeCloseTo(Math.sqrt(whole.r / ring.r), 12);
    expect(meshDensity(ring, whole)).toBeLessThan(1);
    expect(meshDensity(whole, ring)).toBe(1);
  });
});
