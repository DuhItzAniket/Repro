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
  RING_ARC_X,
  RING_RADIUS,
  SIDE_ASPECT,
  STAGE_MIN_SHARE,
} from "./layout";

const right = (r: Rect) => r.x + r.w;
const bottom = (r: Rect) => r.y + r.h;
const overlaps = (a: Rect, b: Rect) =>
  a.x < right(b) && b.x < right(a) && a.y < bottom(b) && b.y < bottom(a);

describe("computeLayout at the reference sizes", () => {
  it("1440×900: the stage on the left near the reference's shape, 4 × 2 panels beside it", () => {
    const l = computeLayout(1440, 900);
    expect(l.mode).toBe("side");
    expect(l.header).toEqual({ x: 0, y: 0, w: 1440, h: 56 });
    expect(l.stage).toEqual({ x: 0, y: 56, w: 904, h: 844 });
    expect(l.panels.map((p) => [p.x, p.y, p.w, p.h])).toEqual([
      [912, 64, 256, 201],
      [1176, 64, 256, 201],
      [912, 273, 256, 201],
      [1176, 273, 256, 201],
      [912, 482, 256, 201],
      [1176, 482, 256, 201],
      [912, 691, 256, 201],
      [1176, 691, 256, 201],
    ]);
    expect(l.contentHeight).toBe(900);
    // The inner rim's radius is 1.02 H and its 3 o'clock point sits at 0.46 W (B14).
    expect(l.ring).toEqual({ cx: 904 * 0.46 - 844 * 1.02, cy: 422, r: 844 * 1.02 });
    // The drawer covers the panels, not the stage.
    expect(l.drawer).toEqual({ x: 1052, y: 64, w: 380, h: 828 });
    expect(l.transport).toEqual({ x: 8, y: 872, w: 888, h: 24 });
  });

  it("1920×1080: a 1178×1024 stage and panels of 359×246", () => {
    const l = computeLayout(1920, 1080);
    expect(l.mode).toBe("side");
    expect(l.stage).toEqual({ x: 0, y: 56, w: 1178, h: 1024 });
    expect(l.panels[0]).toEqual({ x: 1186, y: 64, w: 359, h: 246 });
    expect(l.panels[7]).toEqual({ x: 1553, y: 826, w: 359, h: 246 });
    expect(bottom(l.panels[7] as Rect)).toBe(1080 - PAD);
    expect(l.contentHeight).toBe(1080);
  });

  it("portrait windows get the reference's own arrangement: stage on top, 2 × 4 panels below", () => {
    const l = computeLayout(1200, 1500);
    expect(l.mode).toBe("stacked");
    expect(l.stage).toEqual({ x: 0, y: 56, w: 1200, h: 978 });
    expect(l.panels[0]).toEqual({ x: 8, y: 1042, w: 290, h: 221 });
    expect(l.panels[7]).toEqual({ x: 902, y: 1271, w: 290, h: 221 });
    expect(l.contentHeight).toBe(1500);
  });
});

function invariants(l: CockpitLayout): void {
  expect(l.header).toEqual({ x: 0, y: 0, w: l.width, h: HEADER_HEIGHT });
  expect(l.stage.y).toBe(HEADER_HEIGHT);
  expect(l.stage.x).toBe(0);
  expect(l.panels).toHaveLength(8);
  const columns = l.mode === "stacked" ? 4 : 2;
  for (const [i, p] of l.panels.entries()) {
    expect(p.w).toBeGreaterThan(0);
    expect(p.h).toBeGreaterThan(0);
    if (l.mode === "side") {
      expect(p.x).toBeGreaterThanOrEqual(right(l.stage) + GAP);
      expect(p.y).toBeGreaterThanOrEqual(HEADER_HEIGHT + PAD);
    } else {
      expect(p.y).toBeGreaterThanOrEqual(bottom(l.stage) + GAP);
      expect(p.x).toBeGreaterThanOrEqual(PAD);
    }
    expect(right(p)).toBeLessThanOrEqual(l.width - PAD);
    expect(bottom(p)).toBeLessThanOrEqual(l.contentHeight - PAD);
    for (const q of l.panels.slice(i + 1)) expect(overlaps(p, q)).toBe(false);
    // Neighbours sit exactly one gap apart.
    const next = l.panels[i + 1];
    if (next !== undefined && (i + 1) % columns !== 0) expect(next.x - right(p)).toBe(GAP);
  }
  // Rows fill their width edge to edge.
  expect(right(l.panels[columns - 1] as Rect)).toBe(l.width - PAD);
  // The ring follows the stage (B14).
  expect(l.ring.r).toBeCloseTo(l.stage.h * RING_RADIUS, 9);
  expect(l.ring.cx + l.ring.r).toBeCloseTo(l.stage.w * RING_ARC_X, 9);
  expect(l.ring.cy).toBe(l.stage.h / 2);
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
          if (w < NARROW_BELOW) {
            expect(l.mode).toBe("narrow");
            expect(l.stage.w).toBe(w);
            expect(l.stage.h).toBeGreaterThanOrEqual(h * 0.5);
            expect(l.contentHeight).toBeGreaterThan(l.stage.h + HEADER_HEIGHT);
          } else if (w >= h * SIDE_ASPECT) {
            expect(l.mode).toBe("side");
            expect(l.stage.h).toBe(h - HEADER_HEIGHT);
            expect(right(l.stage) + GAP + 2 * (l.panels[0] as Rect).w + GAP + PAD).toBe(w);
          } else {
            expect(l.mode).toBe("stacked");
            expect(l.stage.w).toBe(w);
            expect(l.stage.h / h).toBeGreaterThanOrEqual(STAGE_MIN_SHARE - 1e-9);
            if (l.contentHeight === h) expect(bottom(l.panels[7] as Rect)).toBe(h - PAD);
          }
        },
      ),
      { numRuns: 400 },
    );
  });

  it("lets short windows scroll instead of crushing the panels", () => {
    const l = computeLayout(1400, 500);
    expect(l.mode).toBe("side");
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
