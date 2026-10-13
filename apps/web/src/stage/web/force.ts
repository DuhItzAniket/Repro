/**
 * Force-directed layout of the dependency web (DESIGN.md "Dependency web"; ARCHITECTURE §13).
 *
 * Deterministic by construction:
 * - initial positions come from node-id hashes by rejection sampling (no trigonometry);
 * - d3-force 3 jiggles with its own fixed-seed generator, not `Math.random`;
 * - a fixed number of ticks runs in a fixed order.
 *
 * The same graph therefore always gets the same layout, and the result can be cached by graph
 * hash. Symbols and tests carry no edge to their own module, so the layout adds short
 * **containment** links (never drawn) to keep each file's symbols near its module.
 */
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { fnv, type LayoutInput } from "./layout-input";

export const LAYOUT_TICKS = 300;
/** How far node radii move towards a uniform disc (0 = raw force layout, 1 = fully uniform). */
export const EQUALISE = 0.85;

/** A deterministic point in the disc of radius `r` from an id (rejection sampling on its hash). */
function seedPoint(id: string, r: number, node: SimulationNodeDatum): void {
  let h = fnv(0x811c9dc5, id);
  for (let i = 0; i < 24; i++) {
    const x = (h / 4294967296) * 2 - 1;
    h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d) >>> 0;
    const y = (h / 4294967296) * 2 - 1;
    h = Math.imul(h ^ (h >>> 13), 0x297a2d39) >>> 0;
    if (x * x + y * y <= 1) {
      node.x = x * r;
      node.y = y * r;
      return;
    }
  }
  node.x = 0;
  node.y = 0;
}

/**
 * Runs the simulation and returns positions in the unit disc (radius 0.97), centred on the
 * centroid, with radii equalised towards a uniform disc (`EQUALISE`).
 */
export function forceLayout(input: LayoutInput, ticks = LAYOUT_TICKS): Float32Array {
  const n = input.ids.length;
  const out = new Float32Array(n * 2);
  if (n === 0) return out;
  const spread = 12 * Math.sqrt(n);
  const nodes: SimulationNodeDatum[] = input.ids.map((id) => {
    const node: SimulationNodeDatum = {};
    seedPoint(id, spread, node);
    return node;
  });
  const drawn = input.links.length / 2 - input.containment;
  const links: (SimulationLinkDatum<SimulationNodeDatum> & { contain: boolean })[] = [];
  for (let i = 0; i < input.links.length / 2; i++) {
    const source = input.links[i * 2] as number;
    const target = input.links[i * 2 + 1] as number;
    if (source !== target) links.push({ source, target, contain: i >= drawn });
  }
  const simulation = forceSimulation(nodes)
    .force(
      "link",
      forceLink(links)
        .distance((link) => ((link as { contain: boolean }).contain ? 10 : 34))
        .strength((link) => ((link as { contain: boolean }).contain ? 0.9 : 0.25)),
    )
    .force("charge", forceManyBody().strength(-26).theta(0.9).distanceMax(320))
    .force("center", forceCenter(0, 0))
    .stop();
  simulation.tick(ticks);

  // Normalise around the centroid, then equalise radii: a hub-heavy import graph collapses into
  // a dense core, but the stage should read as an even hairball (DESIGN.md). Each node keeps its
  // angle and its radial rank; its radius moves most of the way to the rank's position in a
  // uniform disc, sqrt((rank + 0.5) / n).
  let cx = 0;
  let cy = 0;
  for (const node of nodes) {
    cx += node.x ?? 0;
    cy += node.y ?? 0;
  }
  cx /= n;
  cy /= n;
  // sqrt is correctly rounded on every engine (Math.hypot is only "implementation-approximated").
  const distance = (x: number, y: number) => Math.sqrt(x * x + y * y);
  const radii = nodes.map((node) => distance((node.x ?? 0) - cx, (node.y ?? 0) - cy));
  const order = radii
    .map((_, i) => i)
    .sort((p, q) => (radii[p] as number) - (radii[q] as number) || p - q);
  const rank = new Int32Array(n);
  order.forEach((node, i) => {
    rank[node] = i;
  });
  const maxRadius = radii[order[n - 1] as number] || 1;
  nodes.forEach((node, i) => {
    const r = radii[i] as number;
    const uniform = Math.sqrt(((rank[i] as number) + 0.5) / n);
    const target = (1 - EQUALISE) * (r / maxRadius) + EQUALISE * uniform;
    const dx = (node.x ?? 0) - cx;
    const dy = (node.y ?? 0) - cy;
    const scale = r > 0 ? (target * 0.97) / r : 0;
    out[i * 2] = dx * scale;
    out[i * 2 + 1] = dy * scale;
  });
  return out;
}
