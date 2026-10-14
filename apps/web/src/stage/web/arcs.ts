/**
 * Edges of the dependency web drawn as gentle arcs (B14; DESIGN.md "Dependency web"): the
 * reference's web is a hairball of long curves, not straight spokes. Each edge is a quadratic
 * Bézier from its source to its target, bowed to one side by a share of its length that comes
 * from a hash of its endpoints, so the same edge always bends the same way.
 *
 * Most of the web lies off-screen (the ring's centre is left of the stage), so arcs are written
 * only as the sub-segments that touch the stage. The flash governor sizes an edge's flare from
 * the same sub-segments (`arcArea`), so it counts exactly what is drawn.
 */
import type { SegmentWriter } from "../segments";

/** Margin around the stage, px, within which sub-segments are still written. */
const MARGIN = 4;

/** A deterministic 32-bit hash of an edge's endpoints (node indices). */
export function edgeHash(source: number, target: number): number {
  let h = Math.imul(source ^ 0x9e3779b9, 0x85ebca6b) ^ Math.imul(target + 0x632be5ab, 0xc2b2ae35);
  h ^= h >>> 15;
  h = Math.imul(h, 0x2c1b3c6d);
  h ^= h >>> 12;
  h = Math.imul(h, 0x297a2d39);
  h ^= h >>> 15;
  return h >>> 0;
}

/** The arc's bow: its middle moves sideways by 25–60% of its length, to a side from the hash. */
export function arcBow(len: number, h: number): number {
  return (0.25 + (((h >>> 8) % 1000) / 1000) * 0.35) * len * ((h & 1) === 1 ? 1 : -1);
}

/** Straight pieces per arc: about one per 20 px, 2–28, so long arcs stay smooth. */
export function arcSteps(len: number): number {
  return Math.min(28, Math.max(2, Math.ceil(len / 20)));
}

/** Whether the piece from a to b touches the stage (with a small margin). */
function onStage(ax: number, ay: number, bx: number, by: number, w: number, h: number): boolean {
  return (
    Math.max(ax, bx) >= -MARGIN &&
    Math.min(ax, bx) <= w + MARGIN &&
    Math.max(ay, by) >= -MARGIN &&
    Math.min(ay, by) <= h + MARGIN
  );
}

/** The arc's control point (a scratch pair, so callers do not allocate). */
const control = new Float64Array(2);
function controlPoint(px: number, py: number, qx: number, qy: number, bow: number): number {
  const dx = qx - px;
  const dy = qy - py;
  const len = Math.sqrt(dx * dx + dy * dy);
  const nx = len > 0 ? -dy / len : 0;
  const ny = len > 0 ? dx / len : 0;
  control[0] = (px + qx) / 2 + nx * bow;
  control[1] = (py + qy) / 2 + ny * bow;
  return len;
}

/**
 * Writes the arc from p to q as straight pieces, only those that touch the `w × h` stage.
 * Returns how many pieces it wrote.
 */
export function writeArc(
  writer: SegmentWriter,
  px: number,
  py: number,
  qx: number,
  qy: number,
  h: number,
  stageW: number,
  stageH: number,
  width: number,
  alpha: number,
  appear: number,
  flare: number,
): number {
  const len = controlPoint(px, py, qx, qy, 0);
  if (len < 0.5) return 0;
  controlPoint(px, py, qx, qy, arcBow(len, h));
  const kx = control[0] as number;
  const ky = control[1] as number;
  const steps = arcSteps(len);
  let written = 0;
  let x0 = px;
  let y0 = py;
  for (let s = 1; s <= steps; s++) {
    const u = s / steps;
    const v = 1 - u;
    const x1 = v * v * px + 2 * v * u * kx + u * u * qx;
    const y1 = v * v * py + 2 * v * u * ky + u * u * qy;
    if (onStage(x0, y0, x1, y1, stageW, stageH)) {
      if (!writer.push(x0, y0, x1, y1, width, 1, 1, 1, alpha, 1, appear, flare)) return written;
      written++;
    }
    x0 = x1;
    y0 = y1;
  }
  return written;
}

/** How many of the arc's pieces touch the stage: what `writeArc` writes. */
export function arcPieces(
  px: number,
  py: number,
  qx: number,
  qy: number,
  h: number,
  stageW: number,
  stageH: number,
): number {
  const len = controlPoint(px, py, qx, qy, 0);
  if (len < 0.5) return 0;
  controlPoint(px, py, qx, qy, arcBow(len, h));
  const kx = control[0] as number;
  const ky = control[1] as number;
  const steps = arcSteps(len);
  let pieces = 0;
  let x0 = px;
  let y0 = py;
  for (let s = 1; s <= steps; s++) {
    const u = s / steps;
    const v = 1 - u;
    const x1 = v * v * px + 2 * v * u * kx + u * u * qx;
    const y1 = v * v * py + 2 * v * u * ky + u * u * qy;
    if (onStage(x0, y0, x1, y1, stageW, stageH)) pieces++;
    x0 = x1;
    y0 = y1;
  }
  return pieces;
}

/**
 * Upper bound of the drawn area of the arc's on-stage pieces in CSS px² (each piece's length
 * and width plus 2 px of anti-aliasing fringe), for the flash governor.
 */
export function arcArea(
  px: number,
  py: number,
  qx: number,
  qy: number,
  h: number,
  stageW: number,
  stageH: number,
  width: number,
): number {
  const len = controlPoint(px, py, qx, qy, 0);
  if (len < 0.5) return 0;
  controlPoint(px, py, qx, qy, arcBow(len, h));
  const kx = control[0] as number;
  const ky = control[1] as number;
  const steps = arcSteps(len);
  let area = 0;
  let x0 = px;
  let y0 = py;
  for (let s = 1; s <= steps; s++) {
    const u = s / steps;
    const v = 1 - u;
    const x1 = v * v * px + 2 * v * u * kx + u * u * qx;
    const y1 = v * v * py + 2 * v * u * ky + u * u * qy;
    if (onStage(x0, y0, x1, y1, stageW, stageH)) {
      const dx = x1 - x0;
      const dy = y1 - y0;
      area += (Math.sqrt(dx * dx + dy * dy) + 2) * (width + 2);
    }
    x0 = x1;
    y0 = y1;
  }
  return area;
}
