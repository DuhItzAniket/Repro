import { describe, expect, it } from "vitest";
import {
  ATLAS_MAX,
  ATLAS_SCALE,
  type AtlasCard,
  atlasLayout,
  CARD_UNITS,
  cardUnits,
  DOT_COLS,
  drawAtlas,
  ROW_PITCH,
  type TextSurface,
} from "./atlas";
import { AtlasService } from "./atlas-service";

describe("atlasLayout", () => {
  it("packs cells of each card's own size without overlap, within 2048 px", () => {
    const units = Array.from({ length: 64 }, (_, i) => 30 + ((i * 37) % 80));
    const layout = atlasLayout(units);
    expect(layout.width).toBeLessThanOrEqual(ATLAS_MAX);
    expect(layout.height).toBeLessThanOrEqual(ATLAS_MAX);
    expect(layout.scale).toBe(ATLAS_SCALE);
    const rects = layout.cells;
    rects.forEach((r, i) => {
      // Cells keep their aspect: band units across, the card's units along.
      expect((r.u1 - r.u0) * layout.width).toBeCloseTo(CARD_UNITS * layout.scale, 6);
      expect((r.v1 - r.v0) * layout.height).toBeCloseTo((units[i] as number) * layout.scale, 6);
    });
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
  });

  it("lowers the scale when the cards do not fit at full scale, and refuses what never fits", () => {
    const crowded = atlasLayout(Array.from({ length: 80 }, () => 120));
    expect(crowded.scale).toBeLessThan(ATLAS_SCALE);
    expect(crowded.height).toBeLessThanOrEqual(ATLAS_MAX);
    expect(() => atlasLayout(Array.from({ length: 10_000 }, () => 100))).toThrow(RangeError);
  });
});

describe("cardUnits", () => {
  it("fits the header, the rows and the dot grid", () => {
    const card: AtlasCard = { header: "// a / b", rows: [], dots: [], dotRows: 0, meta: [] };
    expect(cardUnits(card)).toBe(30); // the minimum
    const rows = Array.from({ length: 10 }, () => ({ num: "1", text: "x", flag: false }));
    expect(cardUnits({ ...card, rows })).toBe(14 + 10 * ROW_PITCH + 4);
    expect(cardUnits({ ...card, rows, dots: [1], dotRows: 4 })).toBe(14 + 10 * ROW_PITCH + 18 + 4);
  });
});

describe("drawAtlas", () => {
  it("writes each card's header, rows, dots and labels inside its own cell", () => {
    const calls: { text: string; x: number; y: number; style: string }[] = [];
    const dots: { x: number; y: number; style: string }[] = [];
    const surface: TextSurface = {
      font: "",
      fillStyle: "",
      textBaseline: "alphabetic",
      textAlign: "left",
      clearRect: () => {},
      fillRect: (x, y, w, h) => {
        if (w === h) dots.push({ x, y, style: String(surface.fillStyle) });
      },
      fillText: (text, x, y) => calls.push({ text, x, y, style: String(surface.fillStyle) }),
      measureText: (text) => ({ width: text.length * 6 }),
    };
    const cards: AtlasCard[] = [
      {
        header: "// pkg / a",
        rows: [
          { num: "12", text: "def f()", flag: true },
          { num: "", text: "import b", flag: false },
        ],
        dots: [0, 17],
        dotRows: 2,
        meta: ["1 imp", ""],
      },
      { header: "// c", rows: [], dots: [], dotRows: 0, meta: ["0 imp"] },
    ];
    const layout = atlasLayout(cards.map(cardUnits));
    drawAtlas(surface, layout, cards);
    expect(calls.map((c) => c.text)).toEqual([
      "// pkg / a",
      "12",
      "def f()",
      "import b",
      "1 imp",
      "// c",
      "0 imp",
    ]);
    expect(surface.textBaseline).toBe("top");
    // A changed row is pure red, which the shader reads as --flag.
    expect(calls[2]?.style).toBe("rgba(255,0,0,0.95)");
    // The second card's text lies inside its own cell.
    const [x1, y1] = layout.origins[1] as readonly [number, number];
    for (const call of calls.slice(5)) {
      expect(call.x).toBeGreaterThanOrEqual(x1);
      expect(call.y).toBeGreaterThanOrEqual(y1);
    }
    // Two rows of DOT_COLS dots, two of them lit.
    expect(dots).toHaveLength(2 * DOT_COLS);
    expect(dots.filter((d) => d.style.endsWith("0.92)"))).toHaveLength(2);
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
