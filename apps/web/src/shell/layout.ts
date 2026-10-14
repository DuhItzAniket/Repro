/**
 * Cockpit geometry (DESIGN.md "Layout"). One pure function computes every rectangle: header,
 * stage, the eight panels and the ring. The DOM, the stage renderer (B04) and the tests all
 * read it, so there is a single source of truth for where things are.
 *
 * The reference's stage is nearly square (about 1.15:1) and its composition depends on it: the
 * ring's arc spans the stage height, the web fills its inside and the streams the right (B14).
 * So the layout keeps the stage near that shape:
 * - **side** (landscape, width ≥ 1100 and at least 1.3 times the height): a 56 px header, the
 *   stage on the left, and the eight panels in 4 rows × 2 columns beside it.
 * - **stacked** (portrait-ish, width ≥ 1100): the reference's own arrangement. The stage on top
 *   (at least 55% of the height) and 2 rows × 4 panels in about 30% of the height beneath it.
 * - **narrow** (width < 1100): the stage keeps 60% of the height (≥ 50vh), and the panels
 *   become 2 columns × 4 rows that scroll.
 */

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

export interface Ring {
  /**
   * Centre and inner radius (the inner rim) in stage coordinates (px). The centre lies left of
   * the stage, so only the right arc shows. The band's thickness follows from the radius
   * (`ringBand` in stage/geometry.ts).
   */
  readonly cx: number;
  readonly cy: number;
  readonly r: number;
}

export type LayoutMode = "side" | "stacked" | "narrow";

export interface CockpitLayout {
  readonly mode: LayoutMode;
  readonly width: number;
  readonly height: number;
  /** Total content height; larger than `height` when the page scrolls. */
  readonly contentHeight: number;
  readonly header: Rect;
  readonly stage: Rect;
  readonly panels: readonly Rect[];
  readonly ring: Ring;
  /** The replay transport strip, along the bottom of the stage (B10). */
  readonly transport: Rect;
  /** The evidence drawer (B11): over the panels in the side layout, else over the stage's right. */
  readonly drawer: Rect;
}

export const HEADER_HEIGHT = 56;
export const TRANSPORT_HEIGHT = 24;
export const DRAWER_WIDTH = 380;
export const GAP = 8;
export const PAD = 8;
export const NARROW_BELOW = 1100;
/** Width-to-height ratio of the viewport from which the panels sit beside the stage. */
export const SIDE_ASPECT = 1.3;
/** The stage shape the side layout aims for: the reference's stage is about 1.15:1. */
export const STAGE_ASPECT = 1.15;
export const SIDE_PANEL_MIN_W = 256;
/** Side panels are at most this many times as wide as they are tall. */
export const SIDE_PANEL_MAX_ASPECT = 1.6;
export const PANEL_SHARE = 0.3;
export const STAGE_MIN_SHARE = 0.55;
export const NARROW_STAGE_SHARE = 0.6;
/** Below this panel row height, panels stop shrinking and the page scrolls instead. */
export const MIN_PANEL_ROW = 112;
export const NARROW_PANEL_ROW = 220;
export const PANEL_COUNT = 8;
/**
 * Ring geometry relative to the stage (DESIGN.md "Ring"), measured on the 1080×1350 reference
 * (B14): the inner rim's radius is 1.02 times the stage height, and its 3 o'clock point sits at
 * 0.46 of the stage width.
 */
export const RING_RADIUS = 1.02;
export const RING_ARC_X = 0.46;

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
  if (width < NARROW_BELOW) return narrowLayout(width, height);
  if (width >= height * SIDE_ASPECT) return sideLayout(width, height);
  return stackedLayout(width, height);
}

function narrowLayout(width: number, height: number): CockpitLayout {
  const header: Rect = { x: 0, y: 0, w: width, h: HEADER_HEIGHT };
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
    transport: transportFor(stage),
    drawer: drawerOver(stage),
  };
}

function stackedLayout(width: number, height: number): CockpitLayout {
  const header: Rect = { x: 0, y: 0, w: width, h: HEADER_HEIGHT };
  // Panels take about 30% of the height, unless that would squeeze the stage below 55%.
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
  return {
    mode: "stacked",
    width,
    height,
    contentHeight: top + panelArea + PAD,
    header,
    stage,
    panels,
    ring: ringFor(stage),
    transport: transportFor(stage),
    drawer: drawerOver(stage),
  };
}

function sideLayout(width: number, height: number): CockpitLayout {
  const header: Rect = { x: 0, y: 0, w: width, h: HEADER_HEIGHT };
  const stageH = height - HEADER_HEIGHT;
  // Four rows of panels fill the height beside the stage, unless they would get too short.
  let rows = split(height - HEADER_HEIGHT - 2 * PAD, 4, GAP);
  if ((rows[0] as number) < MIN_PANEL_ROW) rows = rows.map(() => MIN_PANEL_ROW);
  const rowH = rows[0] as number;
  // Two columns, as wide as keeps the stage near the reference's shape.
  const ideal = (width - 2 * GAP - PAD - STAGE_ASPECT * stageH) / 2;
  const panelW = Math.round(
    Math.min(
      Math.max(ideal, SIDE_PANEL_MIN_W),
      Math.max(SIDE_PANEL_MIN_W, SIDE_PANEL_MAX_ASPECT * rowH),
    ),
  );
  const columnW = 2 * panelW + GAP;
  const stageW = width - columnW - GAP - PAD;
  const stage: Rect = { x: 0, y: HEADER_HEIGHT, w: stageW, h: stageH };
  const top = HEADER_HEIGHT + PAD;
  const panels = grid(stageW + GAP, top, columnW, rows, 2);
  const panelsBottom = top + rows.reduce((sum, h) => sum + h, 0) + GAP * (rows.length - 1);
  const drawerW = Math.min(DRAWER_WIDTH, columnW);
  return {
    mode: "side",
    width,
    height,
    contentHeight: Math.max(height, panelsBottom + PAD),
    header,
    stage,
    panels,
    ring: ringFor(stage),
    transport: transportFor(stage),
    drawer: {
      x: width - PAD - drawerW,
      y: HEADER_HEIGHT + PAD,
      w: drawerW,
      h: height - HEADER_HEIGHT - 2 * PAD,
    },
  };
}

/** The drawer over the right of the stage, above the transport. */
function drawerOver(stage: Rect): Rect {
  const w = Math.min(DRAWER_WIDTH, stage.w - 2 * PAD);
  return {
    x: stage.x + stage.w - w - PAD,
    y: stage.y + PAD,
    w,
    h: stage.h - 2 * PAD - TRANSPORT_HEIGHT - PAD,
  };
}

function transportFor(stage: Rect): Rect {
  return {
    x: stage.x + PAD,
    y: stage.y + stage.h - TRANSPORT_HEIGHT - PAD / 2,
    w: stage.w - 2 * PAD,
    h: TRANSPORT_HEIGHT,
  };
}

function ringFor(stage: Rect): Ring {
  const r = stage.h * RING_RADIUS;
  return { cx: stage.w * RING_ARC_X - r, cy: stage.h / 2, r };
}
