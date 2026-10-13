/**
 * Cockpit geometry (DESIGN.md "Layout"). One pure function computes every rectangle: header,
 * stage, the eight panels and the ring. The DOM, the stage renderer (B04) and the tests all
 * read it, so there is a single source of truth for where things are.
 *
 * Desktop (width ≥ 1100): a 56 px header, then the stage (at least 55% of the height), then
 * 2 × 4 panels in about 34% of the height with 8 px gaps. Narrow (< 1100): the stage keeps
 * 60% of the height (≥ 50vh), and the panels become 2 columns × 4 rows that scroll.
 */

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export interface Ring {
  /** Centre and radius in stage coordinates (px). The left part of the circle is off-screen. */
  readonly cx: number;
  readonly cy: number;
  readonly r: number;
}

export interface CockpitLayout {
  readonly mode: "desktop" | "narrow";
  readonly width: number;
  readonly height: number;
  /** Total content height; larger than `height` when the page scrolls. */
  readonly contentHeight: number;
  readonly header: Rect;
  readonly stage: Rect;
  readonly panels: readonly Rect[];
  readonly ring: Ring;
}

export const HEADER_HEIGHT = 56;
export const GAP = 8;
export const PAD = 8;
export const NARROW_BELOW = 1100;
export const PANEL_SHARE = 0.34;
export const STAGE_MIN_SHARE = 0.55;
export const NARROW_STAGE_SHARE = 0.6;
/** Below this panel row height, desktop panels stop shrinking and the page scrolls instead. */
export const MIN_PANEL_ROW = 112;
export const NARROW_PANEL_ROW = 220;
export const PANEL_COUNT = 8;
/** Ring geometry relative to the stage (DESIGN.md "Ring"). */
export const RING_CENTRE_X = 0.15;
export const RING_RADIUS = 0.55;

/** Splits `total` px into `n` integer parts separated by `gap`; the last part absorbs rounding. */
function split(total: number, n: number, gap: number): number[] {
  const each = Math.floor((total - gap * (n - 1)) / n);
  const parts = Array.from({ length: n }, () => each);
  parts[n - 1] = total - gap * (n - 1) - each * (n - 1);
  return parts;
}

function grid(x0: number, y0: number, width: number, rows: number[], columns: number): Rect[] {
  const cols = split(width, columns, GAP);
  const rects: Rect[] = [];
  let y = y0;
  for (const h of rows) {
    let x = x0;
    for (const w of cols) {
      rects.push({ x, y, w, h });
      x += w + GAP;
    }
    y += h + GAP;
  }
  return rects;
}

export function computeLayout(viewportWidth: number, viewportHeight: number): CockpitLayout {
  const width = Math.max(320, Math.floor(viewportWidth));
  const height = Math.max(320, Math.floor(viewportHeight));
  const header: Rect = { x: 0, y: 0, w: width, h: HEADER_HEIGHT };

  if (width < NARROW_BELOW) {
    const stageH = Math.round(height * NARROW_STAGE_SHARE);
    const stage: Rect = { x: 0, y: HEADER_HEIGHT, w: width, h: stageH };
    const rows = Array.from({ length: PANEL_COUNT / 2 }, () => NARROW_PANEL_ROW);
    const top = HEADER_HEIGHT + stageH + GAP;
    const panels = grid(PAD, top, width - 2 * PAD, rows, 2);
    const contentHeight = top + rows.reduce((sum, h) => sum + h, 0) + GAP * (rows.length - 1) + PAD;
    return {
      mode: "narrow",
      width,
      height,
      contentHeight,
      header,
      stage,
      panels,
      ring: ringFor(stage),
    };
  }

  // Panels take about 34% of the height, unless that would squeeze the stage below 55%.
  const chrome = HEADER_HEIGHT + GAP + PAD; // header, gap above the panels, bottom padding
  const stageMin = Math.ceil(height * STAGE_MIN_SHARE);
  let panelArea = Math.round(height * PANEL_SHARE);
  if (height - chrome - panelArea < stageMin) panelArea = height - chrome - stageMin;
  let rows = split(panelArea, 2, GAP);
  if ((rows[0] as number) < MIN_PANEL_ROW) {
    rows = [MIN_PANEL_ROW, MIN_PANEL_ROW];
    panelArea = 2 * MIN_PANEL_ROW + GAP;
  }
  const stageH = Math.max(stageMin, height - chrome - panelArea);
  const stage: Rect = { x: 0, y: HEADER_HEIGHT, w: width, h: stageH };
  const top = HEADER_HEIGHT + stageH + GAP;
  const panels = grid(PAD, top, width - 2 * PAD, rows, 4);
  const contentHeight = top + panelArea + PAD;
  return {
    mode: "desktop",
    width,
    height,
    contentHeight,
    header,
    stage,
    panels,
    ring: ringFor(stage),
  };
}

function ringFor(stage: Rect): Ring {
  return { cx: stage.w * RING_CENTRE_X, cy: stage.h / 2, r: stage.h * RING_RADIUS };
}
