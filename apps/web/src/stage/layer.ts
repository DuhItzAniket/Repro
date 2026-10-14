/**
 * The `Layer` contract (ADR-0008, IMPLEMENTATION_PLAN §5). A layer is pure CPU code: each frame
 * it writes instance data for time `t` into its own preallocated buffers. The host turns those
 * buffers into one instanced draw call. Layers never touch WebGL, so they are tested without a
 * GPU by hashing their render model.
 */
import type { FocusTargets } from "../focus/focus";
import type { Motion } from "../motion/motion";
import type { Ring } from "../shell/layout";
import type { InstanceBuffers, RenderModel } from "./instances";
import type { Look, LookPart } from "./look";
import type { Recency } from "./segments";

export interface StageFrame {
  /** Presentation time, ms since the run started. */
  readonly t: number;
  /** Fold cursor at `t` (events with presentation time ≤ t). */
  readonly cursor: number;
  /** Stage size in CSS pixels. */
  readonly width: number;
  readonly height: number;
  readonly ring: Ring;
  /** Replay speed and reduced motion: wall-clock durations scale with the speed (ADR-0011). */
  readonly motion: Motion;
  /** What the user focused (B11): highlighted on the stage, its file pinned on the ring. */
  readonly focus?: FocusTargets;
  /**
   * The viewer's look (B15): widths and brightness per part. Layers write the same instances
   * whatever it is (the shader applies it); the flash governor reads the widths it counts.
   */
  readonly look?: Look;
}

/** Which GPU primitive draws a layer's buffers. */
export type Primitive = "segments" | "cards";

export interface StageLayer {
  readonly name: string;
  readonly primitive: Primitive;
  readonly buffers: InstanceBuffers;
  /** How segments brighten after appearing (default: no flare). */
  readonly recency?: Recency;
  /**
   * How the layer's segments combine with what is under them: added (the default), or the
   * brighter of the two, so overlaps never add up (B14's stream rays).
   */
  readonly blend?: "add" | "max";
  /** Which part of the viewer's look (B15) scales this layer's widths and alphas, if any. */
  readonly part?: LookPart;
  /**
   * Rotation about the ring's centre (radians) for the frame last updated, for layers that turn
   * with the ring. The shader applies it, so a turning layer need not rewrite its buffers.
   */
  readonly rotation?: number;
  /**
   * Writes this frame's instances, or leaves them as they are. Must not allocate objects (B12's
   * allocation gate measures it).
   */
  update(frame: StageFrame): void;
}

export function renderModels(layers: readonly StageLayer[]): RenderModel[] {
  return layers.map((layer) => ({ layer: layer.name, buffers: layer.buffers }));
}
