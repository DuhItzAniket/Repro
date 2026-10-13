/**
 * Benchmark proxy layers (B04). They put the GPU and CPU load of the planned stage layers
 * (B05–B07) on screen before those layers exist: every graph edge as a line, up to 2,048 live
 * streaks from the event window, a ring of card quads and a scale of ticks. Positions are
 * deliberately cruder than the real layers. Random chords inside the ring are longer than
 * force-directed edges, so the proxy costs **more** fill rate than the real edge layer will.
 */
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../model/cockpit";
import { statusCode } from "../model/codes";
import type { StageFrame, StageLayer } from "../stage/layer";
import { ringTracker } from "../stage/ring";
import { segmentBuffers, segmentWriter } from "../stage/segments";

const UNIT = 4294967296;
const FAIL = statusCode("fail");

/** A deterministic point in the unit disc from an id, by rejection sampling on its hash (no trig). */
function discPoint(id: string, out: { x: number; y: number }): void {
  let h = hash32(id);
  for (let i = 0; i < 16; i++) {
    const x = (h / UNIT) * 2 - 1;
    h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d) >>> 0;
    const y = (h / UNIT) * 2 - 1;
    h = Math.imul(h ^ (h >>> 13), 0x297a2d39) >>> 0;
    if (x * x + y * y <= 1) {
      out.x = x;
      out.y = y;
      return;
    }
  }
  out.x = 0;
  out.y = 0;
}

export function edgeProxy(model: CockpitModel, capacity = 10_240): StageLayer {
  const buffers = segmentBuffers(capacity);
  const writer = segmentWriter(buffers);
  const p = { x: 0, y: 0 };
  const q = { x: 0, y: 0 };
  let drawnCount = -1;
  const ringChanged = ringTracker();
  return {
    name: "edges",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      const count = model.kinds.count("graph.edge", frame.cursor);
      const moved = ringChanged(frame.ring);
      if (count === drawnCount && !moved) return; // static between graph events
      drawnCount = count;
      const { cx, cy, r } = frame.ring;
      const radius = r - 55;
      writer.begin();
      for (const index of model.kinds.last("graph.edge", frame.cursor, capacity)) {
        const event = model.store.event(index);
        if (event?.kind !== "graph.edge") continue;
        discPoint(event.payload.source, p);
        discPoint(event.payload.target, q);
        writer.push(
          cx + p.x * radius,
          cy + p.y * radius,
          cx + q.x * radius,
          cy + q.y * radius,
          1,
          1,
          1,
          1,
          0.1,
          1,
        );
      }
    },
  };
}

const STREAK_LIFE_MS = 1400;

export function streakProxy(model: CockpitModel, limit = 2048): StageLayer {
  const buffers = segmentBuffers(limit);
  const writer = segmentWriter(buffers, limit);
  return {
    name: "streaks",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      const start = model.store.firstAtOrAfter(frame.t - STREAK_LIFE_MS);
      const end = model.store.cursorAt(frame.t);
      const { cx, cy, r } = frame.ring;
      const origin = r + 50;
      writer.begin();
      for (let i = end - 1; i >= start; i--) {
        const time = model.store.time[i] as number;
        const h = hash32(model.store.envelope(i).id);
        const life = 600 + (h % 800);
        const age = frame.t - time;
        if (age > life) continue;
        const progress = age / life;
        const slope = ((h >>> 10) / 4194304) * 2.4 - 1.2; // −1.2…1.2, about ±50°
        const norm = Math.sqrt(1 + slope * slope);
        const dx = 1 / norm;
        const dy = slope / norm;
        const length = 120 + ((h >>> 3) % 300);
        const head = origin + length * progress;
        const tail = Math.max(origin, head - 90);
        const fail = model.store.status[i] === FAIL;
        const red = fail ? 0.43 : 0.85;
        const green = fail ? 0.31 : 0.85;
        const blue = fail ? 0.35 : 0.88;
        if (
          !writer.push(
            cx + dx * tail,
            cy + dy * tail,
            cx + dx * head,
            cy + dy * head,
            1.5,
            red,
            green,
            blue,
            0.6 * (1 - progress),
            0,
          )
        )
          break;
      }
    },
  };
}

export function cardProxy(cards = 360): StageLayer {
  const buffers = segmentBuffers(cards);
  const writer = segmentWriter(buffers);
  return {
    name: "cards",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      const { cx, cy, r } = frame.ring;
      // One card per ~2 s of rotation (DESIGN.md "Ring").
      const turn = frame.t / 2000 / cards;
      writer.begin();
      for (let i = 0; i < cards; i++) {
        const angle = ((i / cards + turn) % 1) * Math.PI * 2;
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        writer.push(
          cx + dx * (r - 45),
          cy + dy * (r - 45),
          cx + dx * (r + 45),
          cy + dy * (r + 45),
          9,
          0.7,
          0.7,
          0.7,
          0.16,
          1,
        );
      }
    },
  };
}

export function tickProxy(ticks = 720): StageLayer {
  const buffers = segmentBuffers(ticks);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  return {
    name: "ticks",
    primitive: "segments",
    buffers,
    update(frame: StageFrame) {
      if (!ringChanged(frame.ring)) return;
      const { cx, cy, r } = frame.ring;
      writer.begin();
      for (let i = 0; i < ticks; i++) {
        const angle = (i / ticks) * Math.PI * 2;
        const long = i % 10 === 0 ? 10 : 5;
        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        writer.push(
          cx + dx * (r + 48),
          cy + dy * (r + 48),
          cx + dx * (r + 48 + long),
          cy + dy * (r + 48 + long),
          1,
          1,
          1,
          1,
          0.3,
          1,
        );
      }
    },
  };
}

export function proxyLayers(model: CockpitModel): StageLayer[] {
  return [edgeProxy(model), cardProxy(), tickProxy(), streakProxy(model)];
}
