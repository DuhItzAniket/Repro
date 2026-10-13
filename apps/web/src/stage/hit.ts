/**
 * What is under a point on the stage (B11): a ring card (its file) or a node of the dependency
 * web (its symbol, or its file for modules and tests). Only what has appeared by `t` can be hit.
 * Uses the same geometry as the layers: the ring's closed-form rotation, the card bands, and the
 * web layout scaled into the ring.
 */
import type { Focus, FocusTargets } from "../focus/focus";
import type { CockpitModel } from "../model/cockpit";
import type { Motion } from "../motion/motion";
import type { Ring } from "../shell/layout";
import { WEB_INSET } from "./geometry";
import type { PlacedNodes } from "./governor";
import { CONTENT_BAND, META_BAND, type RingModel, rotationAt } from "./ring/layers";

/** How close (CSS px) a click must be to a node's centre. */
export const NODE_HIT_PX = 8;
const TAU = Math.PI * 2;

export interface StageHitInput {
  readonly t: number;
  readonly ring: Ring;
  readonly motion: Motion;
  readonly focus?: FocusTargets;
}

export function hitStage(
  x: number,
  y: number,
  frame: StageHitInput,
  model: CockpitModel,
  ringModel: RingModel,
  layout: PlacedNodes,
): Focus | null {
  const { cx, cy, r } = frame.ring;
  const dx = x - cx;
  const dy = y - cy;
  const distance = Math.sqrt(dx * dx + dy * dy);

  // The ring band: find the card whose angular span holds the point.
  if (distance >= r + CONTENT_BAND[0] && distance <= r + META_BAND[1]) {
    ringModel.sync();
    const rotation = rotationAt(ringModel, frame.t, frame.motion, frame.focus);
    const angle = (((Math.atan2(dy, dx) - rotation) % TAU) + TAU) % TAU;
    const { start, end } = ringModel.angles;
    for (let c = 0; c < start.length; c++) {
      if (angle < (start[c] as number) || angle >= (end[c] as number)) continue;
      const card = ringModel.content.cards[c];
      return card !== undefined && frame.t >= card.appear
        ? { kind: "file", file: card.file }
        : null;
    }
    return null;
  }

  // The web: the nearest placed, appeared node within reach.
  const positions = layout.positions;
  const radius = r - WEB_INSET;
  if (positions === null || distance > radius + NODE_HIT_PX) return null;
  const { graph, store } = model;
  let best = -1;
  let bestDistance = NODE_HIT_PX * NODE_HIT_PX;
  for (let n = 0; n < graph.nodeCount && n * 2 + 1 < positions.length; n++) {
    if ((store.time[graph.nodeEvent[n] as number] as number) > frame.t) continue;
    const nx = cx + (positions[n * 2] as number) * radius - x;
    const ny = cy + (positions[n * 2 + 1] as number) * radius - y;
    const d = nx * nx + ny * ny;
    if (d <= bestDistance) {
      best = n;
      bestDistance = d;
    }
  }
  if (best < 0) return null;
  const file = graph.files[best] as string;
  const type = graph.nodeTypeName(best);
  return type === "module" || type === "test"
    ? { kind: "file", file }
    : { kind: "symbol", symbol: graph.ids[best] as string, file };
}
