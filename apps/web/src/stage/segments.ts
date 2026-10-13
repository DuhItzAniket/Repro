/**
 * The stage's line primitive (ADR-0008): one instanced, anti-aliased quad per segment, drawn
 * in a single call per layer with additive blending. Edges, streaks, ticks, markers and bundles
 * are all segments; only what each layer writes differs.
 *
 * Each segment also carries the presentation time at which it **appears**. The shader hides it
 * before that time and brightens it briefly afterwards (recency). So a static layer, such as
 * the dependency web, is uploaded once and then revealed by the clock alone, with no per-frame
 * uploads and exact results when scrubbing.
 */
import { type AttributeSpec, InstanceBuffers } from "./instances";

/** Per-instance attributes. Coordinates are stage CSS pixels with y pointing down. */
export const SEGMENT_ATTRIBUTES: readonly AttributeSpec[] = [
  { name: "a", size: 2 }, // start x, y
  { name: "b", size: 2 }, // end x, y
  { name: "color", size: 4 }, // r, g, b in 0–1, base alpha
  { name: "shape", size: 2 }, // width in px; alpha at the start relative to the end (tails)
  { name: "appear", size: 1 }, // presentation time (ms) the segment appears at
  { name: "flare", size: 1 }, // share of the layer's recency flare this segment gets (0–1)
];

/** `appear` for segments that are always visible (layers that rewrite every frame). */
export const ALWAYS = -1e9;

/**
 * Per-layer recency parameters (shader uniforms). `flareMs` is wall-clock time (ADR-0011): the
 * host scales it by the replay speed, and turns flares off under reduced motion.
 */
export interface Recency {
  /** Extra alpha multiple right after appearing: 0 = none, 2 = three times as bright. */
  readonly flare: number;
  /** Decay time constant of the flare, wall-clock ms. */
  readonly flareMs: number;
}

export const NO_RECENCY: Recency = { flare: 0, flareMs: 1 };

/**
 * The alpha multiplier the segment shader applies at presentation time `t` (mirrors
 * `segment.vert.glsl`; tested against it by value). `recency` is as the shader receives it, in
 * presentation time; `flare` is the segment's own share of the flare.
 */
export function recencyFactor(appear: number, t: number, recency: Recency, flare = 1): number {
  const dt = t - appear;
  if (dt < 0) return 0;
  return 1 + recency.flare * flare * Math.exp(-dt / recency.flareMs);
}

/** The alpha a segment is drawn with at `t` (before anti-aliasing and tails). */
export function segmentAlpha(
  base: number,
  appear: number,
  t: number,
  recency: Recency,
  flare = 1,
): number {
  return Math.min(1, base * recencyFactor(appear, t, recency, flare));
}

export function segmentBuffers(capacity: number): InstanceBuffers {
  return new InstanceBuffers(SEGMENT_ATTRIBUTES, capacity);
}

export interface SegmentWriter {
  readonly buffers: InstanceBuffers;
  /** Starts rewriting the buffers: resets the count and marks them changed (no allocation). */
  begin(): void;
  /** Appends one segment; returns false when `limit` instances are already written. */
  push(
    ax: number,
    ay: number,
    bx: number,
    by: number,
    width: number,
    r: number,
    g: number,
    b: number,
    alpha: number,
    tail: number,
    appear?: number,
    flare?: number,
  ): boolean;
}

/** A writer that never allocates during a frame. `reserve` capacity up front for the maximum. */
export function segmentWriter(
  buffers: InstanceBuffers,
  limit = Number.POSITIVE_INFINITY,
): SegmentWriter {
  let a = buffers.array("a");
  let bb = buffers.array("b");
  let color = buffers.array("color");
  let shape = buffers.array("shape");
  let appearAt = buffers.array("appear");
  let flares = buffers.array("flare");
  let generation = buffers.generation;
  return {
    buffers,
    begin() {
      buffers.count = 0;
      buffers.version++;
      if (generation !== buffers.generation) {
        a = buffers.array("a");
        bb = buffers.array("b");
        color = buffers.array("color");
        shape = buffers.array("shape");
        appearAt = buffers.array("appear");
        flares = buffers.array("flare");
        generation = buffers.generation;
      }
    },
    push(ax, ay, bx, by, width, r, g, b, alpha, tail, appear = ALWAYS, flare = 1) {
      const i = buffers.count;
      if (i >= limit || i >= buffers.capacity) return false;
      a[i * 2] = ax;
      a[i * 2 + 1] = ay;
      bb[i * 2] = bx;
      bb[i * 2 + 1] = by;
      color[i * 4] = r;
      color[i * 4 + 1] = g;
      color[i * 4 + 2] = b;
      color[i * 4 + 3] = alpha;
      shape[i * 2] = width;
      shape[i * 2 + 1] = tail;
      appearAt[i] = appear;
      flares[i] = flare;
      buffers.count = i + 1;
      return true;
    },
  };
}
