import fc from "fast-check";
import { beforeAll, describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { NORMAL_MOTION } from "../../motion/motion";
import type { Ring } from "../../shell/layout";
import { computeLayout } from "../../shell/layout";
import { viewRing } from "../camera";
import { outerRadius, webRadius } from "../geometry";
import { FlashGovernor } from "../governor";
import { hashRenderModels } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { clampLook, DEFAULT_LOOK, type Look } from "../look";
import { AtlasService } from "../ring/atlas-service";
import { RingModel, rotationAt } from "../ring/layers";
import { RING_TURN_MS } from "../ring/rotation";
import { cardCentre, eventFile } from "../ring/sections";
import { segmentAlpha } from "../segments";
import { streams } from "../streams/style";
import { arcPieces, edgeHash } from "./arcs";
import {
  BUNDLE_MS,
  BUNDLE_STEPS,
  bulletAt,
  bundleLayer,
  DIM_MAX,
  EDGE_RECENCY,
  edgeLayer,
  FADE_FROM,
  FOLLOW,
  HIT_FILE,
  HIT_FUNCTION,
  HIT_TEST,
  landingAngle,
  landsOnStage,
  MARKER_SIDES,
  MAX_BUNDLES,
  markerLayer,
  newHit,
  nodeLayer,
  pinLength,
  placedBunch,
  RAY_COUNT,
  RAY_OUT,
  rayExtent,
  sortByBearing,
  strandFade,
  strandHit,
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
/** A node's position on the stage (in the arc view, or in `view`). */
const at = (n: number, view: Ring = ring): [number, number] => {
  const positions = layout.positions as Float32Array;
  const radius = webRadius(view);
  return [
    view.cx + (positions[n * 2] as number) * radius,
    view.cy + (positions[n * 2 + 1] as number) * radius,
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

/** A bundle layer over a fresh ring, with an uncapped governor that knows the ring. */
function strands() {
  const rings = ringModel();
  rings.sync();
  const governor = new FlashGovernor(model, layout, Number.POSITIVE_INFINITY, rings);
  return { rings, governor, layer: bundleLayer(model, layout, governor, rings) };
}

/** Whether one of a layer's segments starts at (x, y). */
function startsIn(layer: StageLayer, x: number, y: number): boolean {
  const a = layer.buffers.array("a");
  for (let k = 0; k < layer.buffers.count; k++) {
    if (Math.abs((a[k * 2] as number) - x) < 1e-3 && Math.abs((a[k * 2 + 1] as number) - y) < 1e-3)
      return true;
  }
  return false;
}

/** The screen angle of the section the event at store index `i` hits, where it stood then. */
function firedAt(rings: RingModel, i: number): number | undefined {
  const event = model.store.event(i);
  const hit = newHit();
  if (event === null || !strandHit(model, event, hit)) return undefined;
  const card = rings.cardOf.get(hit.file);
  if (card === undefined) return undefined;
  return cardCentre(rings, card) + rotationAt(rings, model.store.time[i] as number, NORMAL_MOTION);
}

/** Whether the event at store index `i` hit its section while the section was on screen. */
function traceOnScreen(rings: RingModel, i: number): boolean {
  const fired = firedAt(rings, i);
  return fired !== undefined && landsOnStage(fired, ring, stage.w, stage.h);
}

/** The last trace whose function matches and whose section was on screen when it fired. */
function lastTrace(rings: RingModel, match: (target: number) => boolean): number {
  for (let i = model.store.length - 1; i >= 0; i--) {
    const event = model.store.event(i);
    if (event?.kind !== "trace.sample") continue;
    const target = model.graph.nodeForSymbol(event.payload.symbol_id);
    if (target !== undefined && match(target) && traceOnScreen(rings, i)) return i;
  }
  throw new Error("no trace on screen");
}

describe("node layer", () => {
  it("draws the run's nodes on the stage as small circles: some in the arc, all in the whole wheel", () => {
    const { graph } = model;
    const inner = graph.ids.filter((_, n) => graph.nodeTypeName(n) !== "module").length;
    const whole = viewRing(ring, stage.w, stage.h, 1);
    for (const view of [ring, whole]) {
      const layer = nodeLayer(model, layout);
      layer.update({ ...frameAt(0), ring: view });
      const shown = graph.ids
        .map((_, n) => n)
        .filter((n) => {
          if (graph.nodeTypeName(n) === "module") return false;
          const [x, y] = at(n, view);
          return x >= -3.2 && y >= -3.2 && x <= stage.w + 3.2 && y <= stage.h + 3.2;
        });
      expect(layer.buffers.count).toBe(8 * shown.length);
      // B15 spreads them over the whole disc: the arc view shows the part facing the stage.
      if (view === ring) expect(shown.length).toBeGreaterThan(0);
      else expect(shown.length).toBe(inner);
    }
  });
});

describe("bundle layer (B05: bundles are pure functions of (event, t))", () => {
  it("gives the same render model whatever happened in earlier frames", () => {
    const fresh = () => strands().layer;
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
    const { layer } = strands();
    let peak = 0;
    for (let t = 0; t <= model.store.endTime; t += 250) {
      layer.update(frameAt(t));
      peak = Math.max(peak, layer.buffers.count);
      const [start, end] = model.window.active(t, BUNDLE_MS);
      const triggers = Array.from({ length: end - start }, (_, i) =>
        model.store.event(start + i),
      ).filter((e) => e !== null && streams(e)).length;
      if (triggers === 0) expect(layer.buffers.count).toBe(0);
    }
    expect(peak).toBeGreaterThan(0);
    expect(peak).toBeLessThanOrEqual(MAX_BUNDLES * (12 * BUNDLE_STEPS + 11));
  });

  it("fires a bunch's first strand from the test's node, which lights up, and keeps it attached", () => {
    const { rings, layer } = strands();
    const first = lastTrace(rings, () => true);
    const t0 = model.store.time[first] as number;
    const event = model.store.event(first);
    if (event?.kind !== "trace.sample") throw new Error("no trace");
    const hit = newHit();
    expect(strandHit(model, event, hit)).toBe(true);
    const origin = hit.first;
    expect(origin).toBe(model.graph.byId.get(event.target?.test ?? ""));
    const [x, y] = at(origin as number);
    for (const life of [0.05, 0.2, 0.5, 0.9]) {
      layer.update(frameAt(t0 + life * BUNDLE_MS));
      // The dim strand starts at the node at every age: it stays attached.
      expect(startsIn(layer.lines, x, y)).toBe(true);
      // The node's ring (from (x + 4.5, y)) shows while the bullet is in flight.
      expect(startsIn(layer, x + 4.5, y)).toBe(life < TRAVEL);
    }
  });

  it("fires a bunch from the nodes that reach the function, converging on one section (B14)", () => {
    const { rings, governor, layer } = strands();
    const { store, graph } = model;
    const parseDate = graph.byId.get("timekeeper.parse:parse_date#0") as number;
    // The last trace of parse_date fired while its section was on screen.
    const i = lastTrace(rings, (target) => target === parseDate);
    const event = store.event(i);
    if (event?.kind !== "trace.sample") throw new Error("no trace of parse_date");
    governor.prepare(frameAt(0)); // indexes the log, as the first frame does
    const members = new Int32Array(MAX_BUNCH);
    const hit = newHit();
    strandHit(model, event, hit);
    expect(hit.role).toBe(HIT_FUNCTION);
    expect(hit.target).toBe(parseDate);
    const fired = firedAt(rings, i) as number;
    const unit = (ring.r - 3) / webRadius(ring);
    const n = placedBunch(
      governor.reach,
      hit,
      i,
      members,
      layout.positions as Float32Array,
      Math.cos(fired) * unit,
      Math.sin(fired) * unit,
    );
    expect(n).toBe(MAX_BUNCH); // parse_date has more reachers than a bunch holds
    const t0 = store.time[i] as number;
    // In flight: every node of the bunch lights up, each the start of its own dim strand.
    layer.update(frameAt(t0 + 0.05 * BUNDLE_MS));
    const a = layer.buffers.array("a");
    const origins = new Set<string>();
    for (let k = 0; k < n; k++) {
      const [x, y] = at(members[k] as number);
      expect(startsIn(layer.lines, x, y)).toBe(true);
      expect(startsIn(layer, x + 4.5, y)).toBe(true);
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

  it("lands each strand on the inner rim, on the stage or as far as it has followed the ring", () => {
    const { layer } = strands();
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
        // Where it fired was on the stage; it has followed the ring by at most FOLLOW since.
        const angle = Math.atan2(my, mx);
        let fired = false;
        for (let d = -FOLLOW; d <= FOLLOW + 1e-9; d += FOLLOW / 64)
          fired ||= landsOnStage(angle + d, ring, stage.w, stage.h);
        expect(fired).toBe(true);
      }
    }
    expect(pins).toBeGreaterThan(0);
  });

  it("lands on its section where it stood when it fired, and follows that section as it turns (B14)", () => {
    expect(landingAngle(0.1, 0)).toBeCloseTo(0.1, 12); // the section, where it stood
    expect(landingAngle(0.1, 0.05)).toBeCloseTo(0.15, 12); // then carried with the ring
    expect(landingAngle(0.1 + Math.PI * 2, 0)).toBeCloseTo(0.1, 12);
    expect(landingAngle(0.1, 10)).toBeCloseTo(0.1 + FOLLOW, 12); // a snap is not followed
    expect(FOLLOW).toBeCloseTo((Math.PI * 2 * BUNDLE_MS) / RING_TURN_MS, 12);
    // The ring's centre is left of the stage: its right side is on screen, its left side is not.
    expect(landsOnStage(0, ring, stage.w, stage.h)).toBe(true);
    expect(landsOnStage(Math.PI, ring, stage.w, stage.h)).toBe(false);
    expect(landsOnStage(Math.PI * 2, ring, stage.w, stage.h)).toBe(true);
  });

  it("fires a bunch only when its section is on screen and it has nodes, and the governor agrees", () => {
    const rings = ringModel();
    rings.sync();
    const governor = new FlashGovernor(model, layout, Number.POSITIVE_INFINITY, rings);
    governor.prepare(frameAt(0));
    const positions = layout.positions as Float32Array;
    const members = new Int32Array(MAX_BUNCH);
    const hit = newHit();
    const unit = (ring.r - 3) / webRadius(ring);
    let on = 0;
    let off = 0;
    for (let i = 0; i < model.store.length; i++) {
      const event = model.store.event(i);
      if (event === null || !streams(event)) continue;
      const fired = firedAt(rings, i);
      let fires = fired !== undefined && landsOnStage(fired, ring, stage.w, stage.h);
      if (fires && fired !== undefined) {
        strandHit(model, event, hit);
        const n = placedBunch(
          governor.reach,
          hit,
          i,
          members,
          positions,
          Math.cos(fired) * unit,
          Math.sin(fired) * unit,
        );
        fires = n > 0;
      }
      expect(governor.bundle(i)).toBe(fires);
      if (fires) on++;
      else off++;
    }
    expect(on).toBeGreaterThan(0);
    expect(off).toBeGreaterThan(0);
  });

  it("knows what each event's strands are about: a function, a test or a file (B14)", () => {
    const hit = newHit();
    const roles = new Set<number>();
    for (let i = 0; i < model.store.length; i++) {
      const event = model.store.event(i);
      if (event === null || !streams(event) || !strandHit(model, event, hit)) continue;
      roles.add(hit.role);
      // Its section is the file the event is about, as the outside lines take it.
      expect(hit.file).toBe(eventFile(model, event));
      if (hit.role === HIT_FUNCTION || hit.role === HIT_TEST) {
        expect(model.graph.files[hit.target]).toBe(hit.file);
      } else {
        expect(hit.target).toBe(-1);
        expect(hit.first).toBe(-1);
      }
      if (hit.role === HIT_TEST) expect(hit.first).toBe(hit.target);
    }
    expect(roles.has(HIT_FUNCTION)).toBe(true);
    expect(roles.has(HIT_FILE) || roles.has(HIT_TEST)).toBe(true);
  });

  it("bounces each outside line: out to its length, then back into the rim (B14)", () => {
    expect(rayExtent(0)).toBe(0);
    expect(rayExtent(RAY_OUT)).toBeCloseTo(1, 12);
    expect(rayExtent(1)).toBe(0);
    expect(rayExtent(-0.1)).toBe(0);
    expect(rayExtent(1.1)).toBe(0);
    for (let u = 0; u < 1; u += 0.01) {
      const next = Math.min(1, u + 0.01);
      if (next <= RAY_OUT) expect(rayExtent(next)).toBeGreaterThanOrEqual(rayExtent(u));
      else if (u >= RAY_OUT) expect(rayExtent(next)).toBeLessThanOrEqual(rayExtent(u));
      expect(rayExtent(u)).toBeLessThanOrEqual(1);
    }
    // The rebound is slower than the shot: the line shoots out, then falls back.
    expect(1 - RAY_OUT).toBeGreaterThan(RAY_OUT);
  });

  it("shoots the outside lines only from the hit section, after the strands land, and ends with the bunch", () => {
    const { rings, governor, layer } = strands();
    governor.prepare(frameAt(0));
    const { store } = model;
    // A bunch with no other bunch within a life of it, so the lines on screen are its own.
    let lone = -1;
    for (let i = store.length - 1; i >= 0 && lone < 0; i--) {
      if (!governor.bundle(i)) continue;
      const t = store.time[i] as number;
      let alone = true;
      for (let j = store.firstAtOrAfter(t - BUNDLE_MS); j < store.length; j++) {
        if ((store.time[j] as number) > t + BUNDLE_MS) break;
        if (j !== i && governor.bundle(j)) alone = false;
      }
      if (alone) lone = i;
    }
    expect(lone).toBeGreaterThanOrEqual(0);
    const t0 = store.time[lone] as number;
    const event = store.event(lone);
    const hit = newHit();
    if (event === null || !strandHit(model, event, hit)) throw new Error("no hit");
    const card = rings.cardOf.get(hit.file) as number;
    const then = rotationAt(rings, t0, NORMAL_MOTION);
    // In flight: no lines outside yet.
    layer.update(frameAt(t0 + 0.2 * BUNDLE_MS));
    expect(layer.rays.buffers.count).toBe(0);
    // Landed: lines leave the outer rim, within the hit section as it has turned since.
    let peak = 0;
    for (const life of [0.5, 0.6, 0.7, 0.8, 0.9]) {
      const t = t0 + life * BUNDLE_MS;
      layer.update(frameAt(t));
      const turned = landingAngle(0, rotationAt(rings, t, NORMAL_MOTION) - then);
      const a = layer.rays.buffers.array("a");
      const count = layer.rays.buffers.count;
      expect(count).toBeLessThanOrEqual(RAY_COUNT);
      peak = Math.max(peak, count);
      const lo = (rings.angles.start[card] as number) + then + turned;
      const hi = (rings.angles.end[card] as number) + then + turned;
      for (let k = 0; k < count; k++) {
        const dx = (a[k * 2] as number) - ring.cx;
        const dy = (a[k * 2 + 1] as number) - ring.cy;
        expect(Math.hypot(dx, dy)).toBeCloseTo(outerRadius(ring) + 2, 1);
        let angle = Math.atan2(dy, dx);
        while (angle < lo - Math.PI) angle += Math.PI * 2;
        while (angle > lo + Math.PI) angle -= Math.PI * 2;
        expect(angle).toBeGreaterThanOrEqual(lo - 1e-4);
        expect(angle).toBeLessThanOrEqual(hi + 1e-4);
      }
    }
    expect(peak).toBeGreaterThan(0);
    // At the end of the bunch's life every line has rebounded into the rim.
    layer.update(frameAt(t0 + BUNDLE_MS - 1));
    const a = layer.rays.buffers.array("a");
    const b = layer.rays.buffers.array("b");
    for (let k = 0; k < layer.rays.buffers.count; k++) {
      const length = Math.hypot(
        (b[k * 2] as number) - (a[k * 2] as number),
        (b[k * 2 + 1] as number) - (a[k * 2 + 1] as number),
      );
      expect(length).toBeLessThan(8);
    }
  });

  it("keeps the dim strands and the outside lines below a flash: MAX-blended at DIM_MAX (B14)", () => {
    const { layer } = strands();
    expect(layer.lines.blend).toBe("max");
    expect(layer.rays.blend).toBe("max");
    // sRGB to relative luminance: DIM_MAX over the #080808 background rises by less than 10%.
    const luminance = (v: number) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
    expect(luminance(DIM_MAX) - luminance(8 / 255)).toBeLessThan(0.1);
    let seen = 0;
    for (let t = 20_000; t <= 32_000; t += 100) {
      layer.update(frameAt(t));
      for (const part of [layer.lines, layer.rays]) {
        const color = part.buffers.array("color");
        const shape = part.buffers.array("shape");
        for (let k = 0; k < part.buffers.count; k++) {
          seen++;
          const alpha = color[k * 4 + 3] as number;
          const tail = shape[k * 2 + 1] as number;
          // The brighter end of each segment, colour channels at most 1.
          expect(alpha * Math.max(1, tail)).toBeLessThanOrEqual(DIM_MAX + 1e-6);
          for (let c = 0; c < 3; c++) expect(color[k * 4 + c] as number).toBeLessThanOrEqual(1);
        }
      }
    }
    expect(seen).toBeGreaterThan(0);
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

  it("writes the same instances whatever the viewer's brightness and uncounted widths (B15)", () => {
    const restyled = clampLook({
      parts: {
        strands: { width: 3, brightness: 0.2 },
        lines: { width: 0.5, brightness: 0.5 },
        nodes: { width: 2, brightness: 2 },
        mesh: { brightness: 0.3 },
        bullets: { brightness: 0.3 },
      },
    });
    const drawn = (look: Look) => {
      const { layer } = strands();
      const nodes = nodeLayer(model, layout);
      const edges = edgeLayer(model, layout, unlimited(layout));
      const layers = [layer, layer.lines, layer.rays, nodes, edges];
      for (const t of [24_400, 24_700]) {
        for (const l of [layer, nodes, edges]) l.update({ ...frameAt(t), look });
      }
      return hashRenderModels(layers.map((l) => ({ layer: l.name, buffers: l.buffers })));
    };
    expect(drawn(restyled)).toBe(drawn(DEFAULT_LOOK));
  });

  it("pins the demo run's web at fixed times", async () => {
    const layers = [
      edgeLayer(model, layout, unlimited(layout)),
      nodeLayer(model, layout),
      markerLayer(model, layout, unlimited(layout)),
      strands().layer,
    ];
    const hashes = Object.fromEntries(
      [8_000, 22_000, 25_500, 45_000].map((t) => {
        for (const layer of layers) layer.update(frameAt(t));
        return [t, hashRenderModels(layers.map((l) => ({ layer: l.name, buffers: l.buffers })))];
      }),
    );
    expect(hashes).toMatchInlineSnapshot(`
      {
        "22000": "aaf0e32ed9be12e2",
        "25500": "d4b601318ea138b5",
        "45000": "8394c3af7b9aa3c9",
        "8000": "9bb76d36c0a1f000",
      }
    `);
  });
});
