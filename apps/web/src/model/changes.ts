/**
 * Changed symbols, test selections and the routes between them (change routes panel, change×check
 * index). Append-only like `TestIndex`: each entry records the store index of its event, so a
 * view can ask "as of cursor k" without folding.
 *
 * A selected test **routes** to a changed symbol S when:
 * 1. S is one of the symbols it was selected for, or one of those symbols calls S within
 *    `ROUTE_HOPS` `calls` edges (the blast radius, followed back to the change); or
 * 2. S is a module-level change (`<module>`) of module M and the test's module imports M
 *    (selections with reason `module_import` name no symbols).
 *
 * A selection is routed with the graph edges and changes that precede it in the log, which is
 * what the engine knew when it selected the test. Routes are therefore fixed once computed and
 * pure in the cursor.
 */

import type { GraphIndex } from "./graph";
import type { EventStore } from "./store";

/** How many `calls` edges a route may follow from a selected symbol back to a change. */
export const ROUTE_HOPS = 3;

export interface ChangedSymbol {
  readonly symbol: string;
  readonly file: string;
  readonly change: string;
  /** Store index of the `symbol.changed` event. */
  readonly index: number;
}

export interface Selection {
  readonly test: string;
  readonly symbols: readonly string[];
  readonly moduleImport: boolean;
  /** Store index of the `test.selected` event. */
  readonly index: number;
}

const MODULE_LEVEL = ":<module>#";

/** How many of the first `length` ascending values are below `bound` (binary search). */
function countBefore(values: Int32Array, length: number, bound: number): number {
  let lo = 0;
  let hi = length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((values[mid] as number) < bound) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The module part of a symbol id (`pkg.mod:name#0` → `pkg.mod`). */
export const moduleOf = (symbol: string): string => {
  const colon = symbol.indexOf(":");
  return colon < 0 ? symbol : symbol.slice(0, colon);
};

/** The short name of a symbol id (`pkg.mod:Class.method#0` → `Class.method`). */
export const nameOf = (symbol: string): string => {
  const colon = symbol.indexOf(":");
  const hash = symbol.lastIndexOf("#");
  return symbol.slice(colon + 1, hash < 0 ? undefined : hash);
};

/** The file part of a test id (`tests/test_x.py::test_y` → `tests/test_x.py`). */
export const testFile = (test: string): string => {
  const sep = test.indexOf("::");
  return sep < 0 ? test : test.slice(0, sep);
};

export class ChangeIndex {
  readonly changed: ChangedSymbol[] = [];
  readonly selections: Selection[] = [];
  private synced = 0;
  /** Changed-symbol indices per selection, computed once each. */
  private readonly routes: (readonly number[])[] = [];
  /** The log prefix `reach` and `importers` were built from: edge and change counts. */
  private builtFor = { edges: -1, changed: -1 };
  /** Symbol id → changed symbols it reaches within ROUTE_HOPS calls (itself included). */
  private reach = new Map<string, number[]>();
  /** Test file → module-level changes whose module that file's module imports. */
  private importers = new Map<string, number[]>();

  constructor(
    private readonly store: EventStore,
    private readonly graph: GraphIndex,
  ) {}

  sync(): void {
    for (let i = this.synced; i < this.store.length; i++) {
      const event = this.store.event(i);
      if (event?.kind === "symbol.changed") {
        const { symbol_id: symbol, file, change } = event.payload;
        this.changed.push({ symbol, file, change, index: i });
      } else if (event?.kind === "test.selected") {
        const test = event.target?.test;
        if (test === undefined) continue;
        this.selections.push({
          test,
          symbols: event.payload.symbols,
          moduleImport: event.payload.reasons.includes("module_import"),
          index: i,
        });
      }
    }
    this.synced = this.store.length;
  }

  /** Indices into `changed` that selection `s` routes to. */
  routesOf(s: number): readonly number[] {
    this.ensureRoutes();
    return this.routes[s] ?? [];
  }

  private ensureRoutes(): void {
    for (let s = this.routes.length; s < this.selections.length; s++) {
      const selection = this.selections[s] as Selection;
      const edges = countBefore(this.graph.edgeEvent, this.graph.edgeCount, selection.index);
      let changed = 0;
      while (
        changed < this.changed.length &&
        (this.changed[changed] as ChangedSymbol).index < selection.index
      )
        changed++;
      if (edges !== this.builtFor.edges || changed !== this.builtFor.changed)
        this.buildRouting(edges, changed);
      this.routes.push(this.route(selection));
    }
  }

  /** Builds `reach` and `importers` from the first `edges` graph edges and `changed` changes. */
  private buildRouting(edges: number, changed: number): void {
    const g = this.graph;
    const callers = new Map<number, number[]>();
    const importersOf = new Map<number, number[]>();
    for (let e = 0; e < edges; e++) {
      const type = g.edgeTypeName(e);
      const source = g.edgeSource[e] as number;
      const target = g.edgeTarget[e] as number;
      const into = type === "calls" ? callers : type === "imports" ? importersOf : null;
      if (into === null) continue;
      const list = into.get(target);
      if (list === undefined) into.set(target, [source]);
      else list.push(source);
    }
    const reach = new Map<string, number[]>();
    const importers = new Map<string, number[]>();
    const add = (map: Map<string, number[]>, key: string, c: number) => {
      const list = map.get(key);
      if (list === undefined) map.set(key, [c]);
      else if (!list.includes(c)) list.push(c);
    };
    this.changed.slice(0, changed).forEach((change, c) => {
      add(reach, change.symbol, c);
      if (change.symbol.includes(MODULE_LEVEL)) {
        const module = g.byId.get(moduleOf(change.symbol));
        for (const source of module === undefined ? [] : (importersOf.get(module) ?? []))
          add(importers, g.files[source] as string, c);
        return;
      }
      // Walk callers back from the change, up to ROUTE_HOPS edges.
      const start = g.byId.get(change.symbol);
      if (start === undefined) return;
      const seen = new Set([start]);
      let frontier = [start];
      for (let hop = 0; hop < ROUTE_HOPS && frontier.length > 0; hop++) {
        const next: number[] = [];
        for (const node of frontier)
          for (const caller of callers.get(node) ?? []) {
            if (seen.has(caller)) continue;
            seen.add(caller);
            next.push(caller);
            add(reach, g.ids[caller] as string, c);
          }
        frontier = next;
      }
    });
    this.reach = reach;
    this.importers = importers;
    this.builtFor = { edges, changed };
  }

  private route(selection: Selection): readonly number[] {
    const out: number[] = [];
    for (const symbol of selection.symbols)
      for (const c of this.reach.get(symbol) ?? []) if (!out.includes(c)) out.push(c);
    if (selection.moduleImport)
      for (const c of this.importers.get(testFile(selection.test)) ?? [])
        if (!out.includes(c)) out.push(c);
    return out.sort((a, b) => a - b);
  }
}
