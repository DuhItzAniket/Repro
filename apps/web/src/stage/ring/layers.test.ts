import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { NORMAL_MOTION } from "../../motion/motion";
import { computeLayout } from "../../shell/layout";
import { hashRenderModels } from "../instances";
import type { StageFrame } from "../layer";
import { AtlasService } from "./atlas-service";
import { cardLayer, RingModel, ringLayers, tickLayer } from "./layers";

const model = new CockpitModel();
model.ingest(runEvents());
const { stage, ring } = computeLayout(1440, 900);
const frameAt = (t: number): StageFrame => ({
  t,
  cursor: model.store.cursorAt(t),
  width: stage.w,
  height: stage.h,
  ring,
  motion: NORMAL_MOTION,
});
const noAtlas = () => new AtlasService(() => Promise.resolve(null));

describe("card layer (B06: one draw call for the cards)", () => {
  it("writes a content card and a metadata card per file into one buffer", () => {
    const ringModel = new RingModel(model, noAtlas());
    const layer = cardLayer(ringModel);
    layer.update(frameAt(0));
    expect(layer.primitive).toBe("cards");
    expect(layer.buffers.count).toBe(ringModel.content.cards.length * 2);
    const times = layer.buffers.array("times");
    ringModel.content.cards.forEach((card, c) => {
      expect([...times.subarray(c * 8, c * 8 + 4)]).toEqual([
        Math.fround(card.appear),
        Math.fround(card.blastAt),
        Math.fround(card.changedAt),
        0,
      ]);
      expect(times[c * 8 + 7]).toBe(1);
    });
  });

  it("rewrites nothing while time passes; only the rotation moves", () => {
    const layer = cardLayer(new RingModel(model, noAtlas()));
    layer.update(frameAt(1_000));
    const version = layer.buffers.version;
    const rotations = [5_000, 20_000, 30_000].map((t) => {
      layer.update(frameAt(t));
      return layer.rotation;
    });
    expect(layer.buffers.version).toBe(version);
    expect(new Set(rotations).size).toBe(3);
  });

  it("requests the atlas once per content, off the frame loop", async () => {
    let builds = 0;
    const atlas = new AtlasService(() => {
      builds++;
      return Promise.resolve(null);
    });
    const { layers } = ringLayers(model, atlas);
    for (const t of [0, 10_000, 20_000]) for (const layer of layers) layer.update(frameAt(t));
    await Promise.resolve();
    expect(builds).toBe(1);
  });
});

describe("tick layer", () => {
  it("draws rims and a scale once; the shader turns it with the ring", () => {
    const ringModel = new RingModel(model, noAtlas());
    const layer = tickLayer(ringModel);
    layer.update(frameAt(20_000));
    const cards = ringModel.content.cards.length;
    expect(layer.buffers.count).toBe(192 * 2 + cards * 5);
    const version = layer.buffers.version;
    const appear = layer.buffers.array("appear");
    expect(appear[0]).toBe(Math.fround(ringModel.firstAppear)); // hidden until the first card
    const rotations = [20_000, 25_000, 30_000].map((t) => {
      layer.update(frameAt(t));
      return layer.rotation;
    });
    expect(layer.buffers.version).toBe(version);
    expect(new Set(rotations).size).toBe(3);
    expect(rotations[1]).toBe(ringModel.rotation.at(25_000));
  });
});

describe("ring render model", () => {
  it("is pinned for the demo run at fixed times (same on every OS in CI)", () => {
    const { layers } = ringLayers(model, noAtlas());
    const hashes = Object.fromEntries(
      [0, 8_000, 20_000, 25_500, 45_000].map((t) => {
        for (const layer of layers) layer.update(frameAt(t));
        const rotation = layers[0]?.rotation ?? 0;
        return [
          t,
          `${hashRenderModels(layers.map((l) => ({ layer: l.name, buffers: l.buffers })))}@${rotation.toFixed(6)}`,
        ];
      }),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "0": "35d133bf64ea368b@0.000000",
        "20000": "35d133bf64ea368b@0.674643",
        "25500": "35d133bf64ea368b@0.403877",
        "45000": "35d133bf64ea368b@1.982273",
        "8000": "35d133bf64ea368b@1.984973",
      }
    `);
  });
});
