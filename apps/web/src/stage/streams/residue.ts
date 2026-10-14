/**
 * Stream rays (B13's residue, restyled in B14). Every streaming event leaves a static ray along
 * its file's lane, from the ring's outer rim outward. It draws itself out over RAY_GROW_MS of
 * wall-clock time, behind its streak, then stays and fades over RAY_FADE_MS of run time. Busy
 * files build dense bands and quiet ones sparse rays, like the reference's long-exposure field,
 * and the right of the stage shows where the run has been busy.
 *
 * Each ray maps to one event and does not move once drawn. Rays are not flashes, so the flash
 * governor does not count them (ADR-0011, B14 note):
 * - they blend with MAX, so a pixel is only ever as bright as its brightest ray (at most 0.92),
 *   however many overlap;
 * - a ray fades over 90 s of run time, but never faster than over 40 s of wall-clock time, so a
 *   pixel's value falls by at most 0.023 a second. A fall of 10% relative luminance needs at
 *   least 0.05 (from 0.92; more from anything dimmer), over 2 s, so no pixel completes a rise
 *   and a fall of 10% within one second.
 *
 * Under reduced motion rays appear whole, since nothing moves.
 *
 * Like the edge layer, rays are written once, when their event arrives, with the event's time
 * as their appearance time. The shader hides, grows and fades them, so the layer is a pure
 * function of (events, t, motion) and costs nothing per frame.
 */

import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { outerRadius } from "../geometry";
import type { StageFrame, StageLayer } from "../layer";
import { type Recency, segmentBuffers, segmentWriter } from "../segments";
import { laneAngle } from "./layers";
import { importance, streams, TINTS, tintOf, travel } from "./style";

/** Run time over which a ray fades to nothing (it does not move, so this is not wall-clock). */
export const RAY_FADE_MS = 90_000;
/** Wall-clock time a ray takes to draw itself out from the rim. */
export const RAY_GROW_MS = 900;
/** However fast the replay, a ray takes at least this long (wall-clock) to fade. */
export const RAY_FADE_WALL_MS = 40_000;
export const RAY_RECENCY: Recency = {
  flare: 0,
  flareMs: 1,
  fadeMs: RAY_FADE_MS,
  fadeWallMs: RAY_FADE_WALL_MS,
  growMs: RAY_GROW_MS,
};
const UNIT = 4294967296;

/**
 * A ray's alpha at the rim: brighter for findings. It falls to RAY_END of that at its outer end,
 * so the field is brightest near the ring, like the reference's.
 */
export const rayAlpha = (event: ReproEvent): number => 0.42 + 0.5 * importance(event);
export const RAY_END = 0.45;
const RAY_WIDTH = 1.6;

/**
 * How far a ray reaches, as a share of the way from the rim to the stage's edge: further for
 * findings and slow tests, with a per-event spread (`h`, 0–1), so the field ends raggedly.
 */
export function rayReach(event: ReproEvent, h: number): number {
  const travelled = Math.min(1, Math.max(0, (travel(event) - 90) / 530));
  return 0.55 + 0.45 * travelled + 0.3 * h;
}

/** Distance from (x, y) along (dx, dy) to the edge of a `w × h` stage; 0 when outside it. */
export function toEdge(x: number, y: number, dx: number, dy: number, w: number, h: number): number {
  if (x < 0 || y < 0 || x > w || y > h) return 0;
  const along = dx > 1e-9 ? (w - x) / dx : dx < -1e-9 ? -x / dx : Number.POSITIVE_INFINITY;
  const across = dy > 1e-9 ? (h - y) / dy : dy < -1e-9 ? -y / dy : Number.POSITIVE_INFINITY;
  return Math.min(along, across);
}

export function residueLayer(model: CockpitModel): StageLayer {
  const buffers = segmentBuffers(1024);
  const writer = segmentWriter(buffers);
  let written = 0;
  let ring = { cx: Number.NaN, cy: Number.NaN, r: Number.NaN };
  let width = Number.NaN;
  let height = Number.NaN;
  return {
    name: "residue",
    primitive: "segments",
    buffers,
    recency: RAY_RECENCY,
    blend: "max", // overlapping rays never add up: a pixel is as bright as its brightest ray
    update(frame: StageFrame) {
      const { store } = model;
      const moved =
        frame.ring.cx !== ring.cx ||
        frame.ring.cy !== ring.cy ||
        frame.ring.r !== ring.r ||
        frame.width !== width ||
        frame.height !== height;
      if (!moved && written === store.length) return;
      // Room for every new event; growing reallocates, which needs a full rewrite.
      const generation = buffers.generation;
      buffers.reserve((moved ? 0 : buffers.count) + store.length - (moved ? 0 : written));
      if (moved || buffers.generation !== generation) {
        ring = { cx: frame.ring.cx, cy: frame.ring.cy, r: frame.ring.r };
        width = frame.width;
        height = frame.height;
        written = 0;
        writer.begin();
      } else {
        buffers.version++; // appending new events' rays
      }
      const { cx, cy } = ring;
      const start = outerRadius(ring) + 2;
      for (let i = written; i < store.length; i++) {
        const event = store.event(i);
        if (event === null || !streams(event)) continue;
        const angle = laneAngle(event);
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        const x = cx + dx * start;
        const y = cy + dy * start;
        const room = toEdge(x, y, dx, dy, width, height);
        if (room <= 0) continue; // its lane starts off the stage
        const length = room * rayReach(event, hash32(event.id) / UNIT);
        const tint = TINTS[tintOf(event)];
        writer.push(
          x,
          y,
          x + dx * length,
          y + dy * length,
          RAY_WIDTH,
          tint[0],
          tint[1],
          tint[2],
          rayAlpha(event) * RAY_END,
          1 / RAY_END, // the start (at the rim) relative to the end
          store.time[i] as number,
          0,
        );
      }
      written = store.length;
    },
  };
}
