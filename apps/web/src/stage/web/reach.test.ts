// B14: the relations strands fire from, and each file's recent activity.
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { eventFile } from "../ring/sections";
import { streams } from "../streams/style";
import { MAX_BUNCH, ReachIndex } from "./reach";

const model = new CockpitModel();
model.ingest(runEvents());
const reach = new ReachIndex(model);
reach.sync();
const { graph, store } = model;
const PARSE_DATE = graph.byId.get("timekeeper.parse:parse_date#0") as number;
const NAIVE = graph.byId.get("tests/test_parse.py::test_naive_input") as number;

const ids = (out: Int32Array, n: number) =>
  Array.from(out.subarray(0, n), (node) => graph.ids[node] as string);

describe("ReachIndex", () => {
  it("collects a function's tests and callers, from covers and calls edges and trace samples", () => {
    const out = new Int32Array(64);
    const found = ids(out, reach.reachersOf(PARSE_DATE, store.length, -1, out, 0));
    expect(found).toHaveLength(15); // 7 tests and 8 callers
    expect(found).toContain("tests/test_parse.py::test_naive_input");
    expect(found).toContain("timekeeper.cli:main#0");
    expect(new Set(found).size).toBe(found.length);
    expect(found).not.toContain("timekeeper.parse:parse_date#0"); // never itself
  });

  it("collects what a test reaches, the same relations the other way", () => {
    const out = new Int32Array(64);
    const found = ids(out, reach.reachedBy(NAIVE, store.length, -1, out, 0));
    expect(found).toContain("timekeeper.parse:parse_date#0");
    for (const id of found)
      expect(graph.nodeTypeName(graph.byId.get(id) as number)).not.toBe("test");
  });

  it("collects a file's own functions, classes and tests", () => {
    const out = new Int32Array(64);
    const found = ids(out, reach.membersOf("timekeeper/parse.py", store.length, -1, out, 0));
    expect(found).toEqual(
      expect.arrayContaining(["timekeeper.parse:parse_date#0", "timekeeper.parse:_split_iso#0"]),
    );
    for (const id of found)
      expect(graph.files[graph.byId.get(id) as number]).toBe("timekeeper/parse.py");
  });

  it("uses only what the log said up to the event: a bunch never includes later nodes", () => {
    const sizes = [0, 400, 1_500, 1_700, store.length - 1].map((at) =>
      reach.reachersOf(PARSE_DATE, at, -1, new Int32Array(64), 0),
    );
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
    const n = early.reachersOf(PARSE_DATE, 1_699, -1, a, 0);
    expect(reach.reachersOf(PARSE_DATE, 1_699, -1, b, 0)).toBe(n);
    expect(Array.from(b.subarray(0, n))).toEqual(Array.from(a.subarray(0, n)));
  });

  it("skips the node that fired and stops when the bunch is full", () => {
    const out = new Int32Array(MAX_BUNCH);
    out[0] = NAIVE;
    const n = reach.reachersOf(PARSE_DATE, store.length, NAIVE, out, 1);
    expect(n).toBe(MAX_BUNCH);
    expect(ids(out, n).filter((id) => id === "tests/test_parse.py::test_naive_input")).toHaveLength(
      1,
    );
  });

  it("lists a file's recent streaming events, newest first, up to the event", () => {
    const at = model.kinds.lastIndex("trace.sample", store.length);
    const out = new Int32Array(24);
    const n = reach.recentEvents("timekeeper/parse.py", at, out);
    expect(n).toBeGreaterThan(0);
    for (let k = 0; k < n; k++) {
      const i = out[k] as number;
      expect(i).toBeLessThanOrEqual(at);
      if (k > 0) expect(i).toBeLessThan(out[k - 1] as number);
      const event = store.event(i);
      expect(event !== null && streams(event)).toBe(true);
      if (event !== null) expect(eventFile(model, event)).toBe("timekeeper/parse.py");
    }
  });
});
