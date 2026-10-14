/**
 * The dependency-web layers (B05, restyled in B14; DESIGN.md "Dependency web"):
 * - **edges**: every graph edge as a thin arc, written once. The shader reveals each edge when
 *   its `graph.edge` event happens and flares it briefly (recency), so playback and scrubbing
 *   cost no uploads. The web fills a disc just inside the ring, whose centre is left of the
 *   stage: the stage shows long arcs crossing its right part, like the reference.
 * - **nodes**: tests as tiny hollow squares, revealed with their `graph.node` events.
 * - **markers**: tiny hollow circles on the nodes in the latest blast radius.
 * - **bundles**: bright sheaves of 10–20 near-parallel curves from a test towards the ring card
 *   of the function it reaches (`trace.sample`, `diff.behaviour`), landing on a short bar at the
 *   inner rim and fading over 1.2 s. They are a pure function of the events in the window, `t`
 *   and the motion settings.
 *
 * Durations are wall-clock (ADR-0011). The flash governor decides which bundles are drawn and
 * which edges and markers flare; reduced motion draws no bundles and the host turns flares off.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { kindCode } from "../../model/codes";
import type { EdgeType } from "../../model/graph";
import { ringTracker, webRadius } from "../geometry";
import type { FlashGovernor } from "../governor";
import type { StageFrame, StageLayer } from "../layer";
import { type RingModel, rotationAt } from "../ring/layers";
import {
  ALWAYS,
  type Recency,
  type SegmentWriter,
  segmentBuffers,
  segmentWriter,
} from "../segments";
import { arcPieces, edgeHash, writeArc } from "./arcs";
import type { LayoutService } from "./layout-service";

export const EDGE_RECENCY: Recency = { flare: 2.5, flareMs: 1500 };
export const EDGE_STYLE: Readonly<Record<EdgeType, { alpha: number; width: number }>> = {
  imports: { alpha: 0.24, width: 1 },
  calls: { alpha: 0.3, width: 1 },
  covers: { alpha: 0.16, width: 1 },
};

const EDGE_TYPES: readonly EdgeType[] = ["imports", "calls", "covers"];

export function edgeLayer(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
): StageLayer {
  const buffers = segmentBuffers(4096);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawnGraph = -1;
  let drawnLayout = -1;
  let drawnGovernor = -1;
  let drawnW = -1;
  let drawnH = -1;
  return {
    name: "edges",
    primitive: "segments",
    buffers,
    recency: EDGE_RECENCY,
    update(frame: StageFrame) {
      const { graph } = model;
      governor.prepare(frame);
      const moved = ringChanged(frame.ring);
      if (
        graph.version === drawnGraph &&
        layout.version === drawnLayout &&
        governor.version === drawnGovernor &&
        frame.width === drawnW &&
        frame.height === drawnH &&
        !moved
      )
        return;
      const positions = layout.positions;
      if (positions === null) return;
      drawnGraph = graph.version;
      drawnLayout = layout.version;
      drawnGovernor = governor.version;
      drawnW = frame.width;
      drawnH = frame.height;
      const { cx, cy } = frame.ring;
      const radius = webRadius(frame.ring);
      const x = (n: number) => cx + (positions[n * 2] as number) * radius;
      const y = (n: number) => cy + (positions[n * 2 + 1] as number) * radius;
      const placed = (n: number) => n * 2 + 1 < positions.length; // else newer than the layout
      // Room for exactly the pieces on the stage: most of the web is off it.
      let pieces = 0;
      for (let e = 0; e < graph.edgeCount; e++) {
        const s = graph.edgeSource[e] as number;
        const t = graph.edgeTarget[e] as number;
        if (placed(s) && placed(t))
          pieces += arcPieces(x(s), y(s), x(t), y(t), edgeHash(s, t), frame.width, frame.height);
      }
      buffers.reserve(pieces);
      writer.begin();
      for (let e = 0; e < graph.edgeCount; e++) {
        const s = graph.edgeSource[e] as number;
        const t = graph.edgeTarget[e] as number;
        if (!placed(s) || !placed(t)) continue;
        const style = EDGE_STYLE[EDGE_TYPES[graph.edgeType[e] as number] ?? "imports"];
        writeArc(
          writer,
          x(s),
          y(s),
          x(t),
          y(t),
          edgeHash(s, t),
          frame.width,
          frame.height,
          style.width,
          style.alpha,
          model.store.time[graph.edgeEvent[e] as number] as number,
          governor.edgeFlare(e) ? 1 : 0,
        );
      }
    },
  };
}

const SQUARE = 2.2;

/** Tests as tiny hollow squares (the reference's scattered squares), when on the stage. */
export function nodeLayer(model: CockpitModel, layout: LayoutService): StageLayer {
  const buffers = segmentBuffers(256);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawnGraph = -1;
  let drawnLayout = -1;
  let drawnW = -1;
  let drawnH = -1;
  return {
    name: "nodes",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      const { graph, store } = model;
      const moved = ringChanged(frame.ring);
      if (
        graph.version === drawnGraph &&
        layout.version === drawnLayout &&
        frame.width === drawnW &&
        frame.height === drawnH &&
        !moved
      )
        return;
      const positions = layout.positions;
      if (positions === null) return;
      drawnGraph = graph.version;
      drawnLayout = layout.version;
      drawnW = frame.width;
      drawnH = frame.height;
      const { cx, cy } = frame.ring;
      const radius = webRadius(frame.ring);
      buffers.reserve(graph.nodeCount * 4);
      writer.begin();
      for (let n = 0; n < graph.nodeCount && n * 2 + 1 < positions.length; n++) {
        if (graph.nodeTypeName(n) !== "test") continue;
        const x = cx + (positions[n * 2] as number) * radius;
        const y = cy + (positions[n * 2 + 1] as number) * radius;
        if (x < -SQUARE || y < -SQUARE || x > frame.width + SQUARE || y > frame.height + SQUARE)
          continue;
        const appear = store.time[graph.nodeEvent[n] as number] as number;
        const corners = [
          [x - SQUARE, y - SQUARE],
          [x + SQUARE, y - SQUARE],
          [x + SQUARE, y + SQUARE],
          [x - SQUARE, y + SQUARE],
        ] as const;
        for (let k = 0; k < 4; k++) {
          const [ax, ay] = corners[k] as readonly [number, number];
          const [bx, by] = corners[(k + 1) % 4] as readonly [number, number];
          writer.push(ax, ay, bx, by, 1, 1, 1, 1, 0.5, 1, appear, 0);
        }
      }
    },
  };
}

export const MARKER_SIDES = 10;
const MARKER_RADIUS = 3.5;
const CIRCLE = Array.from({ length: MARKER_SIDES + 1 }, (_, i) => {
  const angle = (i / MARKER_SIDES) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
export const MARKER_RECENCY: Recency = { flare: 1.2, flareMs: 900 };
/** Upper bound of one blast marker's drawn area in CSS px² (its 1 px sides). */
export const MARKER_AREA =
  MARKER_SIDES * segmentArea(2 * MARKER_RADIUS * Math.sin(Math.PI / MARKER_SIDES), 1);

export function markerLayer(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
): StageLayer {
  const buffers = segmentBuffers(MARKER_SIDES * 128);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawnBlast = -2;
  let drawnLayout = -1;
  let drawnGovernor = -1;
  return {
    name: "markers",
    primitive: "segments",
    buffers,
    recency: MARKER_RECENCY,
    update(frame: StageFrame) {
      const blast = model.kinds.lastIndex("blast.computed", frame.cursor);
      governor.prepare(frame);
      const moved = ringChanged(frame.ring);
      if (
        blast === drawnBlast &&
        layout.version === drawnLayout &&
        governor.version === drawnGovernor &&
        !moved
      )
        return;
      const positions = layout.positions;
      if (positions === null) return;
      drawnBlast = blast;
      drawnLayout = layout.version;
      drawnGovernor = governor.version;
      writer.begin();
      const event = blast < 0 ? null : model.store.event(blast);
      if (event?.kind !== "blast.computed") return;
      const { cx, cy } = frame.ring;
      const radius = webRadius(frame.ring);
      const appear = model.store.time[blast] as number;
      const flare = governor.markerFlare(blast) ? 1 : 0;
      const mark = (symbol: string, alpha: number) => {
        const node = model.graph.nodeForSymbol(symbol);
        if (node === undefined || node * 2 + 1 >= positions.length) return;
        const x = cx + (positions[node * 2] as number) * radius;
        const y = cy + (positions[node * 2 + 1] as number) * radius;
        buffers.reserve(buffers.count + MARKER_SIDES);
        for (let i = 0; i < MARKER_SIDES; i++) {
          const [ax, ay] = CIRCLE[i] as readonly [number, number];
          const [bx, by] = CIRCLE[i + 1] as readonly [number, number];
          writer.push(
            x + ax * MARKER_RADIUS,
            y + ay * MARKER_RADIUS,
            x + bx * MARKER_RADIUS,
            y + by * MARKER_RADIUS,
            1,
            1,
            1,
            1,
            alpha,
            1,
            appear,
            flare,
          );
        }
      };
      for (const item of event.payload.affected) mark(item.symbol_id, 0.45);
      for (const symbol of event.payload.changed) mark(symbol, 0.9);
    },
  };
}

export const BUNDLE_MS = 1200;
export const MAX_BUNDLES = 40;
/** A bundle reaches at most this share of the stage height from its landing point. */
export const BUNDLE_REACH = 0.32;
export const BUNDLE_STEPS = 12;
/** Spacing between a sheaf's curves where it lands (px), where it starts, and at its bow. */
const LAND_SPACING = 1.5;
const START_SPACING = 3.4;
const BOW_SPACING = 2.4;
/** Each curve's offset is its rank ± up to this much, so the sheaf is not a regular grating. */
const OFFSET_JITTER = 0.45;
/** Curves start up to this share of the way along, so the sheaf's far end is ragged. */
const STAGGER = 0.3;
/** Share of a bundle's life spent sweeping from source to target before it fades. */
const SWEEP = 0.25;
const TRACE = kindCode("trace.sample", 1);
const BEHAVIOUR = kindCode("diff.behaviour", 1);

/** Curves in a bundle, from the event's hash. */
export const bundleCurves = (h: number): number => 10 + (h % 11);
/** A bundle's bow: its middle bends to one side by 22–34% of its length (px, signed). */
const bundleBow = (len: number, h: number): number =>
  (0.22 + ((h >>> 8) % 100) / 833) * len * ((h & 1) === 1 ? 1 : -1);
/** Length of the bar a bundle lands on, px. */
const pinLength = (h: number): number => bundleCurves(h) * LAND_SPACING + 8;

/**
 * Upper bound of a bundle's drawn area in CSS px², for the flash governor: the sheaf lies within
 * its control polygon (start → bowed middle → landing), widened by its widest spread, the 1 px
 * line and 2 px of anti-aliasing fringe, plus the 2 px bar it lands on.
 */
export function bundleArea(len: number, h: number): number {
  const curves = bundleCurves(h);
  const spread = START_SPACING * ((curves - 1) / 2 + OFFSET_JITTER);
  const half = Math.sqrt((len / 2) ** 2 + (Math.abs(bundleBow(len, h)) + spread) ** 2);
  return (2 * half + 2) * (2 * spread + 1 + 2) + (pinLength(h) + 2) * (2 + 2);
}

/** Upper bound of a segment's drawn area in CSS px² (2 px of anti-aliasing fringe each way). */
export function segmentArea(len: number, width: number): number {
  return (len + 2) * (width + 2);
}

/** A curve's own hash within its bundle. */
const curveHash = (h: number, c: number): number =>
  Math.imul(h ^ Math.imul(c + 1, 0x9e3779b9), 0x85ebca6b) >>> 0;

/**
 * Writes one sheaf of curves from a start point to a landing point at `life` (0–1 of
 * BUNDLE_MS), like the reference's brushes: side by side where they land on the bar, fanning out
 * and ending raggedly at the far end. `tx, ty` is the direction the bar runs in (unit length).
 */
function drawBundle(
  writer: SegmentWriter,
  px: number,
  py: number,
  qx: number,
  qy: number,
  tx: number,
  ty: number,
  life: number,
  h: number,
  flagged: boolean,
): void {
  const dx = qx - px;
  const dy = qy - py;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return;
  const nx = -dy / len;
  const ny = dx / len;
  const curves = bundleCurves(h);
  const bow = bundleBow(len, h);
  const fade = (1 - life) ** 1.5;
  const reach = Math.min(1, life / SWEEP); // the sheaf sweeps out first, then fades
  const steps = Math.max(1, Math.ceil(BUNDLE_STEPS * reach));
  const alpha = (flagged ? 0.8 : 0.7) * fade;
  const red = flagged ? 0.71 : 1; // --flag for behaviour differences, white otherwise
  const green = flagged ? 0.56 : 1;
  const blue = flagged ? 0.61 : 1;
  const mx = (px + qx) / 2;
  const my = (py + qy) / 2;
  for (let c = 0; c < curves; c++) {
    const hc = curveHash(h, c);
    const offset = c - (curves - 1) / 2 + ((hc & 0xffff) / 0xffff - 0.5) * 2 * OFFSET_JITTER;
    const ax = px + nx * offset * START_SPACING;
    const ay = py + ny * offset * START_SPACING;
    // The sheaf lands along the bar, side by side.
    const bx = qx + tx * offset * LAND_SPACING;
    const by = qy + ty * offset * LAND_SPACING;
    const kx = mx + nx * (bow + offset * BOW_SPACING);
    const ky = my + ny * (bow + offset * BOW_SPACING);
    const from = ((hc >>> 16) / 0xffff) * STAGGER;
    if (reach <= from) continue;
    let x0 = 0;
    let y0 = 0;
    for (let s = 0; s <= steps; s++) {
      const u = from + ((reach - from) * s) / steps;
      const v = 1 - u;
      const x1 = v * v * ax + 2 * v * u * kx + u * u * bx;
      const y1 = v * v * ay + 2 * v * u * ky + u * u * by;
      if (s > 0 && !writer.push(x0, y0, x1, y1, 1, red, green, blue, alpha, 1, ALWAYS)) return;
      x0 = x1;
      y0 = y1;
    }
  }
  if (reach < 1) return;
  // The bar it lands on, like the reference's bright pins at the rim.
  const half = pinLength(h) / 2;
  writer.push(
    qx - tx * half,
    qy - ty * half,
    qx + tx * half,
    qy + ty * half,
    2,
    red,
    green,
    blue,
    0.9 * fade,
    1,
    ALWAYS,
  );
}

export function bundleLayer(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
  ring: RingModel,
): StageLayer {
  const buffers = segmentBuffers(MAX_BUNDLES * (24 * BUNDLE_STEPS + 1));
  const writer = segmentWriter(buffers);
  return {
    name: "bundles",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      writer.begin();
      governor.prepare(frame);
      if (frame.motion.reduced) return; // reduced motion: no bundles (DESIGN.md "Motion")
      const positions = layout.positions;
      if (positions === null) return;
      ring.sync();
      const { store, graph } = model;
      const life = BUNDLE_MS * frame.motion.speed; // the wall-clock fade, in run time
      // Same range as window.active(t, life), without allocating a tuple each frame.
      const start = store.firstAtOrAfter(frame.t - life);
      const end = store.cursorAt(frame.t);
      if (start >= end) return;
      const { cx, cy, r } = frame.ring;
      const radius = webRadius(frame.ring);
      const rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      const maxReach = BUNDLE_REACH * frame.height;
      let bundles = 0;
      for (let i = end - 1; i >= start && bundles < MAX_BUNDLES; i--) {
        const code = store.kind[i];
        if (code !== TRACE && code !== BEHAVIOUR) continue;
        const event = store.event(i);
        if (event?.kind !== "trace.sample" && event?.kind !== "diff.behaviour") continue;
        if (!governor.bundle(i)) continue;
        const test = event.target?.test;
        const from = test === undefined ? undefined : graph.byId.get(test);
        const to = graph.nodeForSymbol(event.payload.symbol_id);
        if (from === undefined || to === undefined) continue;
        if (Math.max(from, to) * 2 + 1 >= positions.length) continue;
        // Land on the function's ring card at the inner rim, or on its node if it has no card.
        const card = ring.cardOf.get(graph.files[to] as string);
        let qx: number;
        let qy: number;
        let tx: number;
        let ty: number;
        if (card !== undefined) {
          const angle =
            ((ring.angles.start[card] as number) + (ring.angles.end[card] as number)) / 2 +
            rotation;
          qx = cx + Math.cos(angle) * (r - 3);
          qy = cy + Math.sin(angle) * (r - 3);
          tx = -Math.sin(angle);
          ty = Math.cos(angle);
        } else {
          qx = cx + (positions[to * 2] as number) * radius;
          qy = cy + (positions[to * 2 + 1] as number) * radius;
          tx = 0;
          ty = 1;
        }
        // Start from the test, or towards it when it is further than the reach.
        let px = cx + (positions[from * 2] as number) * radius;
        let py = cy + (positions[from * 2 + 1] as number) * radius;
        const dx = px - qx;
        const dy = py - qy;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance > maxReach) {
          px = qx + (dx / distance) * maxReach;
          py = qy + (dy / distance) * maxReach;
        }
        bundles++;
        drawBundle(
          writer,
          px,
          py,
          qx,
          qy,
          tx,
          ty,
          (frame.t - (store.time[i] as number)) / life,
          hash32(event.id),
          code === BEHAVIOUR,
        );
      }
    },
  };
}

export function webLayers(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
  ring: RingModel,
): StageLayer[] {
  return [
    edgeLayer(model, layout, governor),
    nodeLayer(model, layout),
    markerLayer(model, layout, governor),
    bundleLayer(model, layout, governor, ring),
  ];
}
