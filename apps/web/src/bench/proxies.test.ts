// The GPU-free render-model harness (ADR-0008, B04): layers are pure functions of the event
// store and `t`, so the instance data they would upload is hashed and pinned. The same hashes
// must come out on every run and every OS (CI runs this on Ubuntu and Windows).

import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { NORMAL_MOTION } from "../motion/motion";
import { hashRenderModels } from "../stage/instances";
import { renderModels, type StageFrame, type StageLayer } from "../stage/layer";
import { proxyLayers } from "./proxies";
import { busiestSecond } from "./run";

function modelOf(events: readonly unknown[]): CockpitModel {
  const model = new CockpitModel();
  model.ingest(events);
  return model;
}

const demo = modelOf(runEvents());
const stress = modelOf(runEvents(STRESS));
// A fixed stage and ring (what `computeLayout(1920, 1080)` gave until B13), so these pins track
// the proxy layers alone, not the cockpit's layout.
const stage = { w: 1920, h: 641 };
const ring = { cx: 1920 * 0.46 - 641 * 0.9, cy: 641 / 2, r: 641 * 0.9 };

function renderAt(model: CockpitModel, layers: StageLayer[], t: number): string {
  const frame: StageFrame = {
    t,
    cursor: model.store.cursorAt(t),
    width: stage.w,
    height: stage.h,
    ring,
    motion: NORMAL_MOTION,
  };
  for (const layer of layers) layer.update(frame);
  return hashRenderModels(renderModels(layers));
}

describe("render-model harness on the proxy layers", () => {
  it("finds the stress run's burst", () => {
    const at = busiestSecond(stress);
    const [start, end] = stress.window.range(at, at + 999);
    expect(end - start).toBeGreaterThanOrEqual(2000);
  });

  it("puts 10k edges and a full 2,048-streak load on screen at the burst", () => {
    const layers = proxyLayers(stress);
    const at = busiestSecond(stress);
    let peak = 0;
    for (let t = at; t <= at + 1500; t += 50) {
      renderAt(stress, layers, t);
      peak = Math.max(peak, layers.find((l) => l.name === "streaks")?.buffers.count ?? 0);
    }
    const counts = Object.fromEntries(layers.map((l) => [l.name, l.buffers.count]));
    expect({ ...counts, streaks: peak }).toEqual({
      edges: 10_000,
      cards: 360,
      ticks: 720,
      streaks: 2048,
    });
  });

  it("gives the same hashes on every run, whatever the order of frames", () => {
    const times = [0, 9_000, 20_000, busiestSecond(stress) + 500, stress.store.endTime];
    const forward = times.map((t) => renderAt(stress, proxyLayers(stress), t));
    const shared = proxyLayers(stress);
    const reversed = [...times]
      .reverse()
      .map((t) => renderAt(stress, shared, t))
      .reverse();
    expect(reversed).toEqual(forward);
  });

  it("pins the demo run's render model at fixed times", () => {
    const hashes = Object.fromEntries(
      [0, 5_000, 20_000, 40_000].map((t) => [t, renderAt(demo, proxyLayers(demo), t)]),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "0": "e676e71b4479dc2d",
        "20000": "e810eec9d0a4b151",
        "40000": "1a93fcf31deabd6f",
        "5000": "2663e41913cd1f1b",
      }
    `);
  });
});
