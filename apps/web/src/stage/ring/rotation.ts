/**
 * Ring geometry and rotation (DESIGN.md "Ring"). Both are closed-form, pure functions, so the
 * ring at any time `t` is exact after a scrub (B06).
 *
 * - Each card takes its natural angle: its size in band units at the same scale along the arc
 *   (at the band's middle) as across the band, so its text is not stretched (B14). Card i
 *   covers [start_i, end_i) radians, clockwise from 3 o'clock on screen (y down). Cards that do
 *   not fill the circle leave the rest of the band empty; cards that overfill it are scaled
 *   down to fit.
 * - The ring drifts by about one card per 2 s.
 * - A focus event snaps its card's centre to 3 o'clock with a 500 ms ease-out-cubic. A snap that
 *   starts while another is running starts from where that one has got to.
 */
import { BAND_SHARE } from "../geometry";
import { CARD_UNITS } from "./atlas";
import type { FocusEvent } from "./content";

export const SNAP_MS = 500;
export const SECONDS_PER_CARD = 2;
const TAU = Math.PI * 2;
/** Radians per band unit along the arc at the band's middle radius (r · (1 + BAND_SHARE / 2)). */
export const UNIT_ANGLE = BAND_SHARE / (CARD_UNITS * (1 + BAND_SHARE / 2));

export const easeOutCubic = (x: number): number => {
  const clamped = Math.min(1, Math.max(0, x));
  return 1 - (1 - clamped) ** 3;
};

export interface RingAngles {
  /** Start and end angle of each card (radians, before rotation). */
  readonly start: Float64Array;
  readonly end: Float64Array;
  /** Drift speed in radians per ms. */
  readonly drift: number;
}

export function ringAngles(cards: readonly { readonly units: number }[]): RingAngles {
  const n = cards.length;
  const start = new Float64Array(n);
  const end = new Float64Array(n);
  const total = cards.reduce((sum, card) => sum + card.units, 0);
  const perUnit = Math.min(UNIT_ANGLE, total > 0 ? TAU / total : UNIT_ANGLE);
  let at = 0;
  cards.forEach((card, i) => {
    start[i] = at * perUnit;
    at += card.units;
    end[i] = at * perUnit;
  });
  // About one (average) card per SECONDS_PER_CARD.
  const drift = n === 0 ? 0 : (at * perUnit) / n / (SECONDS_PER_CARD * 1000);
  return { start, end, drift };
}

/** Wraps an angle to (−π, π]. */
function wrap(angle: number): number {
  let a = angle % TAU;
  if (a <= -Math.PI) a += TAU;
  if (a > Math.PI) a -= TAU;
  return a;
}

export interface RingRotation {
  /** Rotation (radians) at presentation time `t`; card angles are added to it. */
  at(t: number): number;
}

/**
 * Precomputes every snap once (offsets before and after each), so `at(t)` is a binary search
 * plus one easing: O(log n), no allocation, no history.
 */
export function ringRotation(
  angles: RingAngles,
  focus: readonly FocusEvent[],
  snapMs = SNAP_MS,
  drift = angles.drift,
): RingRotation {
  const n = focus.length;
  const time = new Float64Array(n);
  const from = new Float64Array(n);
  const to = new Float64Array(n);
  let offset = 0;
  for (let k = 0; k < n; k++) {
    const event = focus[k] as FocusEvent;
    // Offset at the moment this snap starts (mid-snap if the previous one is still running).
    if (k > 0) {
      const progress = snapMs === 0 ? 1 : (event.time - (time[k - 1] as number)) / snapMs;
      offset =
        (from[k - 1] as number) +
        ((to[k - 1] as number) - (from[k - 1] as number)) * easeOutCubic(progress);
    }
    const centre = ((angles.start[event.card] as number) + (angles.end[event.card] as number)) / 2;
    // At the end of the snap the card's centre must sit at angle 0 (3 o'clock).
    const target = -(centre + drift * (event.time + snapMs));
    time[k] = event.time;
    from[k] = offset;
    to[k] = offset + wrap(target - offset);
  }
  return {
    at(t: number): number {
      let lo = 0;
      let hi = n;
      while (lo < hi) {
        const mid = (lo + hi) >>> 1;
        if ((time[mid] as number) <= t) lo = mid + 1;
        else hi = mid;
      }
      const k = lo - 1;
      let current = 0;
      if (k >= 0) {
        const progress = snapMs === 0 ? 1 : (t - (time[k] as number)) / snapMs;
        current =
          (from[k] as number) + ((to[k] as number) - (from[k] as number)) * easeOutCubic(progress);
      }
      return drift * t + current;
    },
  };
}
