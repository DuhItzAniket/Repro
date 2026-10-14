// B14: which nodes reach a function, so a bunch of strands fires from them.
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { MAX_BUNCH, ReachIndex } from "./reach";

const model = new CockpitModel();
model.ingest(runEvents());
const reach = new ReachIndex(model);
reach.sync();
const { graph, store } = model;
const PARSE_DATE = graph.byId.get("timekeeper.parse:parse_date#0") as number;
const out = new Int32Array(MAX_BUNCH);

/** The nodes `bunch` returns, as ids. */
function bunchIds(target: number, at: number, first?: number): string[] {
  const n = reach.bunch(target, at, first, out);
  return Array.from(out.subarray(0, n), (node) => graph.ids[node] as string);
}

describe("ReachIndex", () => {
  it("collects a function's tests and callers, from covers and calls edges and trace samples", () => {
    const ids = bunchIds(PARSE_DATE, store.length);
    expect(ids).toHaveLength(MAX_BUNCH); // 7 tests and 8 callers, capped
    expect(ids).toEqual(expect.arrayContaining(["tests/test_parse.py::test_naive_input"]));
    expect(ids).toEqual(expect.arrayContaining(["timekeeper.cli:main#0"]));
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).not.toContain("timekeeper.parse:parse_date#0"); // never itself
  });

  it("uses only what the log said up to the event: a bunch never includes later nodes", () => {
    const sizes: number[] = [];
    for (const at of [0, 400, 1_500, 1_700, store.length - 1]) {
      sizes.push(reach.bunch(PARSE_DATE, at, undefined, new Int32Array(64)));
    }
    expect(sizes[0]).toBe(0);
    for (let k = 1; k < sizes.length; k++)
      expect(sizes[k] as number).toBeGreaterThanOrEqual(sizes[k - 1] as number);
    // A fresh index over a prefix of the log agrees with the full one at that prefix.
    const prefix = new CockpitModel();
    prefix.ingest(runEvents().slice(0, 1_700));
    const early = new ReachIndex(prefix);
    early.sync();
    const a = new Int32Array(64);
    const b = new Int32Array(64);
    const n = early.bunch(PARSE_DATE, 1_699, undefined, a);
    expect(reach.bunch(PARSE_DATE, 1_699, undefined, b)).toBe(n);
    expect(Array.from(b.subarray(0, n))).toEqual(Array.from(a.subarray(0, n)));
  });

  it("puts the node that fired first, once", () => {
    const test = graph.byId.get("tests/test_parse.py::test_naive_input") as number;
    const ids = bunchIds(PARSE_DATE, store.length, test);
    expect(ids[0]).toBe("tests/test_parse.py::test_naive_input");
    expect(ids.filter((id) => id === ids[0])).toHaveLength(1);
  });
});
