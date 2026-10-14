// B10: wall-clock motion, the flash governor, reduced motion, and "scrub = play" for the stage.
import { readFileSync } from "node:fs";
import { beforeAll, describe, expect, it } from "vitest";
import { SPEEDS } from "../model/clock";
import { CockpitModel } from "../model/cockpit";
import { parseJsonl } from "../model/jsonl";
import { runEvents } from "../model/test-support";
import { type Motion, NORMAL_MOTION } from "../motion/motion";
import { computeLayout, type Ring } from "../shell/layout";
import { viewRing } from "./camera";
import { webRadius } from "./geometry";
import {
  FLASH_BUDGET,
  FLASH_WINDOW_MS,
  FlashGovernor,
  type OnsetLog,
  WCAG_FLASH_AREA,
} from "./governor";
import { hashRenderModels } from "./instances";
import type { StageFrame, StageLayer } from "./layer";
import { clampLook, DEFAULT_LOOK, LOOK_SPECS, type Look } from "./look";
import { AtlasService } from "./ring/atlas-service";
import { RingModel, ringLayers, rotationAt } from "./ring/layers";
import { easeOutCubic, RING_DRIFT, SNAP_MS } from "./ring/rotation";
import { streams } from "./streams/style";
import { arcPieces, edgeHash } from "./web/arcs";
import { BUNDLE_MS, bundleLayer, edgeLayer, pinArea, strandArea, webLayers } from "./web/layers";
import { computeInline, LayoutService } from "./web/layout-service";

const { stage, ring } = computeLayout(1440, 900);

function load(events: readonly unknown[]): { model: CockpitModel; layout: LayoutService } {
  const model = new CockpitModel();
  model.ingest(events);
  return { model, layout: new LayoutService(model.graph, computeInline) };
}
const demo = load(runEvents());
const stress = load(
  parseJsonl(readFileSync(new URL("../../fixtures/stress-run.jsonl", import.meta.url), "utf8"))
    .values,
);
beforeAll(async () => {
  await Promise.all([demo.layout.request(), stress.layout.request()]);
}, 60_000);

const frameOf = (
  model: CockpitModel,
  t: number,
  motion: Motion = NORMAL_MOTION,
  view: { ring?: Ring; look?: Look } = {},
): StageFrame => ({
  t,
  cursor: model.store.cursorAt(t),
  width: stage.w,
  height: stage.h,
  ring: view.ring ?? ring,
  motion,
  ...(view.look === undefined ? {} : { look: view.look }),
});
/** The whole wheel (B15's view at zoom 1) on the same stage. */
const whole = viewRing(ring, stage.w, stage.h, 1);
const at = (speed: number): Motion => ({ speed, reduced: false });
const ringOf = (model: CockpitModel) =>
  new RingModel(model, new AtlasService(() => Promise.resolve(null)));

/** The largest admitted area rising within any window of `window` ms (brute force). */
function worstWindow(log: OnsetLog, window: number): number {
  let worst = 0;
  for (let j = 0; j < log.time.length; j++) {
    const from = log.time[j] as number;
    let sum = 0;
    for (let k = j; k < log.time.length && (log.time[k] as number) < from + window; k++)
      sum += log.area[k] as number;
    worst = Math.max(worst, sum);
  }
  return worst;
}

/** A governor with the ring, so it decides bunches as the app does. */
function governed(
  run: { model: CockpitModel; layout: LayoutService },
  speed: number,
  view: { ring?: Ring; look?: Look } = {},
) {
  const wheel = ringOf(run.model);
  wheel.sync();
  const governor = new FlashGovernor(run.model, run.layout, FLASH_BUDGET, wheel);
  governor.prepare(frameOf(run.model, 0, at(speed), view));
  return governor;
}

describe("flash governor (ADR-0011, WCAG 2.3.1)", () => {
  it("keeps a margin below the WCAG flashing area", () => {
    expect(WCAG_FLASH_AREA).toBe(341 * 256);
    expect(FLASH_BUDGET).toBeLessThan(WCAG_FLASH_AREA);
  });

  it("never lets more than the budget rise in any 333 ms of wall-clock time, at any speed", () => {
    for (const run of [demo, stress])
      for (const speed of SPEEDS) {
        const { onsets } = governed(run, speed);
        expect(onsets.time.length).toBeGreaterThan(0);
        expect(worstWindow(onsets, FLASH_WINDOW_MS * speed)).toBeLessThanOrEqual(FLASH_BUDGET);
      }
  });

  it("holds the ×16 stress burst under the threshold by dropping what does not fit", () => {
    // In the whole-wheel view (B15), where strands are short enough for some bunches to fit; in
    // the arc view they come from all over the disc and none fits at ×16 (the bound still holds).
    const governor = governed(stress, 16, { ring: whole });
    const { store } = stress.model;
    let streaming = 0;
    let drawn = 0;
    for (let i = 0; i < store.length; i++) {
      const event = store.event(i);
      if (event === null || !streams(event)) continue;
      streaming++;
      if (governor.bundle(i)) drawn++;
    }
    expect(drawn).toBeGreaterThan(0);
    expect(drawn).toBeLessThan(streaming); // the burst exceeds the budget at ×16
    const worst = worstWindow(governor.onsets, FLASH_WINDOW_MS * 16);
    expect(worst).toBeLessThanOrEqual(FLASH_BUDGET);
    expect(worst / WCAG_FLASH_AREA).toBeLessThan(0.5 + 1e-9);
  });

  it("holds the cap in every view and at every width the viewer can choose (B15)", () => {
    const widest = clampLook({
      parts: {
        bullets: { width: LOOK_SPECS.bullets.width.max },
        mesh: { width: LOOK_SPECS.mesh.width.max },
      },
    });
    for (const run of [demo, stress])
      for (const view of [ring, viewRing(ring, stage.w, stage.h, 0.5), whole])
        for (const look of [DEFAULT_LOOK, widest])
          for (const speed of [1, 16]) {
            const { onsets } = governed(run, speed, { ring: view, look });
            expect(worstWindow(onsets, FLASH_WINDOW_MS * speed)).toBeLessThanOrEqual(FLASH_BUDGET);
          }
  });

  it("counts wider bullets and arcs as more area, and re-decides when the widths change (B15)", () => {
    // The bounds grow with the width.
    expect(strandArea(300, 2)).toBeGreaterThan(strandArea(300));
    expect(pinArea(8, 2)).toBeGreaterThan(pinArea(8));
    // Re-preparing with another width re-decides from the start.
    const governor = governed(demo, 1, { ring: whole });
    const before = governor.version;
    governor.prepare(
      frameOf(demo.model, 0, at(1), {
        ring: whole,
        look: clampLook({ parts: { bullets: { width: 2 } } }),
      }),
    );
    expect(governor.version).toBeGreaterThan(before);
  });

  it("decides the same however the log arrives (pure in the events, speed and geometry)", () => {
    const events = runEvents();
    const model = new CockpitModel();
    const layout = { positions: demo.layout.positions, version: 1 };
    const governor = new FlashGovernor(model, layout);
    for (let i = 0; i < events.length; i += 61) {
      model.ingest(events.slice(i, i + 61));
      governor.prepare(frameOf(model, 0, at(4)));
    }
    const whole = new FlashGovernor(demo.model, layout);
    whole.prepare(frameOf(demo.model, 0, at(4)));
    expect(governor.onsets).toEqual(whole.onsets);
  });
});

describe("layers follow the governor and wall-clock time", () => {
  it("draws strands for their wall-clock life, and none under reduced motion", () => {
    const { model, layout } = demo;
    for (const speed of [1, 16]) {
      const wheel = ringOf(model);
      wheel.sync();
      const governor = new FlashGovernor(model, layout, FLASH_BUDGET, wheel);
      const layer = bundleLayer(model, layout, governor, wheel);
      governor.prepare(frameOf(model, 0, at(speed)));
      // The first bunch admitted at this speed (its section was on screen when it fired).
      let first = 0;
      while (first < model.store.length && !governor.bundle(first)) first++;
      const t0 = model.store.time[first] as number;
      layer.update(frameOf(model, t0 + BUNDLE_MS * speed * 0.5, at(speed)));
      expect(layer.buffers.count).toBeGreaterThan(0);
      layer.update(frameOf(model, t0 + BUNDLE_MS * speed * 0.5, { speed, reduced: true }));
      expect(layer.buffers.count).toBe(0);
    }
  });

  it("writes each edge's flare as the governor decided", () => {
    const { model, layout } = stress;
    const governor = new FlashGovernor(model, layout);
    const layer = edgeLayer(model, layout, governor);
    layer.update(frameOf(model, 0, at(16)));
    // Each edge's pieces on the stage, in edge order, carry its flare decision.
    const positions = layout.positions as Float32Array;
    const radius = webRadius(ring);
    const x = (n: number) => ring.cx + (positions[n * 2] as number) * radius;
    const y = (n: number) => ring.cy + (positions[n * 2 + 1] as number) * radius;
    const flares = layer.buffers.array("flare");
    let i = 0;
    let on = 0;
    let shown = 0;
    for (let e = 0; e < model.graph.edgeCount; e++) {
      const s = model.graph.edgeSource[e] as number;
      const t = model.graph.edgeTarget[e] as number;
      const pieces = arcPieces(x(s), y(s), x(t), y(t), edgeHash(s, t), ring, stage.w, stage.h);
      if (pieces > 0) shown++;
      if (pieces > 0 && governor.edgeFlare(e)) on++;
      for (let k = 0; k < pieces; k++) expect(flares[i++]).toBe(governor.edgeFlare(e) ? 1 : 0);
    }
    expect(i).toBe(layer.buffers.count);
    expect(on).toBeLessThan(shown); // the edges on the stage cannot all flare at ×16
  });

  it("snaps the ring over 500 ms of wall-clock time, and instantly without drift when reduced", () => {
    const ringModel = new RingModel(demo.model, new AtlasService(() => Promise.resolve(null)));
    ringModel.sync();
    // The last snap: no later snap can cut it short, even over 8 s of run time at x16.
    const snap = ringModel.content.focus.at(-1);
    if (snap === undefined) throw new Error("no snap");
    for (const speed of [1, 16]) {
      const motion = at(speed);
      const drift = ringModel.angles.drift / speed; // wall-clock drift, in run time
      const offset = (t: number) => rotationAt(ringModel, t, motion) - drift * t;
      const start = offset(snap.time);
      const end = offset(snap.time + SNAP_MS * speed);
      const half = offset(snap.time + (SNAP_MS * speed) / 2);
      expect((half - start) / (end - start)).toBeCloseTo(easeOutCubic(0.5), 9);
    }
    const reduced = { speed: 1, reduced: true };
    const still = rotationAt(ringModel, snap.time + 1, reduced);
    expect(rotationAt(ringModel, snap.time + 400, reduced)).toBe(still);
  });

  it("turns the ring at the same wall-clock speed at every replay speed (B14)", () => {
    const ringModel = new RingModel(demo.model, new AtlasService(() => Promise.resolve(null)));
    ringModel.sync();
    const last = ringModel.content.focus.at(-1);
    if (last === undefined) throw new Error("no snap");
    for (const speed of SPEEDS) {
      const motion = at(speed);
      const from = last.time + SNAP_MS * speed + 1; // after every snap has settled
      const wallMs = 1_000;
      const turned =
        rotationAt(ringModel, from + wallMs * speed, motion) - rotationAt(ringModel, from, motion);
      expect(turned / wallMs).toBeCloseTo(RING_DRIFT, 12);
    }
  });

  it("draws no strands or outside lines under reduced motion", () => {
    const { model, layout } = demo;
    const wheel = ringOf(model);
    wheel.sync();
    const governor = new FlashGovernor(model, layout, FLASH_BUDGET, wheel);
    const layer = bundleLayer(model, layout, governor, wheel);
    for (const t of [24_000, 25_000, 30_500]) {
      layer.update(frameOf(model, t, { speed: 1, reduced: true }));
      for (const part of [layer, layer.lines, layer.rays]) expect(part.buffers.count).toBe(0);
    }
  });
});

describe("scrubbing gives the same frame as playing (golden)", () => {
  function stageLayers(): StageLayer[] {
    const { model, layout } = demo;
    const ringed = ringLayers(model, new AtlasService(() => Promise.resolve(null)));
    const governor = new FlashGovernor(model, layout, FLASH_BUDGET, ringed.ring);
    return [...webLayers(model, layout, governor, ringed.ring), ...ringed.layers];
  }
  const hashAt = (layers: StageLayer[], t: number, motion: Motion) => {
    for (const layer of layers) layer.update(frameOf(demo.model, t, motion));
    return hashRenderModels(layers.map((layer) => ({ layer: layer.name, buffers: layer.buffers })));
  };
  const CHECKPOINTS = [12_000, 24_500, 30_500, 34_000];

  it("plays at 60 fps to each checkpoint and matches a fresh scrub there, at ×1 and ×16", () => {
    for (const speed of [1, 16]) {
      const motion = at(speed);
      const played = stageLayers();
      const frame = (1000 / 60) * speed;
      let t = 0;
      for (const checkpoint of CHECKPOINTS) {
        for (; t < checkpoint; t += frame) hashAt(played, t, motion);
        expect(hashAt(played, checkpoint, motion)).toBe(hashAt(stageLayers(), checkpoint, motion));
        t = checkpoint;
      }
    }
  }, 60_000); // about 2,900 frames: slow under coverage instrumentation or on a busy runner

  it("is pinned at fixed times and speeds (same on every OS in CI)", () => {
    const pins: Record<string, string> = {};
    for (const speed of [1, 16])
      for (const t of CHECKPOINTS) pins[`x${speed}@${t}`] = hashAt(stageLayers(), t, at(speed));
    expect(pins).toMatchSnapshot();
  });
});
