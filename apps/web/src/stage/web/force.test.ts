import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { forceLayout, NODE_REGION, placeNode } from "./force";
import { type LayoutInput, layoutHash, layoutInput } from "./layout-input";
import { computeInline, LayoutService } from "./layout-service";

function modelOf(events: readonly unknown[]): CockpitModel {
  const model = new CockpitModel();
  model.ingest(events);
  return model;
}

const demo = modelOf(runEvents());
const input = layoutInput(demo.graph);

/** Positions quantised to 1/1000 of the disc radius and hashed (FNV-1a), for pinning. */
function digest(positions: Float32Array): string {
  let h = 0x811c9dc5;
  for (const v of positions) h = Math.imul(h ^ (Math.round(v * 1000) | 0), 0x01000193) >>> 0;
  return h.toString(16).padStart(8, "0");
}

describe("layoutInput", () => {
  it("lists drawn edges first, then containment links tying symbols and tests to their module", () => {
    const { graph } = demo;
    expect(input.ids).toEqual(graph.ids);
    expect(input.links.length / 2).toBe(graph.edgeCount + input.containment);
    const nonModules = graph.ids.filter((_, i) => graph.nodeTypeName(i) !== "module").length;
    expect(input.containment).toBe(nonModules);
    for (let i = graph.edgeCount; i < input.links.length / 2; i++) {
      expect(graph.nodeTypeName(input.links[i * 2] as number)).toBe("module");
    }
  });

  it("hashes stably and changes with the graph", () => {
    expect(layoutHash(input)).toBe(layoutHash(layoutInput(demo.graph)));
    const fewer: LayoutInput = { ...input, links: input.links.slice(0, -2) };
    expect(layoutHash(fewer)).not.toBe(layoutHash(input));
    const renamed: LayoutInput = { ...input, ids: ["x", ...input.ids.slice(1)] };
    expect(layoutHash(renamed)).not.toBe(layoutHash(input));
  });
});

describe("forceLayout (B05: identical across reloads; a chord layout since B14)", () => {
  const positions = forceLayout(input);

  it("is deterministic", () => {
    expect(forceLayout(input)).toEqual(positions);
  });

  it("pins the demo layout (same on every OS in CI)", () => {
    expect(digest(positions)).toMatchInlineSnapshot(`"fd69d2f7"`);
  });

  it("puts modules evenly on the circle and scatters the run's nodes across the visible web", () => {
    const { graph } = demo;
    const modules: number[] = [];
    const ys: number[] = [];
    const xs: number[] = [];
    for (let n = 0; n < graph.nodeCount; n++) {
      const x = positions[n * 2] as number;
      const y = positions[n * 2 + 1] as number;
      if (graph.nodeTypeName(n) === "module") {
        expect(Math.sqrt(x * x + y * y)).toBeCloseTo(1, 6);
        modules.push((Math.atan2(y, x) + Math.PI * 2) % (Math.PI * 2));
        continue;
      }
      // Inside the region the stage shows: right of its left edge, inside the rim, on the stage.
      expect(x).toBeGreaterThanOrEqual(NODE_REGION.left - 1e-6);
      expect(Math.abs(y)).toBeLessThanOrEqual(NODE_REGION.top + 1e-6);
      expect(Math.sqrt(x * x + y * y)).toBeLessThanOrEqual(NODE_REGION.rim + 1e-6);
      xs.push(x);
      ys.push(y);
    }
    const sorted = [...modules].sort((a, b) => a - b);
    for (let i = 1; i < sorted.length; i++) {
      expect((sorted[i] as number) - (sorted[i - 1] as number)).toBeCloseTo(
        (Math.PI * 2) / sorted.length,
        5,
      );
    }
    // Spread over the whole region: every quarter of its height and of its depth has nodes.
    for (const [values, lo, hi] of [
      [ys, -NODE_REGION.top, NODE_REGION.top],
      [xs, NODE_REGION.left, NODE_REGION.rim],
    ] as const) {
      for (let q = 0; q < 4; q++) {
        const from = lo + ((hi - lo) * q) / 4;
        const to = lo + ((hi - lo) * (q + 1)) / 4;
        expect(values.some((v) => v >= from && v <= to)).toBe(true);
      }
    }
  });

  it("places by a rule: height by the simulation's order, depth by role (tests deeper in)", () => {
    const { graph } = demo;
    let tests = 0;
    let testDepth = 0;
    let symbols = 0;
    let symbolDepth = 0;
    for (let n = 0; n < graph.nodeCount; n++) {
      const type = graph.nodeTypeName(n);
      if (type === "module") continue;
      const x = positions[n * 2] as number;
      if (type === "test") {
        tests++;
        testDepth += x;
      } else {
        symbols++;
        symbolDepth += x;
      }
    }
    expect(testDepth / tests).toBeLessThan(symbolDepth / symbols);
    // The rule itself: rank sets the height, top to bottom.
    const out = new Float32Array(4);
    placeNode(0, 10, false, "a", out, 0);
    placeNode(9, 10, false, "a", out, 1);
    expect(out[1] as number).toBeLessThan(out[3] as number);
    // A test sits deeper in (further from the wheel) than a symbol with the same id and slot.
    placeNode(4, 10, true, "b", out, 0);
    placeNode(4, 10, false, "b", out, 1);
    expect(out[1]).toBe(out[3]); // the same height
    expect(out[0] as number).toBeLessThan(out[2] as number);
  });

  it("handles an empty graph and the stress graph", () => {
    expect(
      forceLayout({ ids: [], links: new Int32Array(0), containment: 0, tests: new Uint8Array(0) }),
    ).toHaveLength(0);
    const stress = modelOf(runEvents(STRESS));
    const big = forceLayout(layoutInput(stress.graph), 20); // few ticks: shape, not quality
    expect(big).toHaveLength(stress.graph.nodeCount * 2);
    expect(big.every((v) => Number.isFinite(v) && Math.abs(v) <= 1)).toBe(true);
  });
});

describe("LayoutService", () => {
  it("lays out once per graph and serves repeats from its cache", async () => {
    let computed = 0;
    const service = new LayoutService(demo.graph, (i) => {
      computed++;
      return computeInline(i);
    });
    expect(service.positions).toBeNull();
    await service.request();
    expect(service.version).toBe(1);
    expect(service.positions).toEqual(forceLayout(input));
    await service.request();
    expect([computed, service.version]).toEqual([1, 1]);
  });

  it("keeps only the newest request when layouts finish out of order", async () => {
    const small = modelOf(runEvents().slice(0, 700));
    const resolvers: ((p: Float32Array) => void)[] = [];
    const service = new LayoutService(
      small.graph,
      () => new Promise((resolve) => resolvers.push(resolve)),
    );
    const first = service.request();
    small.ingest(runEvents().slice(700));
    const second = service.request();
    resolvers[1]?.(new Float32Array([2, 2]));
    resolvers[0]?.(new Float32Array([1, 1]));
    await Promise.all([first, second]);
    expect([...(service.positions ?? [])]).toEqual([2, 2]);
  });
});
