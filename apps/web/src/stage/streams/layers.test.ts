import { STRESS } from "@repro/synth";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { computeLayout } from "../../shell/layout";
import { hashRenderModels } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { targetFile } from "../ring/content";
import {
  LANE_SPREAD,
  laneAngle,
  MAX_STREAKS,
  type StreakOut,
  streakLayer,
  streakShape,
} from "./layers";
import { lifetime, streams } from "./style";

function modelOf(events: readonly unknown[]): CockpitModel {
  const model = new CockpitModel();
  model.ingest(events);
  return model;
}

const demo = modelOf(runEvents());
const { stage, ring } = computeLayout(1440, 900);
const frameAt = (model: CockpitModel, t: number): StageFrame => ({
  t,
  cursor: model.store.cursorAt(t),
  width: stage.w,
  height: stage.h,
  ring,
});
const hashOf = (layer: StageLayer) =>
  hashRenderModels([{ layer: layer.name, buffers: layer.buffers }]);

describe("streak shape", () => {
  const event = runEvents().find((e) => e.kind === "test.finished");
  if (event === undefined) throw new Error("no test event");
  const out: StreakOut = { angle: 0, from: 0, head: 0, tail: 0, alpha: 0 };
  const at = (age: number) => (streakShape(event, age, 0.1, ring, out) ? { ...out } : null);

  it("eases its head out, fades, and ends with its life", () => {
    const life = lifetime(event);
    const samples = [0, 0.1, 0.3, 0.6, 0.9, 1].map((f) => at(f * life));
    for (let i = 1; i < samples.length; i++) {
      expect(samples[i]?.head).toBeGreaterThanOrEqual(samples[i - 1]?.head ?? 0);
      expect(samples[i]?.alpha).toBeLessThanOrEqual(samples[i - 1]?.alpha ?? 1);
    }
    expect(samples.at(-1)?.alpha).toBe(0);
    expect(at(life + 1)).toBeNull();
    expect(at(-1)).toBeNull();
  });

  it("stretches its tail with its speed: long while fast, short as it slows", () => {
    const life = lifetime(event);
    const early = at(0.15 * life);
    const late = at(0.85 * life);
    if (early === null || late === null) throw new Error("streak ended early");
    expect(early.head - early.tail).toBeGreaterThan(late.head - late.tail);
    expect(early.tail).toBeLessThanOrEqual(early.head);
  });
});

describe("lanes", () => {
  it("fan across the ring's right side, one lane per file", () => {
    const byFile = new Map<string, number[]>();
    for (const event of runEvents()) {
      if (!streams(event)) continue;
      const angle = laneAngle(event);
      expect(Math.abs(angle)).toBeLessThanOrEqual(LANE_SPREAD + 0.03 + 1e-9);
      const file = targetFile(event.target);
      if (file !== undefined) byFile.set(file, [...(byFile.get(file) ?? []), angle]);
    }
    for (const angles of byFile.values())
      expect(Math.max(...angles) - Math.min(...angles)).toBeLessThanOrEqual(0.06 + 1e-9);
  });
});

describe("streak layer (B07: state at any t is reproducible after a scrub)", () => {
  it("gives the same render model whatever happened in earlier frames", () => {
    const reused = streakLayer(demo);
    fc.assert(
      fc.property(fc.integer({ min: 0, max: Math.ceil(demo.store.endTime) }), (t) => {
        const fresh = streakLayer(demo);
        fresh.update(frameAt(demo, t));
        reused.update(frameAt(demo, t));
        expect(hashOf(reused)).toBe(hashOf(fresh));
      }),
      { numRuns: 80 },
    );
  });

  it("draws exactly the streaming events still within their life", () => {
    const layer = streakLayer(demo);
    for (const t of [10_000, 21_000, 30_500, 34_000, 46_000]) {
      layer.update(frameAt(demo, t));
      let expected = 0;
      for (let i = 0; i < demo.store.cursorAt(t); i++) {
        const event = demo.store.event(i);
        if (event === null || !streams(event)) continue;
        const age = t - (demo.store.time[i] as number);
        if (age >= 0 && age <= lifetime(event)) expected++;
      }
      expect(layer.buffers.count).toBe(expected);
    }
  });

  it("caps the stress burst at 2,048 live streaks, keeping the newest", () => {
    const stress = modelOf(runEvents(STRESS));
    const layer = streakLayer(stress);
    let peak = 0;
    for (let t = 20_000; t <= 30_000; t += 100) {
      layer.update(frameAt(stress, t));
      peak = Math.max(peak, layer.buffers.count);
    }
    expect(peak).toBe(MAX_STREAKS);
  });

  it("pins the demo stream at fixed times", () => {
    const layer = streakLayer(demo);
    const hashes = Object.fromEntries(
      [21_000, 30_500, 34_000, 46_000].map((t) => {
        layer.update(frameAt(demo, t));
        return [t, `${hashOf(layer)}/${layer.buffers.count}`];
      }),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "21000": "66d04c6cd55e9a9d/0",
        "30500": "3e62634f811711a5/22",
        "34000": "ff4d1926f1de3e6f/9",
        "46000": "5cbc3b59d499584b/4",
      }
    `);
  });
});
