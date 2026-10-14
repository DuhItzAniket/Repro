import fc from "fast-check";
import { beforeAll, describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { NORMAL_MOTION } from "../../motion/motion";
import { computeLayout } from "../../shell/layout";
import { webRadius } from "../geometry";
import { FlashGovernor } from "../governor";
import { hashRenderModels } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { AtlasService } from "../ring/atlas-service";
import { RingModel } from "../ring/layers";
import { segmentAlpha } from "../segments";
import { arcPieces, edgeHash } from "./arcs";
import {
  BUNDLE_MS,
  BUNDLE_STEPS,
  bundleLayer,
  EDGE_RECENCY,
  edgeLayer,
  MARKER_SIDES,
  MAX_BUNDLES,
  markerLayer,
  nodeLayer,
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
  motion: NORMAL_MOTION,
});
/** The B05 tests run without the flash governor's cap (B10 tests it). */
const unlimited = (placed: LayoutService) =>
  new FlashGovernor(model, placed, Number.POSITIVE_INFINITY);
const hashOf = (layer: StageLayer) =>
  hashRenderModels([{ layer: layer.name, buffers: layer.buffers }]);
const ringModel = () => new RingModel(model, new AtlasService(() => Promise.resolve(null)));
/** A node's position on the stage. */
const at = (n: number): [number, number] => {
  const positions = layout.positions as Float32Array;
  const radius = webRadius(ring);
  return [
    ring.cx + (positions[n * 2] as number) * radius,
    ring.cy + (positions[n * 2 + 1] as number) * radius,
  ];
};

describe("edge layer", () => {
  it("draws nothing until the layout lands", () => {
    const pending = new LayoutService(model.graph, computeInline);
    const layer = edgeLayer(model, pending, unlimited(pending));
    layer.update(frameAt(40_000));
    expect(layer.buffers.count).toBe(0);
  });

  it("writes each edge's arc once, only its pieces on the stage, stamped with its event's time", () => {
    const layer = edgeLayer(model, layout, unlimited(layout));
    layer.update(frameAt(0));
    const { graph } = model;
    const appear = layer.buffers.array("appear");
    let i = 0;
    let offStage = 0;
    for (let e = 0; e < graph.edgeCount; e++) {
      const s = graph.edgeSource[e] as number;
      const t = graph.edgeTarget[e] as number;
      const pieces = arcPieces(...at(s), ...at(t), edgeHash(s, t), stage.w, stage.h);
      if (pieces === 0) offStage++;
      const time = Math.fround(model.store.time[graph.edgeEvent[e] as number] as number);
      for (let k = 0; k < pieces; k++) expect(appear[i++]).toBe(time);
    }
    expect(layer.buffers.count).toBe(i);
    // Most of the web lies off the stage (the ring's centre is left of it), but not all of it.
    expect(offStage).toBeGreaterThan(0);
    expect(offStage).toBeLessThan(graph.edgeCount);
  });

  it("does not rewrite (or re-upload) between graph events: playback is the shader's job", () => {
    const layer = edgeLayer(model, layout, unlimited(layout));
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
    const layer = markerLayer(model, layout, unlimited(layout));
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
      MARKER_SIDES * (event.payload.changed.length + event.payload.affected.length),
    );
    expect(nodes.has(undefined)).toBe(false);
  });
});

describe("node layer", () => {
  it("draws the tests on the stage as squares, each from its node's event", () => {
    const layer = nodeLayer(model, layout);
    layer.update(frameAt(0));
    const { graph } = model;
    const shown = graph.ids
      .map((_, n) => n)
      .filter((n) => {
        if (graph.nodeTypeName(n) !== "test") return false;
        const [x, y] = at(n);
        return x >= -2.2 && y >= -2.2 && x <= stage.w + 2.2 && y <= stage.h + 2.2;
      });
    expect(shown.length).toBeGreaterThan(0);
    expect(layer.buffers.count).toBe(4 * shown.length);
  });
});

describe("bundle layer (B05: bundles are pure functions of (event, t))", () => {
  it("gives the same render model whatever happened in earlier frames", () => {
    const fresh = () => bundleLayer(model, layout, unlimited(layout), ringModel());
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
    const layer = bundleLayer(model, layout, unlimited(layout), ringModel());
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
    expect(peak).toBeLessThanOrEqual(MAX_BUNDLES * (20 * BUNDLE_STEPS + 1));
  });

  it("lands each finished sheaf on its function's ring card, at the inner rim", () => {
    const rings = ringModel();
    const layer = bundleLayer(model, layout, unlimited(layout), rings);
    let pins = 0;
    for (let t = 20_000; t <= 28_000; t += 100) {
      layer.update(frameAt(t));
      const a = layer.buffers.array("a");
      const b = layer.buffers.array("b");
      const shape = layer.buffers.array("shape");
      for (let i = 0; i < layer.buffers.count; i++) {
        if (shape[i * 2] !== 2) continue; // the bar a sheaf lands on
        pins++;
        const mx = ((a[i * 2] as number) + (b[i * 2] as number)) / 2 - ring.cx;
        const my = ((a[i * 2 + 1] as number) + (b[i * 2 + 1] as number)) / 2 - ring.cy;
        expect(Math.sqrt(mx * mx + my * my)).toBeCloseTo(ring.r - 3, 0);
      }
    }
    expect(pins).toBeGreaterThan(0);
  });

  it("pins the demo run's web at fixed times", async () => {
    const layers = [
      edgeLayer(model, layout, unlimited(layout)),
      nodeLayer(model, layout),
      markerLayer(model, layout, unlimited(layout)),
      bundleLayer(model, layout, unlimited(layout), ringModel()),
    ];
    const hashes = Object.fromEntries(
      [8_000, 22_000, 25_500, 45_000].map((t) => {
        for (const layer of layers) layer.update(frameAt(t));
        return [t, hashRenderModels(layers.map((l) => ({ layer: l.name, buffers: l.buffers })))];
      }),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "22000": "48be897551db5447",
        "25500": "d254aa1421e6cdfa",
        "45000": "48be897551db5447",
        "8000": "d147e84ccf4d6242",
      }
    `);
  });
});
