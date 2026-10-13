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
