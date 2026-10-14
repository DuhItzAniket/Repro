/**
 * Stream rays (B13's residue, restyled in B14). Every streaming event leaves a ray outside the
 * wheel, from the outer rim outward, at **its section of the wheel**: its file's ring card, the
 * section its strands hit from inside (`ring/sections.ts`). Rays turn with the wheel, so a ray
 * stays with its section as it emerges and as it vanishes, like the reference's field, which moves
 * with its wheel. An event whose file has no card draws no ray.
 *
 * A ray draws itself out over RAY_GROW_MS of wall-clock time, behind its streak, then stays and
 * fades over RAY_FADE_MS of run time. Busy files build dense bands and quiet ones sparse rays.
 *
 * Rays are not flashes, so the flash governor does not count them (ADR-0011, B14 note):
 * - they blend with MAX, so a pixel is only ever as bright as its brightest ray (at most 0.92),
 *   however many overlap;
 * - a ray fades over 90 s of run time, but never faster than over 40 s of wall-clock time, so a
 *   pixel's value falls by at most 0.023 a second. A fall of 10% relative luminance needs at
 *   least 0.05 (from 0.92; more from anything dimmer), over 2 s, so no ray's own fade completes a
 *   rise and a fall of 10% within one second.
 *
 * Their turning with the wheel is the wheel's motion, which reduced motion stops (no drift).
 *
 * Rays are written once per ring content, in the ring's own frame, each with its event's time as
 * its appearance time; the shader hides, grows, fades and turns them, so the layer is a pure
 * function of (events, t, motion) and costs nothing per frame.
 */
import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { outerRadius } from "../geometry";
import type { StageFrame, StageLayer } from "../layer";
import { type RingModel, rotationAt } from "../ring/layers";
import { eventFile, sectionAngle } from "../ring/sections";
import { type Recency, segmentBuffers, segmentWriter } from "../segments";
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
 * How far a ray reaches, as a share of the room from the rim to the stage's right edge (at 3
 * o'clock): further for findings and slow tests, with a per-event spread (`h`, 0–1), so the
 * field ends raggedly.
 */
export function rayReach(event: ReproEvent, h: number): number {
  const travelled = Math.min(1, Math.max(0, (travel(event) - 90) / 530));
  return 0.55 + 0.45 * travelled + 0.3 * h;
}

export function residueLayer(model: CockpitModel, ring: RingModel): StageLayer {
  const buffers = segmentBuffers(1024);
  const writer = segmentWriter(buffers);
  let written = 0;
  let drawnRing = -1;
  let geometry = { cx: Number.NaN, cy: Number.NaN, r: Number.NaN };
  let width = Number.NaN;
  const layer = {
    name: "residue",
    primitive: "segments" as const,
    buffers,
    recency: RAY_RECENCY,
    blend: "max" as const, // overlapping rays never add up: a pixel is as bright as its brightest ray
    rotation: 0,
    update(frame: StageFrame) {
      ring.sync();
      layer.rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      const { store } = model;
      const moved =
        frame.ring.cx !== geometry.cx ||
        frame.ring.cy !== geometry.cy ||
        frame.ring.r !== geometry.r ||
        frame.width !== width ||
        ring.version !== drawnRing;
      if (!moved && written === store.length) return;
      // Room for every new event; growing reallocates, which needs a full rewrite.
      const generation = buffers.generation;
      buffers.reserve((moved ? 0 : buffers.count) + store.length - (moved ? 0 : written));
      if (moved || buffers.generation !== generation) {
        geometry = { cx: frame.ring.cx, cy: frame.ring.cy, r: frame.ring.r };
        width = frame.width;
        drawnRing = ring.version;
        written = 0;
        writer.begin();
      } else {
        buffers.version++; // appending new events' rays
      }
      const { cx, cy } = geometry;
      const start = outerRadius(geometry) + 2;
      const room = Math.max(0, width - (cx + start)); // from the rim to the right edge, at 3 o'clock
      for (let i = written; i < store.length; i++) {
        const event = store.event(i);
        if (event === null || !streams(event)) continue;
        const h = hash32(event.id);
        const angle = sectionAngle(ring, eventFile(model, event), h);
        if (Number.isNaN(angle)) continue; // no card: no section to emerge from
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        const length = room * rayReach(event, (Math.imul(h, 0x9e3779b1) >>> 0) / UNIT);
        const tint = TINTS[tintOf(event)];
        writer.push(
          cx + dx * start,
          cy + dy * start,
          cx + dx * (start + length),
          cy + dy * (start + length),
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
  return layer;
}
