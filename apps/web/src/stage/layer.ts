/**
 * The `Layer` contract (ADR-0008, IMPLEMENTATION_PLAN §5). A layer is pure CPU code: each frame
 * it writes instance data for time `t` into its own preallocated buffers. The host turns those
 * buffers into one instanced draw call. Layers never touch WebGL, so they are tested without a
 * GPU by hashing their render model.
 */
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
}

/** Which GPU primitive draws a layer's buffers. */
export type Primitive = "segments";

export interface StageLayer {
  readonly name: string;
  readonly primitive: Primitive;
  readonly buffers: InstanceBuffers;
  /** How segments brighten after appearing (default: no flare). */
  readonly recency?: Recency;
  /** Writes this frame's instances, or leaves them as they are. Must not allocate. */
  update(frame: StageFrame): void;
}

export function renderModels(layers: readonly StageLayer[]): RenderModel[] {
  return layers.map((layer) => ({ layer: layer.name, buffers: layer.buffers }));
}
