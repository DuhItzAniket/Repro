import { describe, expect, it } from "vitest";
import { hashRenderModels, InstanceBuffers } from "./instances";
import { SEGMENT_ATTRIBUTES, segmentBuffers, segmentWriter } from "./segments";

function filled(values: (i: number) => number[]): InstanceBuffers {
  const buffers = segmentBuffers(4);
  const writer = segmentWriter(buffers);
  writer.begin();
  for (let i = 0; i < 3; i++) {
    const [ax, ay, bx, by, w, r, g, b, a, tail] = values(i) as [
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
      number,
    ];
    writer.push(ax, ay, bx, by, w, r, g, b, a, tail);
  }
  return buffers;
}

const base = (i: number) => [i, i * 2, 100 - i, 50, 1, 1, 1, 1, 0.25, 1];

describe("InstanceBuffers", () => {
  it("grows by doubling, keeps contents and bumps its generation", () => {
    const buffers = new InstanceBuffers(SEGMENT_ATTRIBUTES, 2);
    buffers.array("a").set([1, 2, 3, 4]);
    buffers.reserve(2);
    expect(buffers.generation).toBe(0);
    buffers.reserve(5);
    expect(buffers.capacity).toBe(8);
    expect(buffers.generation).toBe(1);
    expect([...buffers.array("a").subarray(0, 4)]).toEqual([1, 2, 3, 4]);
    expect(buffers.array("color")).toHaveLength(32);
    expect(() => buffers.array("nope")).toThrow();
  });
});

describe("segmentWriter", () => {
  it("writes each attribute in place, stops at its limit, and marks the buffers changed", () => {
    const buffers = segmentBuffers(8);
    const writer = segmentWriter(buffers, 2);
    const before = buffers.version;
    writer.begin();
    expect(buffers.version).toBe(before + 1);
    expect(writer.push(1, 2, 3, 4, 1.5, 0.1, 0.2, 0.3, 0.4, 0.5)).toBe(true);
    expect(writer.push(5, 6, 7, 8, 1, 1, 1, 1, 1, 1)).toBe(true);
    expect(writer.push(9, 9, 9, 9, 1, 1, 1, 1, 1, 1)).toBe(false);
    expect(buffers.count).toBe(2);
    expect([...buffers.array("a").subarray(0, 4)]).toEqual([1, 2, 5, 6]);
    expect([...buffers.array("b").subarray(0, 2)]).toEqual([3, 4]);
    expect([...buffers.array("color").subarray(0, 4)].map((v) => Math.round(v * 10))).toEqual([
      1, 2, 3, 4,
    ]);
    expect([...buffers.array("shape").subarray(0, 2)]).toEqual([1.5, 0.5]);
    writer.begin();
    expect(buffers.count).toBe(0);
  });

  it("follows the buffers when they are reallocated", () => {
    const buffers = segmentBuffers(1);
    const writer = segmentWriter(buffers);
    buffers.reserve(4);
    writer.begin();
    for (let i = 0; i < 4; i++) writer.push(i, i, i, i, 1, 1, 1, 1, 1, 1);
    expect([...buffers.array("a").subarray(0, 8)]).toEqual([0, 0, 1, 1, 2, 2, 3, 3]);
  });
});

describe("hashRenderModels", () => {
  const hash = (values: (i: number) => number[], layer = "edges") =>
    hashRenderModels([{ layer, buffers: filled(values) }]);

  it("is stable for the same data", () => {
    expect(hash(base)).toBe(hash(base));
    expect(hash(base)).toMatch(/^[0-9a-f]{16}$/);
  });

  it("ignores float noise far below a pixel, but sees any visible change", () => {
    expect(hash((i) => base(i).map((v) => v + 1e-6))).toBe(hash(base));
    expect(hash((i) => base(i).map((v, j) => (j === 0 && i === 2 ? v + 0.05 : v)))).not.toBe(
      hash(base),
    );
    expect(hash((i) => base(i).map((v, j) => (j === 8 ? 0.3 : v)))).not.toBe(hash(base));
  });

  it("covers layer names and instance counts", () => {
    expect(hash(base, "streaks")).not.toBe(hash(base, "edges"));
    const fewer = filled(base);
    fewer.count = 2;
    expect(hashRenderModels([{ layer: "edges", buffers: fewer }])).not.toBe(hash(base));
  });
});
