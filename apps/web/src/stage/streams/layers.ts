/**
 * The event-stream layer (B07; DESIGN.md "Event streams"). Each streaming event shoots a streak
 * outward from the ring's rim along its file's lane: one lane per file, so a file's activity
 * forms a band. The head eases out, the tail stretches with the head's speed, and alpha decays
 * over the event's 600–1400 ms life. At most 2,048 streaks are live.
 *
 * A streak is a pure function of its event and `t`: nothing carries over between frames, so the
 * stream at any `t` is exact after a scrub (property-tested).
 */

import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import type { Ring } from "../../shell/layout";
import type { StageFrame, StageLayer } from "../layer";
import { targetFile } from "../ring/content";
import { META_BAND } from "../ring/layers";
import { ALWAYS, segmentBuffers, segmentWriter } from "../segments";
import { importance, LONGEST_LIFE, lifetime, streams, TINTS, tintOf, travel } from "./style";

export const MAX_STREAKS = 2048;
/** Lanes fan across ±64° of the ring's right side, where the stage has room (DESIGN.md layout). */
export const LANE_SPREAD = (64 * Math.PI) / 180;
/** Tail length = head speed × this many ms (velocity-stretched motion blur). */
const TAIL_MS = 110;
const UNIT = 4294967296;

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
  const jitter = (hash32(event.id) / UNIT - 0.5) * 0.06;
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
 * Where a streak on lane `angle` is at age `age` (ms since its event); false once it has
 * finished. The head eases out over the life; the tail trails by the head's current speed.
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
  out.from = ring.r + META_BAND[1] + 14;
  out.head = length * (1 - (1 - p) * (1 - p)); // ease-out
  const speed = (length * 2 * (1 - p)) / life; // d(head)/d(age), px per ms
  out.tail = Math.max(0, out.head - speed * TAIL_MS - 2);
  out.alpha = (0.35 + 0.45 * importance(event)) * (1 - p) ** 1.5;
  return true;
}

export function streakLayer(model: CockpitModel): StageLayer {
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
      const { store } = model;
      if (lanes.length < store.length) {
        const grown = new Float64Array(Math.max(store.length, lanes.length * 2)).fill(Number.NaN);
        grown.set(lanes);
        lanes = grown;
      }
      const start = store.firstAtOrAfter(frame.t - LONGEST_LIFE);
      const end = store.cursorAt(frame.t);
      const { cx, cy } = frame.ring;
      // Newest first, so the cap keeps the freshest streaks.
      for (let i = end - 1; i >= start; i--) {
        const event = store.event(i);
        if (event === null || !streams(event)) continue;
        let angle = lanes[i] as number;
        if (Number.isNaN(angle)) {
          angle = laneAngle(event);
          lanes[i] = angle;
        }
        if (!streakShape(event, frame.t - (store.time[i] as number), angle, frame.ring, shape)) {
          continue;
        }
        const dx = Math.cos(shape.angle);
        const dy = Math.sin(shape.angle);
        const tint = TINTS[tintOf(event)];
        const width = 1 + 0.8 * importance(event);
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
