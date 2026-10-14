// B14: the stream rays (B13's residue): geometry, append-only writes, and why they are not flashes.
import { describe, expect, it } from "vitest";
import { SPEEDS } from "../../model/clock";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { NORMAL_MOTION } from "../../motion/motion";
import { computeLayout } from "../../shell/layout";
import { outerRadius } from "../geometry";
import type { StageFrame } from "../layer";
import { fadeAt, growFactor } from "../segments";
import { laneAngle } from "./layers";
import {
  RAY_FADE_MS,
  RAY_FADE_WALL_MS,
  RAY_GROW_MS,
  RAY_RECENCY,
  rayAlpha,
  residueLayer,
  toEdge,
} from "./residue";
import { streams } from "./style";

const { stage, ring } = computeLayout(1440, 900);
const FRAME: StageFrame = {
  t: 0,
  cursor: 0,
  width: stage.w,
  height: stage.h,
  ring,
  motion: NORMAL_MOTION,
};
const modelOf = (events: readonly unknown[]) => {
  const model = new CockpitModel();
  model.ingest(events);
  return model;
};

describe("stream rays", () => {
  const model = modelOf(runEvents());
  const layer = residueLayer(model);
  layer.update(FRAME);
  const a = layer.buffers.array("a");
  const b = layer.buffers.array("b");

  it("draws one ray per streaming event whose lane starts on the stage, from the outer rim", () => {
    const start = outerRadius(ring) + 2;
    let expected = 0;
    for (let i = 0; i < model.store.length; i++) {
      const event = model.store.event(i);
      if (event === null || !streams(event)) continue;
      const angle = laneAngle(event);
      const x = ring.cx + Math.cos(angle) * start;
      const y = ring.cy + Math.sin(angle) * start;
      if (toEdge(x, y, Math.cos(angle), Math.sin(angle), stage.w, stage.h) > 0) expected++;
    }
    expect(layer.buffers.count).toBe(expected);
    expect(expected).toBeGreaterThan(400);
    for (let i = 0; i < layer.buffers.count; i++) {
      const dx = (a[i * 2] as number) - ring.cx;
      const dy = (a[i * 2 + 1] as number) - ring.cy;
      expect(Math.sqrt(dx * dx + dy * dy)).toBeCloseTo(start, 2);
      // It runs outward along its radius, into the stage.
      const ex = (b[i * 2] as number) - ring.cx;
      const ey = (b[i * 2 + 1] as number) - ring.cy;
      expect(Math.sqrt(ex * ex + ey * ey)).toBeGreaterThan(start);
      expect((b[i * 2] as number) > (a[i * 2] as number)).toBe(true);
    }
  });

  it("only appends: rays already written are not rewritten when events arrive", () => {
    const events = runEvents();
    const growing = modelOf(events.slice(0, 1200));
    const rays = residueLayer(growing);
    rays.update(FRAME);
    const first = rays.buffers.count;
    const before = rays.buffers.array("b").slice(0, first * 2);
    growing.ingest(events.slice(1200));
    rays.update(FRAME);
    expect(rays.buffers.count).toBeGreaterThan(first);
    expect([...rays.buffers.array("b").slice(0, first * 2)]).toEqual([...before]);
  });

  it("draws itself out over 900 ms of wall-clock time, and whole under reduced motion", () => {
    expect(RAY_RECENCY.growMs).toBe(RAY_GROW_MS);
    expect(growFactor(1_000, 1_000 + RAY_GROW_MS / 2, RAY_GROW_MS)).toBeCloseTo(0.5, 12);
    expect(growFactor(1_000, 999, RAY_GROW_MS)).toBe(0);
    expect(growFactor(1_000, 5_000, RAY_GROW_MS)).toBe(1);
    expect(growFactor(1_000, 1_000, 0)).toBe(1); // the host passes 0 under reduced motion
  });
});

/** WCAG relative luminance of an sRGB-encoded grey value (0–1). */
const luminance = (v: number): number => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);

describe("stream rays are not flashes (ADR-0011, B14)", () => {
  const model = modelOf(runEvents());
  const layer = residueLayer(model);
  layer.update(FRAME);

  it("blend with MAX, so overlapping rays never add up", () => {
    expect(layer.blend).toBe("max");
  });

  it("are never brighter than 0.92 at any point", () => {
    const color = layer.buffers.array("color");
    const shape = layer.buffers.array("shape");
    let brightest = 0;
    for (let i = 0; i < layer.buffers.count; i++) {
      const start = (color[i * 4 + 3] as number) * (shape[i * 2 + 1] as number); // alpha at the rim
      brightest = Math.max(brightest, start);
    }
    expect(brightest).toBeLessThanOrEqual(0.92 + 1e-6);
    for (const kind of ["verdict.issued", "test.finished"]) {
      const event = model.store.event(
        model.kinds.lastIndex(kind as "verdict.issued", model.store.length),
      );
      if (event !== null) expect(rayAlpha(event)).toBeLessThanOrEqual(0.92);
    }
  });

  it("fall too slowly for a 10% luminance change within a second, at every speed", () => {
    // The fade never takes less than RAY_FADE_WALL_MS of wall-clock time.
    let fastest = 0;
    for (const speed of SPEEDS) {
      const fadeRun = fadeAt(RAY_RECENCY, speed);
      expect(fadeRun).toBeGreaterThanOrEqual(RAY_FADE_MS);
      expect(fadeRun / speed).toBeGreaterThanOrEqual(RAY_FADE_WALL_MS);
      fastest = Math.max(fastest, (0.92 * speed) / fadeRun); // value lost per wall-clock ms
    }
    const perSecond = fastest * 1000;
    expect(perSecond).toBeLessThanOrEqual(0.023 + 1e-9);
    // The smallest fall in encoded value that loses 10% relative luminance, from at most 0.92.
    let smallest = Number.POSITIVE_INFINITY;
    for (let v = 0.92; v > 0.05; v -= 0.001) {
      let w = v;
      while (w > 0 && luminance(v) - luminance(w) < 0.1) w -= 0.0005;
      if (w > 0) smallest = Math.min(smallest, v - w);
    }
    expect(smallest).toBeGreaterThanOrEqual(0.05);
    expect(smallest / perSecond).toBeGreaterThan(2); // seconds: more than two
  });
});
