/**
 * Layout of the dependency web (DESIGN.md "Dependency web"; ARCHITECTURE §13). A force-directed
 * simulation orders the nodes, and the result is a **chord layout** (B14):
 * - modules sit on a circle (under the ring's band), in the angular order the simulation gave
 *   them, evenly spaced. Tightly connected modules end up next to each other, so their edges are
 *   short arcs near the rim, and edges between distant parts of the repo cross the disc as long
 *   curves: the reference's hairball, from real edges;
 * - symbols and tests, the nodes a run touches, are scattered across the whole part of the disc
 *   the stage shows (`NODE_REGION`), by a placement rule (`placeNode`): their height from their
 *   rank in the simulation's order, so connected nodes sit near each other; their depth towards
 *   the wheel from their role, tests deeper in and functions nearer the wheel. Strands fire from
 *   them to the ring. The rule is one function, so the engine can replace it later.
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
import { RING_ARC_X, RING_RADIUS, STAGE_ASPECT } from "../../shell/layout";
import { WEB_SCALE } from "../geometry";
import { fnv, type LayoutInput } from "./layout-input";

export const LAYOUT_TICKS = 300;
/**
 * The part of the web's disc the stage shows, in unit-disc coordinates (unit = the modules'
 * circle), with a margin: from the stage's left edge to just inside the ring's inner rim, and
 * from its top to its bottom. Derived from the layout's ring rule at the side layout's stage
 * shape (1.15:1); at other shapes it is close, and nodes outside the stage are simply not drawn.
 */
export const NODE_REGION = {
  /** Unit x of the stage's left edge, plus a margin. */
  left: (RING_RADIUS - RING_ARC_X * STAGE_ASPECT) / (WEB_SCALE * RING_RADIUS) + 0.035,
  /** Largest |unit y| on the stage, less a margin. */
  top: 0.5 / (WEB_SCALE * RING_RADIUS) - 0.025,
  /** Unit radius just inside the inner rim. */
  rim: 1 / WEB_SCALE - 0.03,
} as const;

/** How deep in the web a node sits, 0 (far side) to 1 (at the wheel), by its role. */
const DEPTH = { test: [0.04, 0.6], symbol: [0.3, 0.96] } as const;

/**
 * Where a symbol or test goes (unit-disc coordinates), by the placement rule: `rank` of `count`
 * sets its height (top to bottom, in the simulation's order, ± a third of a slot), and its role
 * and a hash of its id set its depth from the region's left edge to the rim.
 */
export function placeNode(
  rank: number,
  count: number,
  test: boolean,
  id: string,
  out: Float32Array,
  at: number,
): void {
  const h = fnv(0x9747b28c, id);
  const jitter = ((h & 0xffff) / 0xffff - 0.5) * (2 / 3);
  const y = -NODE_REGION.top + (2 * NODE_REGION.top * (rank + 0.5 + jitter)) / count;
  const [lo, hi] = test ? DEPTH.test : DEPTH.symbol;
  const depth = lo + (hi - lo) * ((h >>> 16) / 0xffff);
  // From the left edge to the rim at this height: the region is the disc cut by the stage.
  const right = Math.sqrt(NODE_REGION.rim * NODE_REGION.rim - y * y);
  out[at * 2] = NODE_REGION.left + (right - NODE_REGION.left) * depth;
  out[at * 2 + 1] = y;
}

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
 * Runs the simulation and returns positions: modules on the unit circle, each at the angle of its
 * rank around the simulation's centroid; symbols and tests across the visible region, by
 * `placeNode` in the same order.
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
  const innerCount = inner.reduce((sum, v) => sum + v, 0);
  const moduleCount = n - innerCount;
  let moduleRank = 0;
  let innerRank = 0;
  for (const node of order) {
    if (inner[node] === 1) {
      placeNode(
        innerRank++,
        innerCount,
        input.tests[node] === 1,
        input.ids[node] as string,
        out,
        node,
      );
      continue;
    }
    const angle = ((moduleRank++ + 0.5) / moduleCount) * Math.PI * 2;
    out[node * 2] = Math.cos(angle);
    out[node * 2 + 1] = Math.sin(angle);
  }
  return out;
}
