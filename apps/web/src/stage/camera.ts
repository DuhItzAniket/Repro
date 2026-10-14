/**
 * How much of the wheel the stage shows (B15). By default the stage shows the reference's arc:
 * the ring's centre far left of the stage and its 3 o'clock side across it (the layout's ring).
 * At zoom 1 the whole wheel fits the stage, centred, with room for the lines outside it.
 * Between, the radius shrinks geometrically and the centre moves linearly, so the view zooms out
 * smoothly from the arc to the whole wheel.
 *
 * The view is a different ring geometry for the frame, not a transform on top of it: every layer,
 * the flash governor and the hit tests already derive their positions from `frame.ring`, so they
 * all follow the view, and what is on the stage (where bunches may fire, which arc pieces are
 * written) is decided for the view the viewer sees.
 */
import type { Ring } from "../shell/layout";
import { BAND_SHARE } from "./geometry";
import { RAY_ROOM } from "./web/layers";

/** Margin between the whole wheel, with its lines' room, and the stage's edges, px. */
export const WHOLE_MARGIN = 12;

/** The whole wheel centred on a `width × height` stage, its lines' room inside the stage. */
export function wholeRing(width: number, height: number): Ring {
  const fit = Math.min(width, height) / 2 - WHOLE_MARGIN;
  return { cx: width / 2, cy: height / 2, r: Math.max(1, fit / (1 + BAND_SHARE + RAY_ROOM)) };
}

/**
 * How much the mesh dims in a view: zoomed out, the same arcs cover a smaller disc, so they are
 * denser and would read as a white ball. Their alpha scales with the square root of the radius
 * ratio (0.54 for the whole wheel at 1440×900), never above 1.
 */
export const meshDensity = (base: Ring, view: Ring): number =>
  Math.min(1, Math.sqrt(view.r / base.r));

/** The ring a stage of `width × height` shows at `zoom` (0 the layout's arc `base`, 1 whole). */
export function viewRing(base: Ring, width: number, height: number, zoom: number): Ring {
  const z = Math.min(1, Math.max(0, zoom));
  if (z === 0) return base;
  const whole = wholeRing(width, height);
  if (z === 1) return whole;
  return {
    cx: base.cx + (whole.cx - base.cx) * z,
    cy: base.cy + (whole.cy - base.cy) * z,
    r: base.r * (whole.r / base.r) ** z,
  };
}
