/**
 * The dependency-web layers (B05, restyled in B14; DESIGN.md "Dependency web"):
 * - **edges**: every graph edge as a thin arc, written once. The shader reveals each edge when
 *   its `graph.edge` event happens and flares it briefly (recency), so playback and scrubbing
 *   cost no uploads. The web fills a disc just inside the ring, whose centre is left of the
 *   stage: the stage shows long arcs crossing its right part, like the reference.
 * - **nodes**: the run's nodes, tests and symbols, as small hollow circles scattered across the
 *   visible web (the layout's `placeNode` rule), revealed with their `graph.node` events: the
 *   points strands fire from.
 * - **markers**: tiny hollow circles on the nodes in the latest blast radius.
 * - **bundles** (bunches of strands): when an event names a function, a test or a file, a bunch
 *   fires at its section of the wheel (its file's ring card) when that section is on screen, like
 *   the reference's (B14). Each strand comes from its own node, one of the nodes connected to
 *   what the event is about (`ReachIndex`), and they converge side by side on the section. Each
 *   strand is a dim line along which a bullet shoots to the ring, where a bar flashes. Then the
 *   section answers outside the wheel: its recent events shoot out as lines and rebound into the
 *   rim. The strands stay attached to their nodes while their landing ends follow the section as
 *   the ring turns, then fade (1 s). Bunches are a pure function of the events in the window, `t`
 *   and the motion settings.
 *
 * Durations are wall-clock (ADR-0011). The flash governor decides which bundles are drawn and
 * which edges and markers flare; reduced motion draws no bundles and the host turns flares off.
 */
import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import type { EdgeType } from "../../model/graph";
import type { Ring } from "../../shell/layout";
import { outerRadius, ringTracker, webRadius } from "../geometry";
import type { FlashGovernor } from "../governor";
import type { InstanceBuffers } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { targetFile } from "../ring/content";
import { pinnedCard, type RingModel, rotationAt } from "../ring/layers";
import { RING_DRIFT } from "../ring/rotation";
import { cardCentre, eventSymbol, sectionAngle } from "../ring/sections";
import {
  ALWAYS,
  type Recency,
  type SegmentWriter,
  segmentBuffers,
  segmentWriter,
} from "../segments";
import { type Rgb, TINTS, tintOf, travel } from "../streams/style";
import { arcPieces, edgeHash, writeArc } from "./arcs";
import type { LayoutService } from "./layout-service";
import { MAX_BUNCH, type ReachIndex } from "./reach";

export const EDGE_RECENCY: Recency = { flare: 2.5, flareMs: 1500 };
export const EDGE_STYLE: Readonly<Record<EdgeType, { alpha: number; width: number }>> = {
  imports: { alpha: 0.17, width: 1 },
  calls: { alpha: 0.22, width: 1 },
  covers: { alpha: 0.12, width: 1 },
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
          pieces += arcPieces(
            x(s),
            y(s),
            x(t),
            y(t),
            edgeHash(s, t),
            frame.ring,
            frame.width,
            frame.height,
          );
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
          frame.ring,
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

/** A bunch's life, wall-clock ms: its bullets' trip to the ring, then the outside lines' bounce. */
export const BUNDLE_MS = 1000;
/** Most bunches drawn at once. */
export const MAX_BUNDLES = 16;
/** Straight pieces along a whole strand. */
export const BUNDLE_STEPS = 24;
/** Share of a bunch's life its bullets take to travel from their nodes to the ring. */
export const TRAVEL = 0.4;
/** From this share of its life on, the strands fade, still attached at both ends. */
export const FADE_FROM = 0.6;
/**
 * The brightest a dim line gets: the strands inside the wheel and the lines outside it. Both are
 * MAX-blended, so a pixel under one rises at most to 0.32 encoded (relative luminance 0.084) from
 * the #080808 background (0.0024): less than WCAG 2.3.1's 10% change, so they are never flashes.
 */
export const DIM_MAX = 0.32;
export const STRAND_ALPHA = DIM_MAX;
const BULLET_ALPHA = 0.95;
/** A bullet's length along its strand, px (at most 30% of the strand), and its pieces. */
const BULLET_PX = 80;
const BULLET_PIECES = 6;
const BULLET_WIDTH = 2;
/** The ring a node shows while its bullet is in flight, px. */
const NODE_RING = 4.5;
const NODE_SIDES = 10;
const NODE_CIRCLE = Array.from({ length: NODE_SIDES + 1 }, (_, i) => {
  const angle = (i / NODE_SIDES) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
const TAU = Math.PI * 2;
/** Outside lines per hit: the section's most recent events. */
export const RAY_COUNT = 24;
/** An outside line reaches at most this share of the ring radius beyond the outer rim. */
export const RAY_ROOM = 0.42;
const RAY_WIDTH = 1.6;
/** An outside line's alpha at its tip, relative to the rim. */
const RAY_TIP = 0.6;
/** Share of an outside line's bounce spent shooting out; the rest it rebounds. */
export const RAY_OUT = 0.35;
/** Outside lines start their bounce up to this share of it apart, so a spray is not a block. */
const RAY_STAGGER = 0.2;

/** How far along its strand a bullet is at `life` (0–1): it accelerates out, then eases in. */
export const bulletAt = (life: number): number => {
  const x = Math.min(1, Math.max(0, life / TRAVEL));
  return x * x * (3 - 2 * x);
};

/** A strand's brightness at `life`: full until FADE_FROM, then fading to nothing at the end. */
export const strandFade = (life: number): number =>
  life <= FADE_FROM ? 1 : 1 - ((Math.min(1, life) - FADE_FROM) / (1 - FADE_FROM)) ** 2;

/**
 * How far out an outside line reaches at `u`, 0–1 of its bounce: it shoots out (ease-out) to its
 * full length over RAY_OUT, then rebounds to the rim (ease-in) and is gone.
 */
export function rayExtent(u: number): number {
  if (u <= 0 || u >= 1) return 0;
  if (u < RAY_OUT) return 1 - (1 - u / RAY_OUT) ** 3;
  const back = (u - RAY_OUT) / (1 - RAY_OUT);
  return 1 - back * back;
}

/**
 * How far a strand's landing end follows the ring as it turns, radians: the ring's drift over a
 * strand's life (both wall-clock, so the same at every replay speed). A focus snap can turn the
 * ring further; the strand keeps to this, so its length stays bounded.
 */
export const FOLLOW = RING_DRIFT * BUNDLE_MS;

/** Margin inside the stage a landing point must keep to count as on screen, px. */
const SCREEN_MARGIN = 24;

/** Whether the point on the inner rim at screen angle `angle` is on the stage. */
export function landsOnStage(angle: number, ring: Ring, width: number, height: number): boolean {
  const x = ring.cx + Math.cos(angle) * ring.r;
  const y = ring.cy + Math.sin(angle) * ring.r;
  return (
    x >= SCREEN_MARGIN &&
    x <= width - SCREEN_MARGIN &&
    y >= SCREEN_MARGIN &&
    y <= height - SCREEN_MARGIN
  );
}

/** Wraps an angle to (−π, π]. */
function wrap(angle: number): number {
  let a = angle % TAU;
  if (a <= -Math.PI) a += TAU;
  if (a > Math.PI) a -= TAU;
  return a;
}

/**
 * Where a bunch lands, as a screen angle on the ring: its section where the section stood when
 * the bunch fired (`fired`), then following the ring as it has turned since, by at most FOLLOW
 * either way (a focus snap is not followed, so strands stay bounded).
 */
export function landingAngle(fired: number, turned: number): number {
  return wrap(fired) + Math.min(FOLLOW, Math.max(-FOLLOW, turned));
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

/** What an event's strands are about. */
export const HIT_FUNCTION = 0;
export const HIT_TEST = 1;
export const HIT_FILE = 2;

/** An event's hit: its section's file, what it is about, and the node that fired first. */
export interface StrandHit {
  file: string;
  role: number;
  /** The function or test node (-1 for a file). */
  target: number;
  /** The node that fired, drawn first (-1 for none). */
  first: number;
}

/** A fresh scratch hit. */
export const newHit = (): StrandHit => ({ file: "", role: HIT_FILE, target: -1, first: -1 });

/**
 * Fills `out` with what `event`'s strands are about: a function (its tests and callers fire,
 * the test that ran first), a test (it and the functions it reaches fire) or a file (its own
 * nodes fire). False when the event names none of them.
 */
export function strandHit(model: CockpitModel, event: ReproEvent, out: StrandHit): boolean {
  const { graph } = model;
  const symbol = eventSymbol(event);
  const fn = symbol === undefined ? undefined : graph.nodeForSymbol(symbol);
  const testId = event.target?.test;
  const test = testId === undefined || testId === null ? undefined : graph.byId.get(testId);
  if (fn !== undefined) {
    out.role = HIT_FUNCTION;
    out.target = fn;
    out.first = test ?? -1;
    out.file = graph.files[fn] as string;
    return true;
  }
  if (test !== undefined) {
    out.role = HIT_TEST;
    out.target = test;
    out.first = test;
    out.file = graph.files[test] as string;
    return true;
  }
  const file = targetFile(event.target);
  if (file === undefined) return false;
  out.role = HIT_FILE;
  out.target = -1;
  out.first = -1;
  out.file = file;
  return true;
}

/**
 * How far inside the landing point a strand's control point sits, as a share of its length
 * (0.2–0.28): the strand arrives at the rim along the ring's radius, like the reference's.
 */
const strandBend = (h: number): number => 0.2 + ((h >>> 8) % 100) / 1250;
const MAX_BEND = 0.28;
/**
 * How far the control point also sits along the ring's turning direction, as a share of the
 * strand's length: strands sweep into the rim from the side the cards are moving towards.
 */
const SWEEP = 0.1;
/** Spacing of a bunch's strands where they land side by side on the bar, px. */
export const LAND_SPACING = 2.4;
/** A strand of a bunch starts its trip up to this share of the life after the bunch fires. */
const DELAY = 0.06;

/** Length of the bar a bunch of `n` strands lands on, px. */
export const pinLength = (n: number): number => n * LAND_SPACING + 8;

/**
 * Upper bound of the area one strand's bullet sweeps, in CSS px², for the flash governor, for a
 * strand at most `len` long (node to landing point). The curve is no longer than its control
 * polygon (node → control point → landing), at most len · (1 + 2 · √(bend² + SWEEP²)); the bullet
 * is a 2 px line along it, with 2 px of anti-aliasing fringe and its pieces' ends. Plus the ring
 * on its node. The dim line is not counted: it is MAX-blended at DIM_MAX, so it is not a flash.
 */
export function strandArea(len: number): number {
  // sqrt, not Math.hypot: it is correctly rounded on every engine, so pins agree across OSes.
  const curve = len * (1 + 2 * Math.sqrt(MAX_BEND * MAX_BEND + SWEEP * SWEEP));
  const bullet = (curve + 2 * BULLET_PIECES) * (BULLET_WIDTH + 2);
  const ring = NODE_SIDES * segmentArea(2 * NODE_RING * Math.sin(Math.PI / NODE_SIDES), 1);
  return bullet + ring;
}

/** Upper bound of a bunch's bar's area in CSS px². */
export const pinArea = (n: number): number => segmentArea(pinLength(n), 2);

/** Upper bound of a segment's drawn area in CSS px² (2 px of anti-aliasing fringe each way). */
export function segmentArea(len: number, width: number): number {
  return (len + 2) * (width + 2);
}

/** A point on a strand's curve (a scratch pair, so frames do not allocate). */
const at = new Float64Array(2);
function curvePoint(
  ox: number,
  oy: number,
  kx: number,
  ky: number,
  qx: number,
  qy: number,
  u: number,
): void {
  const v = 1 - u;
  at[0] = v * v * ox + 2 * v * u * kx + u * u * qx;
  at[1] = v * v * oy + 2 * v * u * ky + u * u * qy;
}

/** A strand of a bunch's own hash, for its bend and delay. */
const memberHash = (h: number, k: number): number =>
  Math.imul(h ^ Math.imul(k + 1, 0x9e3779b9), 0x85ebca6b) >>> 0;

/** The writers a bunch draws into. */
interface BunchWriters {
  /** Bullets, node rings and bars (additive, counted by the flash governor). */
  readonly bright: SegmentWriter;
  /** The dim strands inside the wheel (MAX-blended). */
  readonly lines: SegmentWriter;
  /** The lines outside the wheel (MAX-blended). */
  readonly rays: SegmentWriter;
}

/**
 * Writes one strand of a bunch at `life` (0–1 of its own trip), from its node (ox, oy) to its
 * landing point (qx, qy) on the inner rim: a dim line, along which a bullet shoots from the node
 * to the ring (the node lights up as it fires). The line is revealed behind the bullet, stays
 * attached to the node while its landing end follows the ring as it turns, and fades from
 * FADE_FROM on. `tx, ty` is the ring's turning direction at the landing point (unit length).
 */
function drawStrand(
  writers: BunchWriters,
  ox: number,
  oy: number,
  qx: number,
  qy: number,
  tx: number,
  ty: number,
  life: number,
  h: number,
  tint: Rgb,
): void {
  const dx = qx - ox;
  const dy = qy - oy;
  const len = Math.sqrt(dx * dx + dy * dy);
  if (len < 1 || life <= 0) return;
  // The control point sits inside the landing point along the radius (the bar's normal), so the
  // strand arrives at the rim along the radius, and a little along the turning direction. Node,
  // control point and landing point are all inside the inner rim, so the curve is too.
  const bend = strandBend(h) * len;
  const sweep = SWEEP * len;
  const kx = qx - ty * bend + tx * sweep;
  const ky = qy + tx * bend + ty * sweep;
  const fade = strandFade(life);
  const reached = bulletAt(life);
  const [red, green, blue] = tint;

  // The dim strand, revealed behind the bullet.
  const steps = Math.max(1, Math.ceil(BUNDLE_STEPS * reached));
  let x0 = ox;
  let y0 = oy;
  for (let s = 1; s <= steps; s++) {
    curvePoint(ox, oy, kx, ky, qx, qy, (reached * s) / steps);
    const x1 = at[0] as number;
    const y1 = at[1] as number;
    const alpha = STRAND_ALPHA * fade;
    if (!writers.lines.push(x0, y0, x1, y1, 1, red, green, blue, alpha, 1, ALWAYS)) return;
    x0 = x1;
    y0 = y1;
  }
  if (life >= TRAVEL) return;

  // The bullet: a short bright stretch ending at its head, brightest at the head.
  const share = Math.min(0.3, BULLET_PX / len);
  const from = Math.max(0, reached - share);
  curvePoint(ox, oy, kx, ky, qx, qy, from);
  let bx = at[0] as number;
  let by = at[1] as number;
  for (let k = 0; k < BULLET_PIECES; k++) {
    curvePoint(ox, oy, kx, ky, qx, qy, from + ((reached - from) * (k + 1)) / BULLET_PIECES);
    const ex = at[0] as number;
    const ey = at[1] as number;
    const alpha = (BULLET_ALPHA * (k + 1)) / BULLET_PIECES;
    writers.bright.push(bx, by, ex, ey, BULLET_WIDTH, red, green, blue, alpha, k / (k + 1), ALWAYS);
    bx = ex;
    by = ey;
  }
  // The node it fires from lights up while the bullet is in flight.
  const lit = 0.8 * (1 - life / TRAVEL);
  for (let k = 0; k < NODE_SIDES; k++) {
    const [ax, ay] = NODE_CIRCLE[k] as readonly [number, number];
    const [cx, cy] = NODE_CIRCLE[k + 1] as readonly [number, number];
    writers.bright.push(
      ox + ax * NODE_RING,
      oy + ay * NODE_RING,
      ox + cx * NODE_RING,
      oy + cy * NODE_RING,
      1,
      red,
      green,
      blue,
      lit,
      1,
      ALWAYS,
    );
  }
}

/** A strand's own life within its bunch's: it starts up to DELAY later and ends with the bunch. */
export const memberLife = (life: number, h: number, k: number): number => {
  const delay = ((memberHash(h, k) & 0xffff) / 0xffff) * DELAY;
  return (life - delay) / (1 - delay);
};

/** Where an outside line is in its bounce at bunch life `life`, 0–1 (≤ 0 or ≥ 1: not drawn). */
export const rayLife = (life: number, h: number): number => {
  const delay = ((h >>> 16) / 0xffff) * RAY_STAGGER;
  return (life - TRAVEL - delay * (1 - TRAVEL)) / ((1 - TRAVEL) * (1 - delay));
};

/**
 * Sorts a bunch's first `n` nodes by their bearing from the ring's centre, so its strands land
 * on the bar in the order their nodes sit and do not cross there. Insertion sort on scratch
 * arrays: allocation-free.
 */
export function sortByBearing(
  members: Int32Array,
  n: number,
  positions: Float32Array,
  bearings: Float64Array,
): void {
  for (let k = 0; k < n; k++) {
    const node = members[k] as number;
    bearings[k] = Math.atan2(positions[node * 2 + 1] as number, positions[node * 2] as number);
  }
  for (let k = 1; k < n; k++) {
    const node = members[k] as number;
    const bearing = bearings[k] as number;
    let j = k - 1;
    while (j >= 0 && (bearings[j] as number) > bearing) {
      members[j + 1] = members[j] as number;
      bearings[j + 1] = bearings[j] as number;
      j--;
    }
    members[j + 1] = node;
    bearings[j + 1] = bearing;
  }
}

/** The bundle layer: bullets, node rings and bars, plus the MAX-blended dim lines it writes. */
export interface BundleLayer extends StageLayer {
  /** The dim strands inside the wheel: add it after this layer. */
  readonly lines: StageLayer;
  /** The lines outside the wheel: add it after this layer. */
  readonly rays: StageLayer;
}

/** A layer whose buffers another layer writes; it only needs to be uploaded after that one. */
function writtenBy(name: string, buffers: InstanceBuffers): StageLayer {
  return { name, primitive: "segments", buffers, blend: "max", update() {} };
}

export function bundleLayer(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
  ring: RingModel,
): BundleLayer {
  const buffers = segmentBuffers(MAX_BUNDLES * (MAX_BUNCH * (BULLET_PIECES + NODE_SIDES) + 1));
  const lineBuffers = segmentBuffers(MAX_BUNDLES * MAX_BUNCH * BUNDLE_STEPS);
  const rayBuffers = segmentBuffers(MAX_BUNDLES * RAY_COUNT);
  const writers: BunchWriters = {
    bright: segmentWriter(buffers),
    lines: segmentWriter(lineBuffers),
    rays: segmentWriter(rayBuffers),
  };
  const members = new Int32Array(MAX_BUNCH);
  const bearings = new Float64Array(MAX_BUNCH);
  const recent = new Int32Array(RAY_COUNT);
  const hit = newHit();
  return {
    name: "bundles",
    primitive: "segments",
    buffers,
    lines: writtenBy("strands", lineBuffers),
    rays: writtenBy("rays", rayBuffers),
    update(frame: StageFrame) {
      writers.bright.begin();
      writers.lines.begin();
      writers.rays.begin();
      governor.prepare(frame);
      if (frame.motion.reduced) return; // reduced motion: no strands (DESIGN.md "Motion")
      // While the user pins a file the ring is held still; strands wait (the governor's
      // decisions assume the ring's own motion).
      if (pinnedCard(ring, frame.focus) >= 0) return;
      const positions = layout.positions;
      if (positions === null) return;
      ring.sync();
      const { store } = model;
      const life = BUNDLE_MS * frame.motion.speed; // the wall-clock life, in run time
      // Same range as window.active(t, life), without allocating a tuple each frame.
      const start = store.firstAtOrAfter(frame.t - life);
      const end = store.cursorAt(frame.t);
      if (start >= end) return;
      const { cx, cy, r } = frame.ring;
      const radius = webRadius(frame.ring);
      const rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      const rim = r - 3;
      const outer = outerRadius(frame.ring) + 2;
      let bunches = 0;
      for (let i = end - 1; i >= start && bunches < MAX_BUNDLES; i--) {
        if (!governor.bundle(i)) continue;
        const event = store.event(i);
        if (event === null || !strandHit(model, event, hit)) continue;
        // It fires at its section of the wheel (its file's card), where the section stood then,
        // if it was on screen, and follows the ring from there.
        const card = ring.cardOf.get(hit.file);
        if (card === undefined) continue;
        const then = rotationAt(ring, store.time[i] as number, frame.motion, frame.focus);
        const fired = cardCentre(ring, card) + then;
        if (!landsOnStage(fired, frame.ring, frame.width, frame.height)) continue;
        const unit = rim / radius; // the landing point in the layout's unit coordinates
        const n = placedBunch(
          governor.reach,
          hit,
          i,
          members,
          positions,
          Math.cos(fired) * unit,
          Math.sin(fired) * unit,
        );
        if (n === 0) continue;
        bunches++;
        const turned = landingAngle(fired, rotation - then) - wrap(fired);
        const angle = wrap(fired) + turned;
        const qx = cx + Math.cos(angle) * rim;
        const qy = cy + Math.sin(angle) * rim;
        const tx = -Math.sin(angle);
        const ty = Math.cos(angle);
        const age = (frame.t - (store.time[i] as number)) / life;
        const h = hash32(event.id);
        const tint = TINTS[tintOf(event)];
        sortByBearing(members, n, positions, bearings);
        for (let k = 0; k < n; k++) {
          const node = members[k] as number;
          const offset = (k - (n - 1) / 2) * LAND_SPACING;
          drawStrand(
            writers,
            cx + (positions[node * 2] as number) * radius,
            cy + (positions[node * 2 + 1] as number) * radius,
            qx + tx * offset,
            qy + ty * offset,
            tx,
            ty,
            memberLife(age, h, k),
            memberHash(h, k),
            tint,
          );
        }
        if (age < TRAVEL) continue;
        // The bar the bunch hit, like the reference's bright pins at the rim.
        const half = pinLength(n) / 2;
        const flash = 0.9 * (1 - (age - TRAVEL) / (1 - TRAVEL));
        writers.bright.push(
          qx - tx * half,
          qy - ty * half,
          qx + tx * half,
          qy + ty * half,
          2,
          tint[0],
          tint[1],
          tint[2],
          flash,
          1,
          ALWAYS,
        );
        // Outside the wheel the section answers: its recent events shoot out as lines from the
        // outer rim, each in its own place on the section, and rebound into the rim.
        const count = governor.reach.recentEvents(hit.file, i, recent);
        for (let k = 0; k < count; k++) {
          const j = recent[k] as number;
          const past = store.event(j);
          if (past === null) continue;
          const hp = hash32(past.id);
          const u = rayLife(age, hp);
          const extent = rayExtent(u);
          if (extent <= 0) continue;
          const local = sectionAngle(ring, hit.file, hp);
          const a = local + then + turned;
          const dx = Math.cos(a);
          const dy = Math.sin(a);
          const length =
            RAY_ROOM * r * rayReach(past, (Math.imul(hp, 0x9e3779b1) >>> 0) / 4294967296);
          const shade = TINTS[tintOf(past)];
          writers.rays.push(
            cx + dx * outer,
            cy + dy * outer,
            cx + dx * (outer + length * extent),
            cy + dy * (outer + length * extent),
            RAY_WIDTH,
            shade[0],
            shade[1],
            shade[2],
            DIM_MAX * RAY_TIP,
            1 / RAY_TIP, // brightest at the rim, like the reference's
            ALWAYS,
          );
        }
      }
    },
  };
}

/**
 * How far an outside line reaches, as a share of RAY_ROOM: further for findings and slow tests,
 * with a per-event spread (`h`, 0–1), so a spray ends raggedly.
 */
export function rayReach(event: ReproEvent, h: number): number {
  const travelled = Math.min(1, Math.max(0, (travel(event) - 90) / 530));
  return 0.45 + 0.3 * travelled + 0.25 * h;
}

/** Nodes considered for a bunch, before the nearest are chosen. */
const CANDIDATES = new Int32Array(64);
const DISTANCES = new Float64Array(64);

/**
 * The bunch for the event at store index `at` (the same for the layer and the flash governor):
 * the node that fired, then the nodes connected to what the event is about (`hit`) nearest the
 * landing point (lx, ly) in the layout's unit coordinates, up to `out.length`, keeping only
 * nodes the layout has placed. Returns how many nodes it wrote to `out`. Allocation-free.
 */
export function placedBunch(
  reach: ReachIndex,
  hit: StrandHit,
  at: number,
  out: Int32Array,
  positions: Float32Array,
  lx: number,
  ly: number,
): number {
  let found = 0;
  if (hit.first >= 0) CANDIDATES[found++] = hit.first;
  if (hit.role === HIT_FUNCTION)
    found = reach.reachersOf(hit.target, at, hit.first, CANDIDATES, found);
  else if (hit.role === HIT_TEST)
    found = reach.reachedBy(hit.target, at, hit.first, CANDIDATES, found);
  else found = reach.membersOf(hit.file, at, -1, CANDIDATES, found);
  let placed = 0;
  for (let k = 0; k < found; k++) {
    const node = CANDIDATES[k] as number;
    if (node * 2 + 1 >= positions.length) continue;
    const dx = (positions[node * 2] as number) - lx;
    const dy = (positions[node * 2 + 1] as number) - ly;
    CANDIDATES[placed] = node;
    DISTANCES[placed] = dx * dx + dy * dy;
    placed++;
  }
  // The node that fired stays first; the rest go nearest first (insertion sort, stable).
  const keepFirst = placed > 0 && hit.first >= 0 && CANDIDATES[0] === hit.first ? 1 : 0;
  for (let k = keepFirst + 1; k < placed; k++) {
    const node = CANDIDATES[k] as number;
    const d = DISTANCES[k] as number;
    let j = k - 1;
    while (j >= keepFirst && (DISTANCES[j] as number) > d) {
      CANDIDATES[j + 1] = CANDIDATES[j] as number;
      DISTANCES[j + 1] = DISTANCES[j] as number;
      j--;
    }
    CANDIDATES[j + 1] = node;
    DISTANCES[j + 1] = d;
  }
  const n = Math.min(placed, out.length);
  for (let k = 0; k < n; k++) out[k] = CANDIDATES[k] as number;
  return n;
}

export function webLayers(
  model: CockpitModel,
  layout: LayoutService,
  governor: FlashGovernor,
  ring: RingModel,
): StageLayer[] {
  const bundles = bundleLayer(model, layout, governor, ring);
  return [
    edgeLayer(model, layout, governor),
    nodeLayer(model, layout),
    markerLayer(model, layout, governor),
    bundles,
    bundles.lines,
    bundles.rays,
  ];
}
