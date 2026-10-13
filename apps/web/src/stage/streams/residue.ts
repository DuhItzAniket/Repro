/**
 * Stream residue (B13). Every streaming event leaves a faint, static trace along its file's lane
 * that fades over RESIDUE_FADE_MS of run time. Busy files build up dense horizontal bands, like
 * the long-exposure streams of the reference, and the right of the stage shows where the run has
 * been busy rather than staying empty between bursts.
 *
 * Each trace maps to one event and does not move. It adds at most RESIDUE_ALPHA of luminance,
 * under WCAG 2.3.1's 10% flash threshold, so it is not a flash and the flash governor does not
 * count it. It stays under reduced motion, since nothing moves.
 *
 * Like the edge layer, traces are written once, when their event arrives, with the event's time
 * as their appearance time. The shader hides them before it and fades them after it, so the
 * layer is a pure function of (events, t) and costs nothing per frame.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import type { StageFrame, StageLayer } from "../layer";
import { META_BAND } from "../ring/layers";
import { type Recency, segmentBuffers, segmentWriter } from "../segments";
import { laneAngle } from "./layers";
import { importance, streams, TINTS, tintOf, travel } from "./style";

/** Run time over which a trace fades to nothing (it does not move, so this is not wall-clock). */
export const RESIDUE_FADE_MS = 90_000;
/** Brightest a single trace gets: under the 10% luminance change that makes a flash. */
export const RESIDUE_ALPHA = 0.09;
export const RESIDUE_RECENCY: Recency = { flare: 0, flareMs: 1, fadeMs: RESIDUE_FADE_MS };
const UNIT = 4294967296;

export function residueLayer(model: CockpitModel): StageLayer {
  const buffers = segmentBuffers(1024);
  const writer = segmentWriter(buffers);
  let written = 0;
  let ring = { cx: Number.NaN, cy: Number.NaN, r: Number.NaN };
  return {
    name: "residue",
    primitive: "segments",
    buffers,
    recency: RESIDUE_RECENCY,
    update(frame: StageFrame) {
      const { store } = model;
      const moved =
        frame.ring.cx !== ring.cx || frame.ring.cy !== ring.cy || frame.ring.r !== ring.r;
      if (!moved && written === store.length) return;
      // Room for every new event; growing reallocates, which needs a full rewrite.
      const generation = buffers.generation;
      buffers.reserve((moved ? 0 : buffers.count) + store.length - (moved ? 0 : written));
      if (moved || buffers.generation !== generation) {
        ring = { cx: frame.ring.cx, cy: frame.ring.cy, r: frame.ring.r };
        written = 0;
        writer.begin();
      } else {
        buffers.version++; // appending new events' traces
      }
      const { cx, cy, r } = ring;
      for (let i = written; i < store.length; i++) {
        const event = store.event(i);
        if (event === null || !streams(event)) continue;
        // Each trace covers a stretch of its lane, placed by the event's hash.
        const angle = laneAngle(event);
        const h = hash32(event.id) / UNIT;
        const length = travel(event) * (0.6 + 0.8 * h);
        const start = r + META_BAND[1] + 14 + 40 * h;
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        const tint = TINTS[tintOf(event)];
        writer.push(
          cx + dx * start,
          cy + dy * start,
          cx + dx * (start + length),
          cy + dy * (start + length),
          1,
          tint[0],
          tint[1],
          tint[2],
          RESIDUE_ALPHA * (0.5 + importance(event) / 2),
          0.15, // brighter at the outer end, like a motion-blurred trail
          store.time[i] as number,
          0,
        );
      }
      written = store.length;
    },
  };
}
