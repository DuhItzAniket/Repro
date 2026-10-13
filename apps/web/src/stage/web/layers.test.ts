import fc from "fast-check";
import { beforeAll, describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { computeLayout } from "../../shell/layout";
import { hashRenderModels } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { segmentAlpha } from "../segments";
import {
  BUNDLE_MS,
  bundleLayer,
  EDGE_RECENCY,
  edgeLayer,
  MAX_BUNDLES,
  markerLayer,
} from "./layers";
import { computeInline, LayoutService } from "./layout-service";

const model = new CockpitModel();
model.ingest(runEvents());
const layout = new LayoutService(model.graph, computeInline);
const { stage, ring } = computeLayout(1440, 900);
beforeAll(async () => {
  await layout.request();
});

const frameAt = (t: number): StageFrame => ({
  t,
  cursor: model.store.cursorAt(t),
  width: stage.w,
  height: stage.h,
  ring,
});
const hashOf = (layer: StageLayer) =>
  hashRenderModels([{ layer: layer.name, buffers: layer.buffers }]);

describe("edge layer", () => {
  it("draws nothing until the layout lands", () => {
    const pending = new LayoutService(model.graph, computeInline);
    const layer = edgeLayer(model, pending);
    layer.update(frameAt(40_000));
    expect(layer.buffers.count).toBe(0);
  });

  it("writes every edge once, stamped with the time its event appeared", () => {
    const layer = edgeLayer(model, layout);
    layer.update(frameAt(0));
    const { graph } = model;
    expect(layer.buffers.count).toBe(graph.edgeCount);
    const appear = layer.buffers.array("appear");
    for (let e = 0; e < graph.edgeCount; e++) {
      expect(appear[e]).toBe(Math.fround(model.store.time[graph.edgeEvent[e] as number] as number));
    }
  });

  it("does not rewrite (or re-upload) between graph events: playback is the shader's job", () => {
    const layer = edgeLayer(model, layout);
    layer.update(frameAt(1_000));
    const version = layer.buffers.version;
    for (const t of [5_000, 20_000, 48_000, 2_000]) layer.update(frameAt(t));
    expect(layer.buffers.version).toBe(version);
  });

  it("reveals each edge at its event and flares it, as the shader does", () => {
    const appear = 7_010;
    expect(segmentAlpha(0.1, appear, appear - 1, EDGE_RECENCY)).toBe(0);
    expect(segmentAlpha(0.1, appear, appear, EDGE_RECENCY)).toBeCloseTo(0.35, 10);
    expect(segmentAlpha(0.1, appear, appear + 1500, EDGE_RECENCY)).toBeCloseTo(
      0.1 * (1 + 2.5 / Math.E),
      10,
    );
    expect(segmentAlpha(0.1, appear, appear + 60_000, EDGE_RECENCY)).toBeCloseTo(0.1, 6);
  });
});

describe("marker layer", () => {
  it("rings every blast-radius node once the blast is computed", () => {
    const layer = markerLayer(model, layout);
    const blast = model.kinds.lastIndex("blast.computed", model.store.length);
    const at = model.store.time[blast] as number;
    layer.update(frameAt(at - 1));
    expect(layer.buffers.count).toBe(0);
    layer.update(frameAt(at));
    const event = model.store.event(blast);
    if (event?.kind !== "blast.computed") throw new Error("no blast");
    const nodes = new Set(
      [...event.payload.changed, ...event.payload.affected.map((a) => a.symbol_id)].map((s) =>
        model.graph.nodeForSymbol(s),
      ),
    );
    expect(layer.buffers.count).toBe(
      8 * (event.payload.changed.length + event.payload.affected.length),
    );
    expect(nodes.has(undefined)).toBe(false);
  });
});

describe("bundle layer (B05: bundles are pure functions of (event, t))", () => {
  it("gives the same render model whatever happened in earlier frames", () => {
    const fresh = () => bundleLayer(model, layout);
    const reused = fresh();
    fc.assert(
      fc.property(fc.integer({ min: 0, max: Math.ceil(model.store.endTime) }), (t) => {
        const once = fresh();
        once.update(frameAt(t));
        reused.update(frameAt(t));
        expect(hashOf(reused)).toBe(hashOf(once));
      }),
      { numRuns: 60 },
    );
  });

  it("only draws for events within the last 1.2 s, and at most 40 bundles", () => {
    const layer = bundleLayer(model, layout);
    let peak = 0;
    for (let t = 0; t <= model.store.endTime; t += 250) {
      layer.update(frameAt(t));
      peak = Math.max(peak, layer.buffers.count);
      const [start, end] = model.window.active(t, BUNDLE_MS);
      const triggers = Array.from({ length: end - start }, (_, i) =>
        model.store.event(start + i),
      ).filter((e) => e?.kind === "trace.sample" || e?.kind === "diff.behaviour").length;
      if (triggers === 0) expect(layer.buffers.count).toBe(0);
    }
    expect(peak).toBeGreaterThan(0);
    expect(peak).toBeLessThanOrEqual(MAX_BUNDLES * 20 * 10);
  });

  it("pins the demo run's web at fixed times", async () => {
    const layers = [
      edgeLayer(model, layout),
      markerLayer(model, layout),
      bundleLayer(model, layout),
    ];
    const hashes = Object.fromEntries(
      [8_000, 22_000, 25_500, 45_000].map((t) => {
        for (const layer of layers) layer.update(frameAt(t));
        return [t, hashRenderModels(layers.map((l) => ({ layer: l.name, buffers: l.buffers })))];
      }),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "22000": "9d74051c1f051b05",
        "25500": "1b37b47a95d32735",
        "45000": "9d74051c1f051b05",
        "8000": "a7b498742905a6c5",
      }
    `);
  });
});
