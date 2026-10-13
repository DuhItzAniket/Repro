import fc from "fast-check";
import { describe, expect, it } from "vitest";
import {
  type CockpitLayout,
  computeLayout,
  GAP,
  HEADER_HEIGHT,
  NARROW_BELOW,
  PAD,
  type Rect,
  STAGE_MIN_SHARE,
} from "./layout";

const right = (r: Rect) => r.x + r.w;
const bottom = (r: Rect) => r.y + r.h;
const overlaps = (a: Rect, b: Rect) =>
  a.x < right(b) && b.x < right(a) && a.y < bottom(b) && b.y < bottom(a);

describe("computeLayout at the B03 reference sizes", () => {
  it("1440×900: 56 px header, 58% stage, 2×4 panels of 350×149 with 8 px gaps", () => {
    const l = computeLayout(1440, 900);
    expect(l.mode).toBe("desktop");
    expect(l.header).toEqual({ x: 0, y: 0, w: 1440, h: 56 });
    expect(l.stage).toEqual({ x: 0, y: 56, w: 1440, h: 522 });
    expect(l.panels.map((p) => [p.x, p.y, p.w, p.h])).toEqual([
      [8, 586, 350, 149],
      [366, 586, 350, 149],
      [724, 586, 350, 149],
      [1082, 586, 350, 149],
      [8, 743, 350, 149],
      [366, 743, 350, 149],
      [724, 743, 350, 149],
      [1082, 743, 350, 149],
    ]);
    expect(l.contentHeight).toBe(900);
    expect(l.ring).toEqual({ cx: 216, cy: 261, r: 522 * 0.55 });
  });

  it("1920×1080: 59% stage, panels of 470 px in about 34% of the height", () => {
    const l = computeLayout(1920, 1080);
    expect(l.stage).toEqual({ x: 0, y: 56, w: 1920, h: 641 });
    expect(l.panels[0]).toEqual({ x: 8, y: 705, w: 470, h: 179 });
    expect(l.panels[7]).toEqual({ x: 1442, y: 892, w: 470, h: 180 });
    expect(bottom(l.panels[7] as Rect)).toBe(1080 - PAD);
    expect(l.contentHeight).toBe(1080);
  });
});

function invariants(l: CockpitLayout): void {
  expect(l.header).toEqual({ x: 0, y: 0, w: l.width, h: HEADER_HEIGHT });
  expect(l.stage.y).toBe(HEADER_HEIGHT);
  expect(l.stage.w).toBe(l.width);
  expect(l.panels).toHaveLength(8);
  const columns = l.mode === "desktop" ? 4 : 2;
  for (const [i, p] of l.panels.entries()) {
    expect(p.w).toBeGreaterThan(0);
    expect(p.h).toBeGreaterThan(0);
    expect(p.y).toBeGreaterThanOrEqual(bottom(l.stage) + GAP);
    expect(p.x).toBeGreaterThanOrEqual(PAD);
    expect(right(p)).toBeLessThanOrEqual(l.width - PAD);
    expect(bottom(p)).toBeLessThanOrEqual(l.contentHeight - PAD);
    for (const q of l.panels.slice(i + 1)) expect(overlaps(p, q)).toBe(false);
    // Neighbours sit exactly one gap apart.
    const next = l.panels[i + 1];
    if (next !== undefined && (i + 1) % columns !== 0) expect(next.x - right(p)).toBe(GAP);
  }
  // Rows fill the width edge to edge.
  expect(right(l.panels[columns - 1] as Rect)).toBe(l.width - PAD);
}

describe("computeLayout for any viewport", () => {
  it("keeps the DESIGN.md invariants", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 320, max: 3840 }),
        fc.integer({ min: 320, max: 2160 }),
        (w, h) => {
          const l = computeLayout(w, h);
          invariants(l);
          if (w >= NARROW_BELOW) {
            expect(l.mode).toBe("desktop");
            expect(l.stage.h / h).toBeGreaterThanOrEqual(STAGE_MIN_SHARE - 1e-9);
            if (l.contentHeight === h) expect(bottom(l.panels[7] as Rect)).toBe(h - PAD);
          } else {
            expect(l.mode).toBe("narrow");
            expect(l.stage.h).toBeGreaterThanOrEqual(h * 0.5);
            expect(l.contentHeight).toBeGreaterThan(l.stage.h + HEADER_HEIGHT);
          }
        },
      ),
      { numRuns: 400 },
    );
  });

  it("lets short desktop windows scroll instead of crushing the panels", () => {
    const l = computeLayout(1400, 500);
    expect(l.mode).toBe("desktop");
    expect(l.contentHeight).toBeGreaterThan(500);
    expect(l.panels[0]?.h).toBe(112);
  });

  it("switches to two scrolling columns below 1100 px", () => {
    const l = computeLayout(1024, 768);
    expect(l.mode).toBe("narrow");
    expect(l.stage.h).toBe(Math.round(768 * 0.6));
    expect(new Set(l.panels.map((p) => p.x)).size).toBe(2);
    expect(l.contentHeight).toBeGreaterThan(768);
  });
});
