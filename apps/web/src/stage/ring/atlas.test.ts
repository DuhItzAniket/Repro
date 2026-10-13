import { describe, expect, it } from "vitest";
import {
  ATLAS_MAX,
  ATLAS_SCALE,
  atlasLayout,
  CONTENT_CELL,
  drawAtlas,
  type TextSurface,
} from "./atlas";
import { AtlasService } from "./atlas-service";

describe("atlasLayout", () => {
  it("packs content and metadata cells side by side without overlap, within 2048 px", () => {
    const layout = atlasLayout(160);
    expect(layout.width).toBeLessThanOrEqual(ATLAS_MAX);
    expect(layout.height).toBeLessThanOrEqual(ATLAS_MAX);
    const rects = [...layout.content, ...layout.meta];
    for (const r of rects) {
      expect(r.u0).toBeGreaterThanOrEqual(0);
      expect(r.v0).toBeGreaterThanOrEqual(0);
      expect(r.u1).toBeLessThanOrEqual(1 + 1e-9);
      expect(r.v1).toBeLessThanOrEqual(1 + 1e-9);
    }
    for (let i = 0; i < rects.length; i++) {
      for (let j = i + 1; j < rects.length; j++) {
        const a = rects[i];
        const b = rects[j];
        if (a === undefined || b === undefined) continue;
        const overlap =
          a.u0 < b.u1 - 1e-9 && b.u0 < a.u1 - 1e-9 && a.v0 < b.v1 - 1e-9 && b.v0 < a.v1 - 1e-9;
        expect(overlap).toBe(false);
      }
    }
    expect(layout.content[0]?.u1).toBe(layout.meta[0]?.u0);
  });

  it("refuses more cards than fit", () => {
    expect(() => atlasLayout(10_000)).toThrow(RangeError);
  });
});

describe("drawAtlas", () => {
  it("writes each card's lines inside its own cell", () => {
    const calls: { text: string; x: number; y: number; max: number | undefined }[] = [];
    const surface: TextSurface = {
      font: "",
      fillStyle: "",
      textBaseline: "alphabetic",
      clearRect: () => {},
      fillText: (text, x, y, max) => calls.push({ text, x, y, max }),
    };
    const cards = [
      { lines: ["a.py", "import b"], meta: ["a.py", "1 imp"] },
      { lines: ["c.py"], meta: ["c.py"] },
    ];
    const layout = atlasLayout(cards.length);
    drawAtlas(surface, layout, cards);
    expect(calls.map((c) => c.text)).toEqual(["a.py", "import b", "a.py", "1 imp", "c.py", "c.py"]);
    expect(surface.textBaseline).toBe("top");
    const [x1] = layout.origins[1] as readonly [number, number];
    expect(calls[4]?.x).toBeGreaterThan(x1);
    expect(calls[0]?.max).toBeLessThanOrEqual(CONTENT_CELL.w * ATLAS_SCALE);
  });
});

describe("AtlasService", () => {
  const bitmap = () => {
    let closed = false;
    return {
      width: 1,
      height: 1,
      close: () => (closed = true),
      closed: () => closed,
    } as unknown as ImageBitmap & { closed(): boolean };
  };

  it("builds once per key and keeps only the newest result", async () => {
    const built: (ImageBitmap & { closed(): boolean })[] = [];
    const resolvers: ((b: ImageBitmap) => void)[] = [];
    const service = new AtlasService(() => new Promise((resolve) => resolvers.push(resolve)));
    const first = service.request("a", []);
    void service.request("a", []); // same key: no second build
    const second = service.request("b", []);
    expect(resolvers).toHaveLength(2);
    const [old, current] = [bitmap(), bitmap()];
    built.push(old, current);
    resolvers[1]?.(current);
    resolvers[0]?.(old);
    await Promise.all([first, second]);
    expect(service.bitmap).toBe(current);
    expect(service.version).toBe(1);
    expect(old.closed()).toBe(true); // a stale atlas is released, not leaked
  });
});
