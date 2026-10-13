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

/** Radius of the dependency web: inside the ring's band (DESIGN.md "Ring": a ≈ 90 px band). */
export const WEB_INSET = 55;
