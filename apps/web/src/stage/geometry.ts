import type { Ring } from "../shell/layout";

/**
 * Remembers a ring by value without allocating. Returns true when the ring differs from the
 * last call, so static layers redraw only after a resize.
 */
export function ringTracker(): (ring: Ring) => boolean {
  let cx = Number.NaN;
  let cy = Number.NaN;
  let r = Number.NaN;
  return (ring) => {
    if (ring.cx === cx && ring.cy === cy && ring.r === r) return false;
    cx = ring.cx;
    cy = ring.cy;
    r = ring.r;
    return true;
  };
}

/**
 * The ring band's thickness as a share of its inner radius. Measured on the 1080×1350 reference
 * (B14): inner rim radius ≈ 957 px, band ≈ 205 px.
 */
export const BAND_SHARE = 0.215;

/** The band's thickness in px. */
export const ringBand = (ring: Ring): number => ring.r * BAND_SHARE;

/** Radius of the band's outer rim, where the streams start. */
export const outerRadius = (ring: Ring): number => ring.r * (1 + BAND_SHARE);

/**
 * Radius of the dependency web's circle of modules: under the band, so the edges' ends are hidden
 * and the stage shows long arcs passing under the ring, like the reference. Symbols and tests sit
 * inside it (`placeNode`). In the default view the ring's centre lies left of the stage, so most of
 * the web is off-screen and the stage shows the arcs crossing its right part.
 */
export const WEB_SCALE = 1.1;
export const webRadius = (ring: Ring): number => ring.r * WEB_SCALE;
