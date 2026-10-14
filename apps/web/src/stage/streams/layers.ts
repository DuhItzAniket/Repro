/**
 * The event-stream layer (B07; DESIGN.md "Event streams"). Each streaming event shoots a streak
 * outward from the ring's rim along its file's lane: one lane per file, so a file's activity
 * forms a band. The head eases out, the tail stretches with the head's speed, and alpha decays
 * over the event's 600–1400 ms life. At most 2,048 streaks are live.
 *
 * A streak is a pure function of its event, `t` and the motion settings: nothing carries over
 * between frames, so the stream at any `t` is exact after a scrub (property-tested). Lifetimes
 * are wall-clock (ADR-0011): at x16 a streak spans 16 times as much run time. The flash governor
 * decides which streaks are drawn, and reduced motion draws none.
 */

import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import type { Ring } from "../../shell/layout";
import { outerRadius } from "../geometry";
import type { FlashGovernor } from "../governor";
import type { StageFrame, StageLayer } from "../layer";
import { targetFile } from "../ring/content";
import { ALWAYS, segmentBuffers, segmentWriter } from "../segments";
import { importance, LONGEST_LIFE, lifetime, streams, TINTS, tintOf, travel } from "./style";

export const MAX_STREAKS = 2048;
/**
 * Lanes fan across ±24° of the ring's right side: the outer rim's visible arc on a stage of the
 * reference's shape (B14).
 */
export const LANE_SPREAD = (24 * Math.PI) / 180;
/** Tail length = head speed × this many ms (velocity-stretched motion blur). */
const TAIL_MS = 160;
const UNIT = 4294967296;

/** Line width of an event's streak, CSS px. */
export const streakWidth = (event: ReproEvent): number => 1 + 0.8 * importance(event);

/**
 * Upper bound of a streak's drawn area in CSS px², for the flash governor: its longest visible
 * stretch (the tail at the head's top speed, plus the 2 px gap) by its width, each with 2 px of
 * anti-aliasing fringe. Durations are wall-clock, so the bound holds at any replay speed.
 */
export function streakArea(event: ReproEvent): number {
  const longest = (2 * travel(event) * TAIL_MS) / lifetime(event) + 2;
  return (longest + 2) * (streakWidth(event) + 2);
}

/** A streak's geometry at `t`: origin radius, head and tail distances along its lane, alpha. */
export interface StreakShape {
  readonly angle: number;
  readonly from: number;
  readonly head: number;
  readonly tail: number;
  readonly alpha: number;
}

/** Lane angle for an event: its file's lane plus a small per-event jitter. */
export function laneAngle(event: ReproEvent): number {
  const file = targetFile(event.target);
  const lane = hash32(file ?? event.kind) / UNIT; // 0–1
  const jitter = (hash32(event.id) / UNIT - 0.5) * 0.17;
  return (lane * 2 - 1) * LANE_SPREAD + jitter;
}

export interface StreakOut {
  angle: number;
  from: number;
  head: number;
  tail: number;
  alpha: number;
}

/**
 * Where a streak on lane `angle` is at age `age` (wall-clock ms since its event); false once it
 * has finished. The head eases out over the life; the tail trails by the head's current speed.
 */
export function streakShape(
  event: ReproEvent,
  age: number,
  angle: number,
  ring: Ring,
  out: StreakOut,
): boolean {
  const life = lifetime(event);
  if (age < 0 || age > life) return false;
  const p = age / life;
  const length = travel(event);
  out.angle = angle;
  out.from = outerRadius(ring) + 4;
  out.head = length * (1 - (1 - p) * (1 - p)); // ease-out
  const speed = (length * 2 * (1 - p)) / life; // d(head)/d(age), px per ms
  out.tail = Math.max(0, out.head - speed * TAIL_MS - 2);
  out.alpha = (0.35 + 0.45 * importance(event)) * (1 - p) ** 1.5;
  return true;
}

export function streakLayer(model: CockpitModel, governor: FlashGovernor): StageLayer {
  const buffers = segmentBuffers(MAX_STREAKS);
  const writer = segmentWriter(buffers, MAX_STREAKS);
  const shape: StreakOut = { angle: 0, from: 0, head: 0, tail: 0, alpha: 0 };
  // Lane angle per store index, computed once per event (NaN = not yet), so frames allocate
  // nothing. Float64, not 32: a rounded cache would draw differently from a fresh computation.
  let lanes = new Float64Array(0);
  return {
    name: "streaks",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      writer.begin();
      governor.prepare(frame);
      if (frame.motion.reduced) return; // reduced motion: no streaks (DESIGN.md "Motion")
      const { speed } = frame.motion;
      const { store } = model;
      if (lanes.length < store.length) {
        const grown = new Float64Array(Math.max(store.length, lanes.length * 2)).fill(Number.NaN);
        grown.set(lanes);
        lanes = grown;
      }
      const start = store.firstAtOrAfter(frame.t - LONGEST_LIFE * speed);
      const end = store.cursorAt(frame.t);
      const { cx, cy } = frame.ring;
      // Newest first, so the cap keeps the freshest streaks.
      for (let i = end - 1; i >= start; i--) {
        const event = store.event(i);
        if (event === null || !streams(event) || !governor.streak(i)) continue;
        let angle = lanes[i] as number;
        if (Number.isNaN(angle)) {
          angle = laneAngle(event);
          lanes[i] = angle;
        }
        const age = (frame.t - (store.time[i] as number)) / speed;
        if (!streakShape(event, age, angle, frame.ring, shape)) {
          continue;
        }
        const dx = Math.cos(shape.angle);
        const dy = Math.sin(shape.angle);
        const tint = TINTS[tintOf(event)];
        const width = streakWidth(event);
        const pushed = writer.push(
          cx + dx * (shape.from + shape.tail),
          cy + dy * (shape.from + shape.tail),
          cx + dx * (shape.from + shape.head),
          cy + dy * (shape.from + shape.head),
          width,
          tint[0],
          tint[1],
          tint[2],
          shape.alpha,
          0, // the tail fades to nothing: a motion-blurred streak
          ALWAYS,
        );
        if (!pushed) break;
      }
    },
  };
}
