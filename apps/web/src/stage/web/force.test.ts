import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { FRONT_ANGLE, FRONT_RADII, forceLayout } from "./force";
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
    expect(digest(positions)).toMatchInlineSnapshot(`"8a5470c2"`);
  });

  it("puts modules evenly on the circle and the run's nodes in the front sector", () => {
    const { graph } = demo;
    const modules: number[] = [];
    const front: number[] = [];
    for (let n = 0; n < graph.nodeCount; n++) {
      const x = positions[n * 2] as number;
      const y = positions[n * 2 + 1] as number;
      const r = Math.sqrt(x * x + y * y);
      const angle = Math.atan2(y, x);
      if (graph.nodeTypeName(n) === "module") {
        expect(r).toBeCloseTo(1, 6);
        modules.push((angle + Math.PI * 2) % (Math.PI * 2));
      } else {
        expect(r).toBeGreaterThanOrEqual(FRONT_RADII[0] - 1e-6);
        expect(r).toBeLessThanOrEqual(FRONT_RADII[1] + 1e-6);
        expect(Math.abs(angle)).toBeLessThanOrEqual(FRONT_ANGLE + 1e-6);
        front.push(angle);
      }
    }
    // Evenly spaced: sorted, neighbours are one slot apart.
    for (const [angles, slot] of [
      [modules, (Math.PI * 2) / modules.length],
      [front, (2 * FRONT_ANGLE) / front.length],
    ] as const) {
      const sorted = [...angles].sort((a, b) => a - b);
      for (let i = 1; i < sorted.length; i++) {
        expect((sorted[i] as number) - (sorted[i - 1] as number)).toBeCloseTo(slot, 5);
      }
    }
  });

  it("keeps a file's symbols and tests together in the front, in the circle's order", () => {
    const { graph } = demo;
    const byFile = new Map<string, number[]>();
    for (let n = 0; n < graph.nodeCount; n++) {
      if (graph.nodeTypeName(n) === "module") continue;
      const file = graph.files[n] as string;
      byFile.set(file, [
        ...(byFile.get(file) ?? []),
        Math.atan2(positions[n * 2 + 1] as number, positions[n * 2] as number),
      ]);
    }
    // Containment links pull a file's members together in the simulation, so they sit close in
    // the front: the median file spans less than a fifth of the sector.
    const spans = [...byFile.values()]
      .filter((angles) => angles.length > 1)
      .map((angles) => Math.max(...angles) - Math.min(...angles))
      .sort((a, b) => a - b);
    expect(spans.length).toBeGreaterThan(3);
    expect(spans[Math.floor(spans.length / 2)] as number).toBeLessThan((2 * FRONT_ANGLE) / 5);
  });

  it("handles an empty graph and the stress graph", () => {
    expect(forceLayout({ ids: [], links: new Int32Array(0), containment: 0 })).toHaveLength(0);
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
