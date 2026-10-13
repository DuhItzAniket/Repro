import { DEMO, FIXTURE_SEED, generateRun } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "./cockpit";
import { GraphIndex } from "./graph";
import { EventStore } from "./store";

const run = generateRun(DEMO, FIXTURE_SEED);
const model = new CockpitModel();
model.ingest(run.events);
const { graph } = model;

describe("GraphIndex", () => {
  it("holds every node and edge of the run, in arrival order", () => {
    expect(graph.nodeCount).toBe(run.summary.graphNodes);
    expect(graph.edgeCount).toBe(run.summary.graphEdges);
    expect(graph.dangling).toBe(0);
    const nodes = run.events.filter((e) => e.kind === "graph.node");
    expect(graph.ids).toEqual(nodes.map((e) => (e.kind === "graph.node" ? e.payload.node.id : "")));
    for (let e = 1; e < graph.edgeCount; e++) {
      expect(graph.edgeEvent[e]).toBeGreaterThan(graph.edgeEvent[e - 1] as number);
    }
  });

  it("knows node types and edge types", () => {
    const types = new Set(graph.ids.map((_, i) => graph.nodeTypeName(i)));
    expect(types).toEqual(new Set(["module", "function", "method", "class", "test"]));
    const edgeTypes = new Set(
      Array.from({ length: graph.edgeCount }, (_, e) => graph.edgeTypeName(e)),
    );
    expect(edgeTypes).toEqual(new Set(["imports", "calls", "covers"]));
  });

  it("maps module-level symbols to their module node", () => {
    const fmt = graph.byId.get("timekeeper.fmt");
    expect(fmt).toBeDefined();
    expect(graph.nodeForSymbol("timekeeper.fmt:<module>#0")).toBe(fmt);
    expect(graph.nodeForSymbol("timekeeper.parse:parse_date#0")).toBe(
      graph.byId.get("timekeeper.parse:parse_date#0"),
    );
    expect(graph.nodeForSymbol("nowhere")).toBeUndefined();
  });

  it("syncs incrementally and counts edges whose endpoints are unknown", () => {
    const store = new EventStore();
    const partial = new GraphIndex(store);
    store.appendAll(run.events.slice(0, 600));
    partial.sync();
    const before = partial.version;
    store.appendAll(run.events.slice(600));
    partial.sync();
    expect(partial.version).toBeGreaterThan(before);
    expect(partial.edgeCount).toBe(graph.edgeCount);
    // An edge to a node that never appears is counted, not drawn.
    const edge = run.events.find((e) => e.kind === "graph.edge");
    const orphan = {
      ...(edge as object),
      seq: store.length + 1,
      payload: { source: "a", target: "b", type: "imports" },
    };
    store.append(orphan);
    partial.sync();
    expect(partial.dangling).toBe(1);
  });
});
