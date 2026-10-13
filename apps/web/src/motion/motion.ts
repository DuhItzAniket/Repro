/**
 * Motion settings for a frame (ADR-0011, DESIGN.md "Motion"). Visual durations are wall-clock
 * times, so in presentation (run) time they scale with the replay speed. Every animated element
 * stays a pure function of (events, t, motion).
 *
 * - `speed`: run-time ms per wall-clock ms (the replay speed; 1 when following live).
 * - `reduced`: `prefers-reduced-motion` or the in-app toggle. No streaks or bundles, no flares,
 *   no drift, and every state change is instant.
 */

export interface Motion {
  readonly speed: number;
  readonly reduced: boolean;
}

export const NORMAL_MOTION: Motion = { speed: 1, reduced: false };

/** A wall-clock duration as presentation (run) time at this frame's speed. */
export const runMs = (wallMs: number, motion: Motion): number => wallMs * motion.speed;

/** A small integer that changes whenever the motion settings do (for redraw keys). */
export const motionKey = (motion: Motion): number =>
  Math.round(motion.speed * 1000) * 2 + (motion.reduced ? 1 : 0);

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
