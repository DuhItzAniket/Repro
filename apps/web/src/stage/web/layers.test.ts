import fc from "fast-check";
import { beforeAll, describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { NORMAL_MOTION } from "../../motion/motion";
import { computeLayout } from "../../shell/layout";
import { outerRadius, webRadius } from "../geometry";
import { FlashGovernor } from "../governor";
import { hashRenderModels } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { AtlasService } from "../ring/atlas-service";
import { RingModel } from "../ring/layers";
import { RING_TURN_MS } from "../ring/rotation";
import { segmentAlpha } from "../segments";
import { arcPieces, edgeHash } from "./arcs";
import {
  AIM,
  aimRange,
  BUNDLE_MS,
  BUNDLE_STEPS,
  bulletAt,
  bundleLayer,
  EDGE_RECENCY,
  edgeLayer,
  FADE_FROM,
  FOLLOW,
  landingAngle,
  landingArc,
  MARKER_SIDES,
  MAX_BUNDLES,
  markerLayer,
  nodeLayer,
  pinLength,
  placedBunch,
  sortByBearing,
  strandFade,
  strandOrigin,
  strandReach,
  TRAVEL,
} from "./layers";
import { computeInline, LayoutService } from "./layout-service";
import { MAX_BUNCH } from "./reach";

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
      const pieces = arcPieces(...at(s), ...at(t), edgeHash(s, t), ring, stage.w, stage.h);
      if (pieces === 0) offStage++;
      const time = Math.fround(model.store.time[graph.edgeEvent[e] as number] as number);
      for (let k = 0; k < pieces; k++) expect(appear[i++]).toBe(time);
    }
    expect(layer.buffers.count).toBe(i);
    // Most of the web lies off the stage (the ring's centre is left of it), but not all of it.
    expect(offStage).toBeGreaterThan(0);
    expect(offStage).toBeLessThan(graph.edgeCount);
  });

  it("keeps every arc inside the web's circle, so none leaves the wheel (B14)", () => {
    const layer = edgeLayer(model, layout, unlimited(layout));
    layer.update(frameAt(0));
    const a = layer.buffers.array("a");
    const b = layer.buffers.array("b");
    const limit = webRadius(ring) + 1e-3;
    for (let i = 0; i < layer.buffers.count; i++) {
      for (const [x, y] of [
        [a[i * 2] as number, a[i * 2 + 1] as number],
        [b[i * 2] as number, b[i * 2 + 1] as number],
      ] as const) {
        expect(Math.hypot(x - ring.cx, y - ring.cy)).toBeLessThanOrEqual(limit);
      }
    }
    expect(webRadius(ring)).toBeLessThan(outerRadius(ring)); // under the band
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
  it("draws the run's nodes on the stage as small circles, each from its node's event", () => {
    const layer = nodeLayer(model, layout);
    layer.update(frameAt(0));
    const { graph } = model;
    const shown = graph.ids
      .map((_, n) => n)
      .filter((n) => {
        if (graph.nodeTypeName(n) === "module") return false;
        const [x, y] = at(n);
        return x >= -3.2 && y >= -3.2 && x <= stage.w + 3.2 && y <= stage.h + 3.2;
      });
    // The layout puts symbols and tests in front, so most of them are on the stage.
    const inner = graph.ids.filter((_, n) => graph.nodeTypeName(n) !== "module").length;
    expect(shown.length).toBeGreaterThan(inner * 0.8);
    expect(layer.buffers.count).toBe(8 * shown.length);
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

  it("only draws for events within a strand's life, and at most 40 strands", () => {
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
    expect(peak).toBeLessThanOrEqual(MAX_BUNDLES * (12 * BUNDLE_STEPS + 11));
  });

  it("fires a bunch's first strand from the test's node, which lights up, and keeps it attached", () => {
    const layer = bundleLayer(model, layout, unlimited(layout), ringModel());
    const first = model.kinds.last("trace.sample", model.store.length, 1)[0] as number;
    const t0 = model.store.time[first] as number;
    const a = layer.buffers.array("a");
    const event = model.store.event(first);
    if (event?.kind !== "trace.sample") throw new Error("no trace");
    const origin = strandOrigin(
      model.graph,
      event.target?.test,
      model.graph.nodeForSymbol(event.payload.symbol_id),
    );
    expect(origin).toBe(model.graph.byId.get(event.target?.test ?? ""));
    const [x, y] = at(origin as number);
    const startsAt = (px: number, py: number) => {
      for (let i = 0; i < layer.buffers.count; i++) {
        if (
          Math.abs((a[i * 2] as number) - px) < 1e-3 &&
          Math.abs((a[i * 2 + 1] as number) - py) < 1e-3
        )
          return true;
      }
      return false;
    };
    for (const life of [0.05, 0.2, 0.5, 0.9]) {
      layer.update(frameAt(t0 + life * BUNDLE_MS));
      // The dim strand starts at the node at every age: it stays attached.
      expect(startsAt(x, y)).toBe(true);
      // The node's ring (from (x + 4.5, y)) shows while the bullet is in flight.
      expect(startsAt(x + 4.5, y)).toBe(life < TRAVEL);
    }
  });

  it("fires a bunch from the nodes that reach the function, converging on one section (B14)", () => {
    const governor = unlimited(layout);
    const layer = bundleLayer(model, layout, governor, ringModel());
    const { store, graph } = model;
    const parseDate = graph.byId.get("timekeeper.parse:parse_date#0") as number;
    // The last trace of parse_date: by then many nodes reach it.
    let i = store.length - 1;
    for (; i >= 0; i--) {
      const event = store.event(i);
      if (
        event?.kind === "trace.sample" &&
        graph.nodeForSymbol(event.payload.symbol_id) === parseDate
      )
        break;
    }
    const event = store.event(i);
    if (event?.kind !== "trace.sample") throw new Error("no trace of parse_date");
    governor.prepare(frameAt(0)); // indexes the log, as the first frame does
    const members = new Int32Array(MAX_BUNCH);
    const first = strandOrigin(graph, event.target?.test, parseDate);
    const n = placedBunch(
      governor.reach,
      parseDate,
      i,
      first,
      members,
      layout.positions as Float32Array,
    );
    expect(n).toBeGreaterThan(5);
    const t0 = store.time[i] as number;
    // In flight: every node of the bunch lights up, each the start of its own strand.
    layer.update(frameAt(t0 + 0.05 * BUNDLE_MS));
    const a = layer.buffers.array("a");
    const startsAt = (px: number, py: number) => {
      for (let k = 0; k < layer.buffers.count; k++) {
        if (
          Math.abs((a[k * 2] as number) - px) < 1e-3 &&
          Math.abs((a[k * 2 + 1] as number) - py) < 1e-3
        )
          return true;
      }
      return false;
    };
    const origins = new Set<string>();
    for (let k = 0; k < n; k++) {
      const [x, y] = at(members[k] as number);
      expect(startsAt(x, y)).toBe(true);
      expect(startsAt(x + 4.5, y)).toBe(true);
      origins.add(`${x},${y}`);
    }
    expect(origins.size).toBe(n); // one strand per node, each from its own point
    // Landed: one bar, as long as the bunch is wide, where they all converge.
    layer.update(frameAt(t0 + 0.5 * BUNDLE_MS));
    const b = layer.buffers.array("b");
    const shape = layer.buffers.array("shape");
    const bars: number[] = [];
    for (let k = 0; k < layer.buffers.count; k++) {
      if (shape[k * 2] !== 2 || shape[k * 2 + 1] !== 1) continue;
      bars.push(
        Math.hypot(
          (b[k * 2] as number) - (a[k * 2] as number),
          (b[k * 2 + 1] as number) - (a[k * 2 + 1] as number),
        ),
      );
    }
    expect(bars.some((length) => Math.abs(length - pinLength(n)) < 1e-3)).toBe(true);
  });

  it("orders a bunch by its nodes' bearings, so its strands do not cross where they land", () => {
    const positions = new Float32Array([0.5, 0.3, 0.5, -0.3, 0.5, 0]);
    const members = Int32Array.from([0, 1, 2]);
    sortByBearing(members, 3, positions, new Float64Array(3));
    expect(Array.from(members)).toEqual([1, 2, 0]);
  });

  it("lands each strand on the inner rim, in the landing arc or as far as it has followed the ring", () => {
    const layer = bundleLayer(model, layout, unlimited(layout), ringModel());
    const arc = landingArc(ring, stage.h);
    let pins = 0;
    for (let t = 20_000; t <= 28_000; t += 100) {
      layer.update(frameAt(t));
      const a = layer.buffers.array("a");
      const b = layer.buffers.array("b");
      const shape = layer.buffers.array("shape");
      for (let i = 0; i < layer.buffers.count; i++) {
        if (shape[i * 2] !== 2 || shape[i * 2 + 1] !== 1) continue; // the bar a bullet hits
        pins++;
        const mx = ((a[i * 2] as number) + (b[i * 2] as number)) / 2 - ring.cx;
        const my = ((a[i * 2 + 1] as number) + (b[i * 2 + 1] as number)) / 2 - ring.cy;
        expect(Math.sqrt(mx * mx + my * my)).toBeCloseTo(ring.r - 3, 0);
        expect(Math.abs(Math.atan2(my, mx))).toBeLessThanOrEqual(arc + FOLLOW + 1e-6);
        expect(arc).toBeGreaterThan(AIM);
      }
    }
    expect(pins).toBeGreaterThan(0);
  });

  it("fires at the card in front of its node and follows that ring section as it turns (B14)", () => {
    // A node at bearing 0.05 fires within AIM of it, on the arc the stage shows.
    const [lo, hi] = aimRange(0.05, 0.4);
    expect([lo, hi]).toEqual([0.05 - AIM, 0.05 + AIM]);
    expect(aimRange(0.35, 0.4)[1]).toBe(0.4);
    expect(landingAngle(0.1, 0, lo, hi)).toBeCloseTo(0.1, 12); // the card, where it stood
    expect(landingAngle(0.1, 0.05, lo, hi)).toBeCloseTo(0.15, 12); // then carried with the ring
    expect(landingAngle(0.9, 0, lo, hi)).toBeCloseTo(hi, 12); // a card further off: its direction
    expect(landingAngle(0.1 + Math.PI * 2, 0, lo, hi)).toBeCloseTo(0.1, 12);
    expect(landingAngle(0.1, 10, lo, hi)).toBeCloseTo(0.1 + FOLLOW, 12); // a snap is not followed
    expect(FOLLOW).toBeCloseTo((Math.PI * 2 * BUNDLE_MS) / RING_TURN_MS, 12);
  });

  it("shoots a bullet from the node to the ring, then fades the strand while it stays attached (B14)", () => {
    expect(bulletAt(0)).toBe(0);
    expect(bulletAt(TRAVEL)).toBe(1);
    expect(bulletAt(1)).toBe(1);
    expect(TRAVEL).toBeLessThan(FADE_FROM); // the bullet arrives before the strand fades
    expect(strandFade(0)).toBe(1);
    expect(strandFade(FADE_FROM)).toBe(1);
    expect(strandFade(1)).toBe(0);
    for (let life = 0; life < 1; life += 0.01) {
      expect(bulletAt(life + 0.01)).toBeGreaterThanOrEqual(bulletAt(life));
      expect(strandFade(life + 0.01)).toBeLessThanOrEqual(strandFade(life));
    }
  });

  it("bounds a strand's length by the far end of the arc it can land on", () => {
    const rim = 100;
    const half = 0.5;
    const reach = strandReach(40, 10, rim, -half, half);
    for (let angle = -half; angle <= half; angle += 0.01) {
      const d = Math.hypot(Math.cos(angle) * rim - 40, Math.sin(angle) * rim - 10);
      expect(d).toBeLessThanOrEqual(reach + 1e-9);
    }
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
        "22000": "f76a0359fbf04b4f",
        "25500": "e93e946781ba9527",
        "45000": "f76a0359fbf04b4f",
        "8000": "8afc4528e6d75bdf",
      }
    `);
  });
});
