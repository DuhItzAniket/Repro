/**
 * The dependency graph as append-only tables (ARCHITECTURE §13, indexed state): nodes and
 * edges in the order `graph.node` / `graph.edge` events arrived, each with the store index of
 * its event, so "the graph as of cursor k" is a prefix. Folding and snapshots are not needed.
 */
import type { EventStore } from "./store";

export type NodeType = "module" | "class" | "function" | "method" | "test";
export type EdgeType = "imports" | "calls" | "covers";

const NODE_TYPES: readonly NodeType[] = ["module", "class", "function", "method", "test"];
const EDGE_TYPES: readonly EdgeType[] = ["imports", "calls", "covers"];

function growInt(array: Int32Array, need: number): Int32Array {
  if (need <= array.length) return array;
  let size = array.length;
  while (size < need) size *= 2;
  const next = new Int32Array(size);
  next.set(array);
  return next;
}

function growByte(array: Uint8Array, need: number): Uint8Array {
  if (need <= array.length) return array;
  let size = array.length;
  while (size < need) size *= 2;
  const next = new Uint8Array(size);
  next.set(array);
  return next;
}

export class GraphIndex {
  /** Node ids in arrival order. */
  readonly ids: string[] = [];
  readonly files: string[] = [];
  readonly byId = new Map<string, number>();
  nodeType: Uint8Array = new Uint8Array(256);
  /** Store index of each node's `graph.node` event. */
  nodeEvent: Int32Array = new Int32Array(256);
  edgeSource: Int32Array = new Int32Array(1024);
  edgeTarget: Int32Array = new Int32Array(1024);
  edgeType: Uint8Array = new Uint8Array(1024);
  /** Store index of each edge's `graph.edge` event. */
  edgeEvent: Int32Array = new Int32Array(1024);
  edgeCount = 0;
  /** Edges whose endpoints were not (yet) known nodes; they are not drawn. */
  dangling = 0;
  /** Bumped whenever a node or edge is added. */
  version = 0;
  private synced = 0;

  constructor(private readonly store: EventStore) {}

  get nodeCount(): number {
    return this.ids.length;
  }

  nodeTypeName(i: number): NodeType {
    return NODE_TYPES[this.nodeType[i] as number] ?? "module";
  }

  edgeTypeName(i: number): EdgeType {
    return EDGE_TYPES[this.edgeType[i] as number] ?? "imports";
  }

  /** Indexes `graph.*` events appended since the last call. */
  sync(): void {
    for (let i = this.synced; i < this.store.length; i++) {
      const event = this.store.event(i);
      if (event?.kind === "graph.node") {
        const { id, type, file } = event.payload.node;
        if (this.byId.has(id)) continue;
        const n = this.ids.length;
        this.nodeType = growByte(this.nodeType, n + 1);
        this.nodeEvent = growInt(this.nodeEvent, n + 1);
        this.byId.set(id, n);
        this.ids.push(id);
        this.files.push(file);
        this.nodeType[n] = Math.max(0, NODE_TYPES.indexOf(type));
        this.nodeEvent[n] = i;
        this.version++;
      } else if (event?.kind === "graph.edge") {
        const source = this.byId.get(event.payload.source);
        const target = this.byId.get(event.payload.target);
        if (source === undefined || target === undefined) {
          this.dangling++;
          continue;
        }
        const e = this.edgeCount;
        this.edgeSource = growInt(this.edgeSource, e + 1);
        this.edgeTarget = growInt(this.edgeTarget, e + 1);
        this.edgeType = growByte(this.edgeType, e + 1);
        this.edgeEvent = growInt(this.edgeEvent, e + 1);
        this.edgeSource[e] = source;
        this.edgeTarget[e] = target;
        this.edgeType[e] = Math.max(0, EDGE_TYPES.indexOf(event.payload.type));
        this.edgeEvent[e] = i;
        this.edgeCount = e + 1;
        this.version++;
      }
    }
    this.synced = this.store.length;
  }

  /** Node index for a symbol id, falling back to its module for module-level symbols. */
  nodeForSymbol(symbolId: string): number | undefined {
    const direct = this.byId.get(symbolId);
    if (direct !== undefined) return direct;
    const colon = symbolId.indexOf(":");
    return colon < 0 ? undefined : this.byId.get(symbolId.slice(0, colon));
  }
}
