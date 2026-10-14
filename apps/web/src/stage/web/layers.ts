/**
 * The dependency-web layers (B05, restyled in B14; DESIGN.md "Dependency web"):
 * - **edges**: every graph edge as a thin arc, written once. The shader reveals each edge when
 *   its `graph.edge` event happens and flares it briefly (recency), so playback and scrubbing
 *   cost no uploads. The web fills a disc just inside the ring, whose centre is left of the
 *   stage: the stage shows long arcs crossing its right part, like the reference.
 * - **nodes**: the run's nodes, tests and symbols, as small hollow circles in front of the web
 *   (the layout's front sector), revealed with their `graph.node` events: the points strands
 *   fire from.
 * - **markers**: tiny hollow circles on the nodes in the latest blast radius.
 * - **bundles** (strands): bright sheaves of 6–9 curves from a test's node to the ring card of
 *   the function it reaches (`trace.sample`, `diff.behaviour`), like the reference's (B14). A
 *   strand shoots out from its node and lands on a short bar at the inner rim. It stays attached
 *   to its node while its landing end follows that section of the ring as it turns, then fades
 *   (750 ms). They are a pure function of the events in the window, `t` and the motion settings.
 *
 * Durations are wall-clock (ADR-0011). The flash governor decides which bundles are drawn and
 * which edges and markers flare; reduced motion draws no bundles and the host turns flares off.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { kindCode } from "../../model/codes";
import type { EdgeType } from "../../model/graph";
import type { Ring } from "../../shell/layout";
import { ringTracker, webRadius } from "../geometry";
import type { FlashGovernor } from "../governor";
import type { StageFrame, StageLayer } from "../layer";
import { type RingModel, rotationAt } from "../ring/layers";
import { RING_DRIFT } from "../ring/rotation";
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

const POINT_SIDES = 8;
const POINT = Array.from({ length: POINT_SIDES + 1 }, (_, k) => {
  const angle = (k / POINT_SIDES) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
/** Point radii, px: tests (where strands fire from) are a little larger than symbols. */
const TEST_POINT = 3.2;
const SYMBOL_POINT = 2.2;

/**
 * The run's nodes, tests and symbols, as small hollow circles where they are on the stage: the
 * points of the network strands fire from (the reference's scattered circles).
 */
export function nodeLayer(model: CockpitModel, layout: LayoutService): StageLayer {
  const buffers = segmentBuffers(1024);
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
      buffers.reserve(graph.nodeCount * POINT_SIDES);
      writer.begin();
      for (let n = 0; n < graph.nodeCount && n * 2 + 1 < positions.length; n++) {
        const type = graph.nodeTypeName(n);
        if (type === "module") continue;
        const size = type === "test" ? TEST_POINT : SYMBOL_POINT;
        const x = cx + (positions[n * 2] as number) * radius;
        const y = cy + (positions[n * 2 + 1] as number) * radius;
        if (x < -size || y < -size || x > frame.width + size || y > frame.height + size) continue;
        const appear = store.time[graph.nodeEvent[n] as number] as number;
        for (let k = 0; k < POINT_SIDES; k++) {
          const [ax, ay] = POINT[k] as readonly [number, number];
          const [bx, by] = POINT[k + 1] as readonly [number, number];
          writer.push(
            x + ax * size,
            y + ay * size,
            x + bx * size,
            y + by * size,
            1,
            1,
            1,
            1,
            type === "test" ? 0.6 : 0.45,
            1,
            appear,
            0,
          );
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

/** A strand's life, wall-clock ms. */
export const BUNDLE_MS = 500;
export const MAX_BUNDLES = 40;
export const BUNDLE_STEPS = 14;
/** Spacing between a strand's curves where it lands on the bar (px), at its node, and mid-way. */
const LAND_SPACING = 2.6;
const START_SPACING = 0.6;
const BOW_SPACING = 3;
/** Each curve's offset is its rank ± up to this much, so the sheaf is not a regular grating. */
const OFFSET_JITTER = 0.45;
/** Curves leave the node at slightly staggered points, so the strand frays a little there. */
const STAGGER = 0.08;
/** Share of a strand's life its head takes to shoot from its node to the ring. */
export const SHOOT = 0.3;
/** From this share of its life on, the strand fades, still attached at both ends. */
export const FADE_FROM = 0.65;
/** The ring a node shows while one of its strands is alive, px. */
const NODE_RING = 4.5;
const NODE_SIDES = 10;
const NODE_CIRCLE = Array.from({ length: NODE_SIDES + 1 }, (_, i) => {
  const angle = (i / NODE_SIDES) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
const TAU = Math.PI * 2;

/** How far along its path a strand's head is at `life` (0–1): it shoots out, easing out. */
export const strandHead = (life: number): number => 1 - (1 - Math.min(1, life / SHOOT)) ** 2;

/** A strand's brightness at `life`: full until FADE_FROM, then fading to nothing at the end. */
export const strandFade = (life: number): number =>
  life <= FADE_FROM ? 1 : 1 - ((Math.min(1, life) - FADE_FROM) / (1 - FADE_FROM)) ** 2;

/**
 * How far a strand's landing end follows the ring as it turns, radians: the ring's drift over a
 * strand's life (both wall-clock, so the same at every replay speed). A focus snap can turn the
 * ring further; the strand keeps to this, so its length stays bounded.
 */
export const FOLLOW = RING_DRIFT * BUNDLE_MS;

/**
 * How far either side of its node's own bearing a strand can land, radians: it fires at its
 * function's card when the card is in front of it, else at the ring in the card's direction, so
 * strands stay short, like the reference's.
 */
export const AIM = (10 * Math.PI) / 180;

/** Half the arc of the inner rim that strands land on: the part the stage shows, less a margin. */
export function landingArc(ring: Ring, stageHeight: number): number {
  return 0.85 * Math.asin(Math.min(1, stageHeight / 2 / ring.r));
}

/** Wraps an angle to (−π, π]. */
function wrap(angle: number): number {
  let a = angle % TAU;
  if (a <= -Math.PI) a += TAU;
  if (a > Math.PI) a -= TAU;
  return a;
}

/** The range of angles a strand from a node at `bearing` fires at: within AIM of it, on the arc. */
export function aimRange(bearing: number, arc: number): readonly [number, number] {
  return [Math.max(-arc, bearing - AIM), Math.min(arc, bearing + AIM)];
}

/**
 * Where a strand lands, as an angle on the ring: where its target stood when it fired, kept
 * within [lo, hi] (its `aimRange`), then following the ring as it has turned since, by at most
 * FOLLOW either way.
 */
export function landingAngle(fired: number, turned: number, lo: number, hi: number): number {
  const start = Math.min(hi, Math.max(lo, wrap(fired)));
  return start + Math.min(FOLLOW, Math.max(-FOLLOW, turned));
}

/**
 * The longest a strand from a node at (dx, dy) from the ring's centre can be: to the farther end
 * of the arc it can land on, angles [lo, hi] at radius `rim`. Over a range of angles narrower
 * than a half turn, the point farthest from an inner point is at one of its ends.
 */
export function strandReach(dx: number, dy: number, rim: number, lo: number, hi: number): number {
  const ax = Math.cos(lo) * rim - dx;
  const ay = Math.sin(lo) * rim - dy;
  const bx = Math.cos(hi) * rim - dx;
  const by = Math.sin(hi) * rim - dy;
  return Math.max(Math.sqrt(ax * ax + ay * ay), Math.sqrt(bx * bx + by * by));
}

const TRACE = kindCode("trace.sample", 1);
const BEHAVIOUR = kindCode("diff.behaviour", 1);

/** Curves in a strand, from the event's hash. */
export const bundleCurves = (h: number): number => 6 + (h % 4);
/**
 * How far inside the landing point a strand's control point sits, as a share of its length
 * (0.2–0.28): the strand arrives at the rim along the ring's radius, like the reference's.
 */
const bundleBend = (h: number): number => 0.2 + ((h >>> 8) % 100) / 1250;
/**
 * How far the control point also sits along the ring's turning direction, as a share of the
 * strand's length: strands sweep into the rim from the side the cards are moving towards.
 */
const SWEEP = 0.1;
/** Length of the bar a strand lands on, px. */
const pinLength = (h: number): number => bundleCurves(h) * LAND_SPACING + 8;

/**
 * Upper bound of a strand's drawn area in CSS px², for the flash governor, for a strand at most
 * `len` long (node to landing point). Each curve is no longer than its control polygon (node →
 * control point → landing). The control point is √(bend² + SWEEP²) · len from the landing, so
 * the polygon is at most len · (1 + 2 · √(bend² + SWEEP²)) plus the curve's offsets at its three
 * points. Each curve is a 1 px line with 2 px of anti-aliasing fringe. Plus the 2 px bar it lands
 * on and the ring on its node.
 */
export function bundleArea(len: number, h: number): number {
  const curves = bundleCurves(h);
  const offset = (curves - 1) / 2 + OFFSET_JITTER;
  // sqrt, not Math.hypot: it is correctly rounded on every engine, so pins agree across OSes.
  const bend = bundleBend(h);
  const polygon =
    len * (1 + 2 * Math.sqrt(bend * bend + SWEEP * SWEEP)) +
    (START_SPACING + 2 * BOW_SPACING + LAND_SPACING) * offset;
  const ring = NODE_SIDES * segmentArea(2 * NODE_RING * Math.sin(Math.PI / NODE_SIDES), 1);
  return curves * segmentArea(polygon, 1) + segmentArea(pinLength(h), 2) + ring;
}

/** Upper bound of a segment's drawn area in CSS px² (2 px of anti-aliasing fringe each way). */
export function segmentArea(len: number, width: number): number {
  return (len + 2) * (width + 2);
}

/** A curve's own hash within its strand. */
const curveHash = (h: number, c: number): number =>
  Math.imul(h ^ Math.imul(c + 1, 0x9e3779b9), 0x85ebca6b) >>> 0;

/**
 * Writes one strand at `life` (0–1 of BUNDLE_MS), from its node (ox, oy) to its landing point
 * (qx, qy) on the inner rim, like the reference's: its curves leave the node together and land
 * side by side on a bar. The head shoots out from the node (ease-out) in the first SHOOT of the
 * life and stays attached at both ends: to the node, and to the ring, which carries the landing
 * point along as it turns. From FADE_FROM on it fades. `tx, ty` is the direction the bar runs in
 * (unit length), the ring's turning direction.
 */
function drawBundle(
  writer: SegmentWriter,
  ox: number,
  oy: number,
  qx: number,
  qy: number,
  tx: number,
  ty: number,
  life: number,
  h: number,
  flagged: boolean,
): void {
  const dx = qx - ox;
  const dy = qy - oy;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1) return;
  const nx = -dy / len;
  const ny = dx / len;
  const curves = bundleCurves(h);
  // The control point sits inside the landing point along the radius (the bar's normal), so
  // every curve arrives at the rim along the radius, and a little along the turning direction.
  const bend = bundleBend(h) * len;
  const sweep = SWEEP * len;
  const cx = qx - ty * bend + tx * sweep;
  const cy = qy + tx * bend + ty * sweep;
  const head = strandHead(life);
  const fade = strandFade(life);
  const alpha = (flagged ? 0.8 : 0.7) * fade;
  const red = flagged ? 0.71 : 1; // --flag for behaviour differences, white otherwise
  const green = flagged ? 0.56 : 1;
  const blue = flagged ? 0.61 : 1;
  for (let c = 0; c < curves; c++) {
    const hc = curveHash(h, c);
    const offset = c - (curves - 1) / 2 + ((hc & 0xffff) / 0xffff - 0.5) * 2 * OFFSET_JITTER;
    const ax = ox + nx * offset * START_SPACING;
    const ay = oy + ny * offset * START_SPACING;
    // The strand lands along the bar, side by side.
    const bx = qx + tx * offset * LAND_SPACING;
    const by = qy + ty * offset * LAND_SPACING;
    const kx = cx + tx * offset * BOW_SPACING;
    const ky = cy + ty * offset * BOW_SPACING;
    const from = ((hc >>> 16) / 0xffff) * STAGGER;
    if (head <= from) continue;
    const steps = Math.max(1, Math.ceil(BUNDLE_STEPS * (head - from)));
    let x0 = 0;
    let y0 = 0;
    for (let s = 0; s <= steps; s++) {
      const u = from + ((head - from) * s) / steps;
      const v = 1 - u;
      const x1 = v * v * ax + 2 * v * u * kx + u * u * bx;
      const y1 = v * v * ay + 2 * v * u * ky + u * u * by;
      if (s > 0 && !writer.push(x0, y0, x1, y1, 1, red, green, blue, alpha, 1, ALWAYS)) return;
      x0 = x1;
      y0 = y1;
    }
  }
  // The node it fires from lights up while the strand is alive.
  for (let k = 0; k < NODE_SIDES; k++) {
    const [ax, ay] = NODE_CIRCLE[k] as readonly [number, number];
    const [bx, by] = NODE_CIRCLE[k + 1] as readonly [number, number];
    writer.push(
      ox + ax * NODE_RING,
      oy + ay * NODE_RING,
      ox + bx * NODE_RING,
      oy + by * NODE_RING,
      1,
      red,
      green,
      blue,
      0.9 * fade,
      1,
      ALWAYS,
    );
  }
  if (head < 1) return;
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
  const buffers = segmentBuffers(MAX_BUNDLES * (9 * BUNDLE_STEPS + NODE_SIDES + 1));
  const writer = segmentWriter(buffers);
  return {
    name: "bundles",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      writer.begin();
      governor.prepare(frame);
      if (frame.motion.reduced) return; // reduced motion: no strands (DESIGN.md "Motion")
      const positions = layout.positions;
      if (positions === null) return;
      ring.sync();
      const { store, graph } = model;
      const life = BUNDLE_MS * frame.motion.speed; // the wall-clock life, in run time
      // Same range as window.active(t, life), without allocating a tuple each frame.
      const start = store.firstAtOrAfter(frame.t - life);
      const end = store.cursorAt(frame.t);
      if (start >= end) return;
      const { cx, cy, r } = frame.ring;
      const radius = webRadius(frame.ring);
      const rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      const arc = landingArc(frame.ring, frame.height);
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
        // It fires at the function's ring card where the card stood then, within AIM of its
        // node's bearing, and follows the ring from there; a function without a card is aimed
        // at along its own node's direction.
        const ox = positions[from * 2] as number;
        const oy = positions[from * 2 + 1] as number;
        const [lo, hi] = aimRange(Math.atan2(oy, ox), arc);
        const card = ring.cardOf.get(graph.files[to] as string);
        let fired: number;
        let turned = 0;
        if (card !== undefined) {
          const then = rotationAt(ring, store.time[i] as number, frame.motion, frame.focus);
          fired =
            ((ring.angles.start[card] as number) + (ring.angles.end[card] as number)) / 2 + then;
          turned = rotation - then;
        } else {
          fired = Math.atan2(positions[to * 2 + 1] as number, positions[to * 2] as number);
        }
        const angle = landingAngle(fired, turned, lo, hi);
        bundles++;
        drawBundle(
          writer,
          cx + ox * radius,
          cy + oy * radius,
          cx + Math.cos(angle) * (r - 3),
          cy + Math.sin(angle) * (r - 3),
          -Math.sin(angle),
          Math.cos(angle),
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
