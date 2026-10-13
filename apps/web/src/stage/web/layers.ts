/**
 * The dependency-web layers (B05; DESIGN.md "Dependency web"):
 * - **edges**: every graph edge as a thin line, written once. The shader reveals each edge when
 *   its `graph.edge` event happens and flares it briefly (recency), so playback and scrubbing
 *   cost no uploads.
 * - **markers**: tiny hollow circles on the nodes in the latest blast radius.
 * - **bundles**: bright sheaves of 8–20 near-parallel Bézier curves along a path an event
 *   touches (a test reaching a function), fading over 1.2 s. They are a pure function of the
 *   events in the window and `t`.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { kindCode } from "../../model/codes";
import type { EdgeType } from "../../model/graph";
import { ringTracker, WEB_INSET } from "../geometry";
import type { StageFrame, StageLayer } from "../layer";
import {
  ALWAYS,
  type Recency,
  type SegmentWriter,
  segmentBuffers,
  segmentWriter,
} from "../segments";
import type { LayoutService } from "./layout-service";

export const EDGE_RECENCY: Recency = { flare: 2.5, flareMs: 1500 };
export const EDGE_STYLE: Readonly<Record<EdgeType, { alpha: number; width: number }>> = {
  imports: { alpha: 0.1, width: 1 },
  calls: { alpha: 0.16, width: 1 },
  covers: { alpha: 0.07, width: 1 },
};

const EDGE_TYPES: readonly EdgeType[] = ["imports", "calls", "covers"];

export function edgeLayer(model: CockpitModel, layout: LayoutService): StageLayer {
  const buffers = segmentBuffers(1024);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawnGraph = -1;
  let drawnLayout = -1;
  return {
    name: "edges",
    primitive: "segments",
    buffers,
    recency: EDGE_RECENCY,
    update(frame: StageFrame) {
      const { graph } = model;
      const moved = ringChanged(frame.ring);
      if (graph.version === drawnGraph && layout.version === drawnLayout && !moved) return;
      const positions = layout.positions;
      if (positions === null) return;
      drawnGraph = graph.version;
      drawnLayout = layout.version;
      const { cx, cy, r } = frame.ring;
      const radius = r - WEB_INSET;
      buffers.reserve(graph.edgeCount);
      writer.begin();
      for (let e = 0; e < graph.edgeCount; e++) {
        const s = graph.edgeSource[e] as number;
        const t = graph.edgeTarget[e] as number;
        if (t * 2 + 1 >= positions.length || s * 2 + 1 >= positions.length) continue; // newer than the layout
        const style = EDGE_STYLE[EDGE_TYPES[graph.edgeType[e] as number] ?? "imports"];
        writer.push(
          cx + (positions[s * 2] as number) * radius,
          cy + (positions[s * 2 + 1] as number) * radius,
          cx + (positions[t * 2] as number) * radius,
          cy + (positions[t * 2 + 1] as number) * radius,
          style.width,
          1,
          1,
          1,
          style.alpha,
          1,
          model.store.time[graph.edgeEvent[e] as number] as number,
        );
      }
    },
  };
}

const MARKER_SIDES = 8;
const MARKER_RADIUS = 3;
const CIRCLE = Array.from({ length: MARKER_SIDES + 1 }, (_, i) => {
  const angle = (i / MARKER_SIDES) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
export const MARKER_RECENCY: Recency = { flare: 1.2, flareMs: 900 };

export function markerLayer(model: CockpitModel, layout: LayoutService): StageLayer {
  const buffers = segmentBuffers(MARKER_SIDES * 128);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawnBlast = -2;
  let drawnLayout = -1;
  return {
    name: "markers",
    primitive: "segments",
    buffers,
    recency: MARKER_RECENCY,
    update(frame: StageFrame) {
      const blast = model.kinds.lastIndex("blast.computed", frame.cursor);
      const moved = ringChanged(frame.ring);
      if (blast === drawnBlast && layout.version === drawnLayout && !moved) return;
      const positions = layout.positions;
      if (positions === null) return;
      drawnBlast = blast;
      drawnLayout = layout.version;
      writer.begin();
      const event = blast < 0 ? null : model.store.event(blast);
      if (event?.kind !== "blast.computed") return;
      const { cx, cy, r } = frame.ring;
      const radius = r - WEB_INSET;
      const appear = model.store.time[blast] as number;
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
          );
        }
      };
      for (const item of event.payload.affected) mark(item.symbol_id, 0.4);
      for (const symbol of event.payload.changed) mark(symbol, 0.9);
    },
  };
}

export const BUNDLE_MS = 1200;
export const MAX_BUNDLES = 40;
const BUNDLE_STEPS = 10;
/** Share of a bundle's life spent sweeping from source to target before it fades. */
const SWEEP = 0.25;
const TRACE = kindCode("trace.sample", 1);
const BEHAVIOUR = kindCode("diff.behaviour", 1);

/** Writes one sheaf of curves from p to q at `life` (0–1 of BUNDLE_MS). */
function drawBundle(
  writer: SegmentWriter,
  px: number,
  py: number,
  qx: number,
  qy: number,
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
  // Each bundle bows to one side by 12–24% of its length, chosen by the event's hash.
  const bow = (0.12 + ((h >>> 8) % 100) / 800) * len * ((h & 1) === 1 ? 1 : -1);
  const curves = 8 + (h % 13);
  const fade = (1 - life) * (1 - life);
  const reach = Math.min(1, life / SWEEP); // the sheaf sweeps out first, then fades
  const steps = Math.max(1, Math.ceil(BUNDLE_STEPS * reach));
  const alpha = (flagged ? 0.5 : 0.28) * fade;
  const red = flagged ? 0.71 : 1; // --flag for behaviour differences, white otherwise
  const green = flagged ? 0.56 : 1;
  const blue = flagged ? 0.61 : 1;
  const mx = (px + qx) / 2;
  const my = (py + qy) / 2;
  for (let c = 0; c < curves; c++) {
    const offset = (c - (curves - 1) / 2) * 1.2;
    const ax = px + nx * offset * 0.4;
    const ay = py + ny * offset * 0.4;
    const bx = qx + nx * offset * 0.4;
    const by = qy + ny * offset * 0.4;
    // Near-parallel: the control points spread little more than the endpoints do.
    const kx = mx + nx * (bow + offset * 0.7);
    const ky = my + ny * (bow + offset * 0.7);
    let x0 = ax;
    let y0 = ay;
    for (let s = 1; s <= steps; s++) {
      const u = (reach * s) / steps;
      const v = 1 - u;
      const x1 = v * v * ax + 2 * v * u * kx + u * u * bx;
      const y1 = v * v * ay + 2 * v * u * ky + u * u * by;
      if (!writer.push(x0, y0, x1, y1, 1, red, green, blue, alpha, 1, ALWAYS)) return;
      x0 = x1;
      y0 = y1;
    }
  }
}

export function bundleLayer(model: CockpitModel, layout: LayoutService): StageLayer {
  const buffers = segmentBuffers(MAX_BUNDLES * 20 * BUNDLE_STEPS);
  const writer = segmentWriter(buffers);
  return {
    name: "bundles",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      writer.begin();
      const positions = layout.positions;
      if (positions === null) return;
      const { store, graph } = model;
      // Same range as window.active(t, BUNDLE_MS), without allocating a tuple each frame.
      const start = store.firstAtOrAfter(frame.t - BUNDLE_MS);
      const end = store.cursorAt(frame.t);
      const { cx, cy, r } = frame.ring;
      const radius = r - WEB_INSET;
      let bundles = 0;
      for (let i = end - 1; i >= start && bundles < MAX_BUNDLES; i--) {
        const code = store.kind[i];
        if (code !== TRACE && code !== BEHAVIOUR) continue;
        const event = store.event(i);
        if (event?.kind !== "trace.sample" && event?.kind !== "diff.behaviour") continue;
        const test = event.target?.test;
        const from = test === undefined ? undefined : graph.byId.get(test);
        const to = graph.nodeForSymbol(event.payload.symbol_id);
        if (from === undefined || to === undefined) continue;
        if (Math.max(from, to) * 2 + 1 >= positions.length) continue;
        bundles++;
        drawBundle(
          writer,
          cx + (positions[from * 2] as number) * radius,
          cy + (positions[from * 2 + 1] as number) * radius,
          cx + (positions[to * 2] as number) * radius,
          cy + (positions[to * 2 + 1] as number) * radius,
          (frame.t - (store.time[i] as number)) / BUNDLE_MS,
          hash32(event.id),
          code === BEHAVIOUR,
        );
      }
    },
  };
}

export function webLayers(model: CockpitModel, layout: LayoutService): StageLayer[] {
  return [edgeLayer(model, layout), markerLayer(model, layout), bundleLayer(model, layout)];
}
