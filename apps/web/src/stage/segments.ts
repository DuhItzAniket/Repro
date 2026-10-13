/**
 * The stage's line primitive (ADR-0008): one instanced, anti-aliased quad per segment, drawn
 * in a single call per layer with additive blending. Edges, streaks, ticks and bundles are all
 * segments; only what each layer writes differs.
 */
import { type AttributeSpec, InstanceBuffers } from "./instances";

/** Per-instance attributes. Coordinates are stage CSS pixels with y pointing down. */
export const SEGMENT_ATTRIBUTES: readonly AttributeSpec[] = [
  { name: "a", size: 2 }, // start x, y
  { name: "b", size: 2 }, // end x, y
  { name: "color", size: 4 }, // r, g, b in 0–1, alpha
  { name: "shape", size: 2 }, // width in px; alpha at the start relative to the end (tails)
];

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
        generation = buffers.generation;
      }
    },
    push(ax, ay, bx, by, width, r, g, b, alpha, tail) {
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
      buffers.count = i + 1;
      return true;
    },
  };
}
