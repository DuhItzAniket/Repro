/**
 * The ring layers (B06): file cards in one instanced draw call, and the tick scale on its rim.
 * Both share a `RingModel`: content, angles and the closed-form rotation for the current log.
 */
import type { CockpitModel } from "../../model/cockpit";
import { type Motion, motionKey } from "../../motion/motion";
import { ringTracker } from "../geometry";
import { type AttributeSpec, InstanceBuffers } from "../instances";
import type { StageFrame, StageLayer } from "../layer";
import { segmentBuffers, segmentWriter } from "../segments";
import { atlasLayout } from "./atlas";
import type { AtlasService } from "./atlas-service";
import { type RingContent, ringContent } from "./content";
import { type RingAngles, type RingRotation, ringAngles, ringRotation, SNAP_MS } from "./rotation";

/** Per-instance card attributes (see card.vert.glsl). */
export const CARD_ATTRIBUTES: readonly AttributeSpec[] = [
  { name: "span", size: 4 },
  { name: "uv", size: 4 },
  { name: "times", size: 4 },
];

/** Radial extent of the band's two columns, as offsets from the ring radius (DESIGN: ≈ 90 px). */
export const CONTENT_BAND = [-44, 8] as const;
export const META_BAND = [10, 44] as const;
/** Gap between neighbouring cards, as a share of a card's angle. */
const CARD_GAP = 0.08;

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

/**
 * The ring's angle at `t` for this frame's motion (ADR-0011): a snap lasts 500 ms of wall-clock
 * time at any replay speed, and reduced motion snaps instantly and does not drift. Closed-form
 * per setting, so it stays a pure function of (events, t, motion).
 */
export function rotationAt(ring: RingModel, t: number, motion: Motion): number {
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
  const buffers = new InstanceBuffers(CARD_ATTRIBUTES, 64);
  let drawn = -1;
  const layer = {
    name: "cards",
    primitive: "cards" as const,
    buffers,
    atlas: ring.atlas,
    rotation: 0,
    update(frame: StageFrame) {
      ring.sync();
      layer.rotation = rotationAt(ring, frame.t, frame.motion);
      if (ring.version === drawn) return;
      drawn = ring.version;
      const { cards } = ring.content;
      const { start, end } = ring.angles;
      const atlas = atlasLayout(cards.length);
      buffers.reserve(cards.length * 2);
      const span = buffers.array("span");
      const uv = buffers.array("uv");
      const times = buffers.array("times");
      let i = 0;
      cards.forEach((card, c) => {
        const a0 = start[c] as number;
        const a1 = end[c] as number;
        const gap = (a1 - a0) * CARD_GAP;
        for (const kind of [0, 1]) {
          const [r0, r1] = kind === 0 ? CONTENT_BAND : META_BAND;
          const cell = kind === 0 ? atlas.content[c] : atlas.meta[c];
          if (cell === undefined) continue;
          span.set([a0 + gap / 2, a1 - gap / 2, r0, r1], i * 4);
          uv.set([cell.u0, cell.v0, cell.u1, cell.v1], i * 4);
          times.set([card.appear, card.blastAt, card.changedAt, kind], i * 4);
          i++;
        }
      });
      buffers.count = i;
      buffers.version++;
    },
  };
  return layer;
}

const MINOR_TICKS = 4;
const RIM_SEGMENTS = 192;
const RIM = Array.from({ length: RIM_SEGMENTS + 1 }, (_, i) => {
  const angle = (i / RIM_SEGMENTS) * Math.PI * 2;
  return [Math.cos(angle), Math.sin(angle)] as const;
});

/**
 * The band's rims and a tick scale that turns with the cards. Written once per ring content or
 * size; the shader turns it by `rotation`, so the scale costs no per-frame upload.
 */
export function tickLayer(ring: RingModel, cardCapacity = 160): StageLayer {
  const buffers = segmentBuffers(cardCapacity * (MINOR_TICKS + 1) + RIM_SEGMENTS * 2);
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
      layer.rotation = rotationAt(ring, frame.t, frame.motion);
      const moved = ringChanged(frame.ring);
      if (ring.version === drawn && !moved) return;
      drawn = ring.version;
      writer.begin();
      const { cx, cy, r } = frame.ring;
      if (ring.content.cards.length === 0) return;
      const appear = ring.firstAppear;
      // Thin rims on both sides of the band.
      for (let side = 0; side < 2; side++) {
        const radius = side === 0 ? r + CONTENT_BAND[0] - 2 : r + META_BAND[1] + 2;
        for (let i = 0; i < RIM_SEGMENTS; i++) {
          const [ax, ay] = RIM[i] as readonly [number, number];
          const [bx, by] = RIM[i + 1] as readonly [number, number];
          writer.push(
            cx + ax * radius,
            cy + ay * radius,
            cx + bx * radius,
            cy + by * radius,
            1,
            1,
            1,
            1,
            0.22,
            1,
            appear,
          );
        }
      }
      // A major tick at each card boundary and minor ticks between, outside the band.
      const { start, end } = ring.angles;
      const outer = r + META_BAND[1] + 4;
      for (let c = 0; c < start.length; c++) {
        const a0 = start[c] as number;
        const a1 = end[c] as number;
        for (let m = 0; m <= MINOR_TICKS; m++) {
          const angle = a0 + ((a1 - a0) * m) / (MINOR_TICKS + 1);
          const dx = Math.cos(angle);
          const dy = Math.sin(angle);
          const length = m === 0 ? 7 : 3;
          writer.push(
            cx + dx * outer,
            cy + dy * outer,
            cx + dx * (outer + length),
            cy + dy * (outer + length),
            1,
            1,
            1,
            1,
            m === 0 ? 0.45 : 0.22,
            1,
            appear,
          );
        }
      }
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
