// The GPU-free render-model harness (ADR-0008, B04): layers are pure functions of the event
// store and `t`, so the instance data they would upload is hashed and pinned. The same hashes
// must come out on every run and every OS (CI runs this on Ubuntu and Windows).
import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { computeLayout } from "../shell/layout";
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
const { stage, ring } = computeLayout(1920, 1080);

function renderAt(model: CockpitModel, layers: StageLayer[], t: number): string {
  const frame: StageFrame = {
    t,
    cursor: model.store.cursorAt(t),
    width: stage.w,
    height: stage.h,
    ring,
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
        "0": "de93b396f3b5546f",
        "20000": "ecbeca72d16be9b2",
        "40000": "7661e30554dfc1a9",
        "5000": "6416bdb8608fcac2",
      }
    `);
  });
});
