/**
 * The dependency-web layout's input and cache key (B05). Kept apart from the d3-force simulation
 * (`force.ts`), so the main thread can build inputs and hashes without loading d3. The
 * simulation itself runs in `layout.worker.ts`.
 */
import type { GraphIndex } from "../../model/graph";

export interface LayoutInput {
  /** Node ids; positions come back in this order. */
  readonly ids: readonly string[];
  /** Link endpoints as node indices, flattened pairs [s0, t0, s1, t1, …]. */
  readonly links: Int32Array;
  /** How many of `links` (from the end) are containment links. */
  readonly containment: number;
}

/** FNV-1a 32 over a string, continuing from `hash`. */
export function fnv(hash: number, text: string): number {
  let h = hash;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 0x01000193);
  return h >>> 0;
}

/** Builds the layout input from the graph as it is now: drawn edges, then containment links. */
export function layoutInput(graph: GraphIndex): LayoutInput {
  const moduleOfFile = new Map<string, number>();
  for (let i = 0; i < graph.nodeCount; i++) {
    if (graph.nodeTypeName(i) === "module") moduleOfFile.set(graph.files[i] as string, i);
  }
  const contain: number[] = [];
  for (let i = 0; i < graph.nodeCount; i++) {
    if (graph.nodeTypeName(i) === "module") continue;
    const owner = moduleOfFile.get(graph.files[i] as string);
    if (owner !== undefined) contain.push(owner, i);
  }
  const links = new Int32Array(graph.edgeCount * 2 + contain.length);
  for (let e = 0; e < graph.edgeCount; e++) {
    links[e * 2] = graph.edgeSource[e] as number;
    links[e * 2 + 1] = graph.edgeTarget[e] as number;
  }
  links.set(contain, graph.edgeCount * 2);
  return { ids: graph.ids.slice(), links, containment: contain.length / 2 };
}

/** Cache key: changes whenever a node or link is added, removed or reordered. */
export function layoutHash(input: LayoutInput): string {
  let a = 0x811c9dc5;
  let b = fnv(0x811c9dc5, "repro-layout/1");
  for (const id of input.ids) {
    a = fnv(a, id);
    b = fnv(b, `${id.length}`);
  }
  for (let i = 0; i < input.links.length; i++) {
    a = Math.imul(a ^ (input.links[i] as number), 0x01000193) >>> 0;
    b = Math.imul(b ^ ((input.links[i] as number) + i), 0x5bd1e995) >>> 0;
  }
  return `${a.toString(16).padStart(8, "0")}${b.toString(16).padStart(8, "0")}:${input.ids.length}`;
}
