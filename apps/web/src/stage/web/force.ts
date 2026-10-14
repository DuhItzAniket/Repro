/**
 * Layout of the dependency web (DESIGN.md "Dependency web"; ARCHITECTURE §13). A force-directed
 * simulation orders the nodes, and the result is a **chord layout** (B14): modules sit on a
 * circle just inside the ring, in the angular order the simulation gave them, evenly spaced, and
 * symbols and tests sit a little inside, beside their module. Tightly connected modules end up
 * next to each other, so their edges are short arcs near the rim, and edges between distant
 * parts of the repo cross the disc as long curves: the reference's hairball, from real edges.
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
/** Radius of symbols and tests, inside the modules' circle (unit radius), ± a per-node jitter. */
export const INNER_RADIUS = 0.9;
const INNER_JITTER = 0.04;

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
 * Runs the simulation and returns positions on the unit circle (modules) and just inside it
 * (symbols and tests), each at the angle of its rank around the simulation's centroid.
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

  // Order the nodes by their angle around the centroid, then space them evenly on the circle.
  // The order is all that is kept of the simulation: a hub-heavy import graph collapses into a
  // dense core, and spacing by rank keeps every part of the rim equally busy.
  let cx = 0;
  let cy = 0;
  for (const node of nodes) {
    cx += node.x ?? 0;
    cy += node.y ?? 0;
  }
  cx /= n;
  cy /= n;
  // A pseudo-angle (monotonic in the true angle, no trigonometry), so ties and order do not
  // depend on how an engine rounds atan2.
  const pseudo = nodes.map((node) => {
    const dx = (node.x ?? 0) - cx;
    const dy = (node.y ?? 0) - cy;
    const p = dy / (Math.abs(dx) + Math.abs(dy) || 1); // −1..1
    return dx < 0 ? 2 - p : p < 0 ? 4 + p : p; // 0..4 around the circle
  });
  const order = pseudo
    .map((_, i) => i)
    .sort((p, q) => (pseudo[p] as number) - (pseudo[q] as number) || p - q);
  // Symbols and tests: the members of containment links, which come after the drawn edges.
  const inner = new Uint8Array(n);
  for (let i = drawn; i < input.links.length / 2; i++) inner[input.links[i * 2 + 1] as number] = 1;
  order.forEach((node, rank) => {
    const angle = ((rank + 0.5) / n) * Math.PI * 2;
    const jitter = ((fnv(0x811c9dc5, input.ids[node] as string) % 1000) / 1000 - 0.5) * 2;
    const radius = inner[node] === 1 ? INNER_RADIUS + INNER_JITTER * jitter : 1;
    out[node * 2] = Math.cos(angle) * radius;
    out[node * 2 + 1] = Math.sin(angle) * radius;
  });
  return out;
}
