/**
 * The ring layers (B06): file cards in one instanced draw call, and the tick scale on its rim.
 * Both share a `RingModel`: content, angles and the closed-form rotation for the current log.
 */
import type { FocusTargets } from "../../focus/focus";
import type { CockpitModel } from "../../model/cockpit";
import { type Motion, motionKey } from "../../motion/motion";
import { outerRadius, ringBand, ringTracker } from "../geometry";
import { type AttributeSpec, InstanceBuffers } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { segmentBuffers, segmentWriter } from "../segments";
import { atlasLayout, CARD_UNITS } from "./atlas";
import type { AtlasService } from "./atlas-service";
import { NEVER, type RingContent, ringContent } from "./content";
import { type RingAngles, type RingRotation, ringAngles, ringRotation, SNAP_MS } from "./rotation";

/** Per-instance card attributes (see card.vert.glsl). */
export const CARD_ATTRIBUTES: readonly AttributeSpec[] = [
  { name: "span", size: 4 },
  { name: "uv", size: 4 },
  { name: "times", size: 4 },
];

/**
 * The opaque band under the cards, in this many pieces (each a straight quad), so it hides the
 * web all the way round even where there are no cards (yet).
 */
export const BAND_PIECES = 120;
const KIND_CARD = 0;
const KIND_BAND = 2;

/** The ring's content, geometry and rotation for the log as it is now. */
export class RingModel {
  content: RingContent = { cards: [], focus: [], key: "" };
  angles: RingAngles = ringAngles([]);
  rotation: RingRotation = ringRotation(this.angles, []);
  /** Presentation time at which the first card appears. */
  firstAppear = Number.POSITIVE_INFINITY;
  version = 0;
  private built = -1;
  /** Rotations per motion setting (see `rotationAt`), rebuilt with the content. */
  readonly rotationCache = new Map<number, RingRotation>();
  /** Card index per file. */
  cardOf = new Map<string, number>();

  constructor(
    private readonly model: CockpitModel,
    readonly atlas: AtlasService,
  ) {}

  /** Rebuilds when the log has grown. Cheap to call every frame. */
  sync(): void {
    if (this.model.store.length === this.built) return;
    this.built = this.model.store.length;
    this.content = ringContent(this.model);
    this.angles = ringAngles(this.content.cards);
    this.rotation = ringRotation(this.angles, this.content.focus);
    this.rotationCache.clear();
    this.cardOf = new Map(this.content.cards.map((card, i) => [card.file, i]));
    this.firstAppear = this.content.cards.reduce(
      (t, card) => Math.min(t, card.appear),
      Number.POSITIVE_INFINITY,
    );
    this.version++;
    if (this.content.cards.length > 0) {
      void this.atlas.request(this.content.key, this.content.cards);
    }
  }
}

/** The card the user's focus pins: the first focused file that has a card, or -1. */
export function pinnedCard(ring: RingModel, focus: FocusTargets | undefined): number {
  if (focus === undefined) return -1;
  for (const file of focus.files) {
    const card = ring.cardOf.get(file);
    if (card !== undefined) return card;
  }
  return -1;
}

/**
 * The ring's angle at `t` for this frame's motion (ADR-0011): a snap lasts 500 ms of wall-clock
 * time at any replay speed, and reduced motion snaps instantly and does not drift. Closed-form
 * per setting, so it stays a pure function of (events, t, motion). A user focus (B11) pins its
 * file's card at 3 o'clock instead, without drift, until the focus changes.
 */
export function rotationAt(
  ring: RingModel,
  t: number,
  motion: Motion,
  focus?: FocusTargets,
): number {
  const pinned = pinnedCard(ring, focus);
  if (pinned >= 0)
    return -((ring.angles.start[pinned] as number) + (ring.angles.end[pinned] as number)) / 2;
  const key = motionKey(motion);
  let rotation = ring.rotationCache.get(key);
  if (rotation === undefined) {
    rotation = motion.reduced
      ? ringRotation(ring.angles, ring.content.focus, 0, 0)
      : ringRotation(ring.angles, ring.content.focus, SNAP_MS * motion.speed);
    ring.rotationCache.set(key, rotation);
  }
  return rotation.at(t);
}

export interface CardLayer extends StageLayer {
  readonly primitive: "cards";
  readonly atlas: AtlasService;
  /** Ring rotation for the frame last updated (radians). */
  readonly rotation: number;
}

export function cardLayer(ring: RingModel): CardLayer {
  const buffers = new InstanceBuffers(CARD_ATTRIBUTES, BAND_PIECES + 64);
  let drawn = -1;
  const layer = {
    name: "cards",
    primitive: "cards" as const,
    buffers,
    atlas: ring.atlas,
    rotation: 0,
    update(frame: StageFrame) {
      ring.sync();
      layer.rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      if (ring.version === drawn) return;
      drawn = ring.version;
      const { cards } = ring.content;
      const { start, end } = ring.angles;
      buffers.reserve(BAND_PIECES + cards.length);
      const span = buffers.array("span");
      const uv = buffers.array("uv");
      const times = buffers.array("times");
      let i = 0;
      if (cards.length > 0) {
        // The bare band first, from the first card's appearance; the cards draw over it.
        for (let p = 0; p < BAND_PIECES; p++) {
          const a0 = (p / BAND_PIECES) * Math.PI * 2;
          const a1 = ((p + 1) / BAND_PIECES) * Math.PI * 2;
          span.set([a0, a1, 0, 1], i * 4);
          uv.set([0, 0, 0, 0], i * 4);
          times.set([ring.firstAppear, NEVER, NEVER, KIND_BAND], i * 4);
          i++;
        }
      }
      const atlas = atlasLayout(cards.map((card) => card.units));
      cards.forEach((card, c) => {
        const cell = atlas.cells[c];
        if (cell === undefined) return;
        span.set([start[c] as number, end[c] as number, 0, 1], i * 4);
        uv.set([cell.u0, cell.v0, cell.u1, cell.v1], i * 4);
        times.set([card.appear, card.blastAt, card.changedAt, KIND_CARD], i * 4);
        i++;
      });
      buffers.count = i;
      buffers.version++;
    },
  };
  return layer;
}

export const RIM_SEGMENTS = 256;
const RIM = Array.from({ length: RIM_SEGMENTS + 1 }, (_, i) => {
  const angle = (i / RIM_SEGMENTS) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});
/** Arc length between comb ticks, px; every fifth tick is longer, like a ruler. */
export const COMB_PITCH = 3.4;

/**
 * The band's rims and the ruler combs along both of them (B14, from the reference), turning
 * with the cards. Written once per ring content or size; the shader turns it by `rotation`, so
 * the scale costs no per-frame upload.
 */
export function tickLayer(ring: RingModel): StageLayer {
  const buffers = segmentBuffers(4096);
  const writer = segmentWriter(buffers);
  const ringChanged = ringTracker();
  let drawn = -1;
  const layer = {
    name: "ticks",
    primitive: "segments" as const,
    buffers,
    rotation: 0,
    update(frame: StageFrame) {
      ring.sync();
      layer.rotation = rotationAt(ring, frame.t, frame.motion, frame.focus);
      const moved = ringChanged(frame.ring);
      if (ring.version === drawn && !moved) return;
      drawn = ring.version;
      const { cx, cy, r } = frame.ring;
      const band = ringBand(frame.ring);
      const outer = outerRadius(frame.ring);
      const combs = [r, outer].map((radius) => Math.ceil((Math.PI * 2 * radius) / COMB_PITCH));
      buffers.reserve(RIM_SEGMENTS * 3 + (combs[0] as number) + (combs[1] as number));
      writer.begin();
      if (ring.content.cards.length === 0) return;
      const appear = ring.firstAppear;
      const rim = (radius: number, width: number, alpha: number) => {
        for (let i = 0; i < RIM_SEGMENTS; i++) {
          const [ax, ay] = RIM[i] as readonly [number, number];
          const [bx, by] = RIM[i + 1] as readonly [number, number];
          writer.push(
            cx + ax * radius,
            cy + ay * radius,
            cx + bx * radius,
            cy + by * radius,
            width,
            1,
            1,
            1,
            alpha,
            1,
            appear,
          );
        }
      };
      rim(r, 1.2, 0.55); // the inner rim
      rim(r + (band * 12.5) / CARD_UNITS, 1, 0.16); // the edge of the bezel
      rim(outer, 1.2, 0.6); // the outer rim
      // Ruler combs on the inside of both rims.
      combs.forEach((count, side) => {
        for (let k = 0; k < count; k++) {
          const angle = (k / count) * Math.PI * 2;
          const dx = Math.cos(angle);
          const dy = Math.sin(angle);
          const major = k % 5 === 0;
          const length = major ? 9 : 5;
          const from = side === 0 ? r + 1.5 : outer - 1.5;
          const to = side === 0 ? from + length : from - length;
          writer.push(
            cx + dx * from,
            cy + dy * from,
            cx + dx * to,
            cy + dy * to,
            1,
            1,
            1,
            1,
            major ? 0.62 : 0.4,
            1,
            appear,
          );
        }
      });
    },
  };
  return layer;
}

export function ringLayers(
  model: CockpitModel,
  atlas: AtlasService,
): { ring: RingModel; layers: StageLayer[] } {
  const ring = new RingModel(model, atlas);
  return { ring, layers: [cardLayer(ring), tickLayer(ring)] };
}
