/**
 * The card atlas: every card's text drawn once into one texture, so the whole ring is a
 * single instanced draw call (ADR-0008: "ring cards from a Canvas-2D atlas"). Packing is a pure
 * function; drawing takes any Canvas-2D context, the worker's OffscreenCanvas or the main
 * thread's fallback.
 *
 * A card cell spans the band radially, in **band units**: `CARD_UNITS` from the inner rim to
 * the outer rim, whatever the band's size in pixels. Its tangential size is the card's own
 * (`cardUnits`), and the ring gives it the same pixels per unit along the arc as across the
 * band, so text is not stretched (B14). Layout of a cell, in units from the inner rim:
 *
 * ```
 * 0 ── 10   bezel (the shader's shading; the tick layer's comb)
 * 14 ─ 124  header "// package / module", rows of "line  code", the neighbour dots
 * 126 ─ 149 right-aligned labels: counts and changes
 * 151 ─ 160 outer comb (tick layer)
 * ```
 */

/** Radial size of a card in band units. */
export const CARD_UNITS = 160;
/** Device pixels per unit at most; lowered when the cards do not fit the atlas. */
export const ATLAS_SCALE = 2;
const MIN_SCALE = 0.75;
/** WebGL 2 guarantees textures of at least 2048 px per side. */
export const ATLAS_MAX = 2048;

const HEADER_Y = 4;
const HEADER_FONT = 5.4;
const ROW_Y = 14;
export const ROW_PITCH = 6;
const ROW_FONT = 5;
const NUM_RIGHT = 30;
const CODE_X = 34;
const TEXT_RIGHT = 124;
const META_RIGHT = 149;
export const DOT_COLS = 16;
const DOT_PITCH = 4;
const DOT_SIZE = 1.7;
const BOTTOM_PAD = 4;
const FONT_FAMILY = '"JetBrains Mono Variable", ui-monospace, monospace';

/** One row of a card: a dim number column (a line number, or blank) and the code. */
export interface CardRow {
  readonly num: string;
  readonly text: string;
  /** Rows of changed symbols are drawn in `--flag`. */
  readonly flag: boolean;
}

/** What the atlas draws for a card. Plain data, so it can be posted to the worker. */
export interface AtlasCard {
  readonly header: string;
  readonly rows: readonly CardRow[];
  /** Lit cells of the neighbour fingerprint (indices into a DOT_COLS-wide grid). */
  readonly dots: readonly number[];
  /** Rows of the fingerprint grid; 0 = no grid. */
  readonly dotRows: number;
  /** Right-aligned labels, one per row slot (blank = none). */
  readonly meta: readonly string[];
}

/** A card's tangential size in band units: header, rows, dots and padding. */
export function cardUnits(card: AtlasCard): number {
  const dots = card.dotRows > 0 ? 2 + card.dotRows * DOT_PITCH : 0;
  return Math.max(30, ROW_Y + card.rows.length * ROW_PITCH + dots + BOTTOM_PAD);
}

export interface CellRect {
  /** Texture coordinates, 0–1, with v = 0 at the top of the atlas. */
  readonly u0: number;
  readonly v0: number;
  readonly u1: number;
  readonly v1: number;
}

export interface AtlasLayout {
  readonly width: number;
  readonly height: number;
  /** Device pixels per band unit. */
  readonly scale: number;
  readonly cells: readonly CellRect[];
  /** Device-pixel origin of each cell. */
  readonly origins: readonly (readonly [number, number])[];
}

/**
 * Packs cells of the given tangential sizes (band units) into columns, at the largest scale
 * up to `ATLAS_SCALE` at which they fit a 2048 px texture. The atlas's v runs along the card
 * (tangentially) and u across the band.
 */
export function atlasLayout(units: readonly number[]): AtlasLayout {
  for (let scale = ATLAS_SCALE; scale >= MIN_SCALE; scale -= 0.25) {
    const columnW = Math.ceil(CARD_UNITS * scale);
    const columns = Math.floor(ATLAS_MAX / columnW);
    const origins: [number, number][] = [];
    let column = 0;
    let y = 0;
    let height = 0;
    let fits = true;
    for (const u of units) {
      const h = Math.ceil(u * scale);
      if (y + h > ATLAS_MAX) {
        column++;
        y = 0;
      }
      if (column >= columns || h > ATLAS_MAX) {
        fits = false;
        break;
      }
      origins.push([column * columnW, y]);
      y += h;
      height = Math.max(height, y);
    }
    if (!fits) continue;
    const width = Math.max(1, Math.min(ATLAS_MAX, (column + 1) * columnW));
    height = Math.max(1, height);
    const cells = units.map((u, i) => {
      const [x, y0] = origins[i] as [number, number];
      return {
        u0: x / width,
        v0: y0 / height,
        u1: (x + CARD_UNITS * scale) / width,
        v1: (y0 + u * scale) / height,
      };
    });
    return { width, height, scale, cells, origins };
  }
  throw new RangeError(`${units.length} cards do not fit a ${ATLAS_MAX} px atlas`);
}

/** The drawing surface the atlas needs: a subset of CanvasRenderingContext2D. */
export interface TextSurface {
  font: string;
  fillStyle: string | CanvasGradient | CanvasPattern;
  textBaseline: CanvasTextBaseline;
  textAlign: CanvasTextAlign;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number, maxWidth?: number): void;
  measureText(text: string): { width: number };
}

/**
 * Ink on transparent. Plain ink is white; changed rows are pure red, which the card shader reads
 * as `--flag` (it compares green to red, so it works with and without premultiplied alpha).
 */
const INK = (alpha: number) => `rgba(255,255,255,${alpha})`;
const FLAG_INK = "rgba(255,0,0,0.95)";

export function drawAtlas(
  surface: TextSurface,
  layout: AtlasLayout,
  cards: readonly AtlasCard[],
): void {
  const s = layout.scale;
  surface.clearRect(0, 0, layout.width, layout.height);
  surface.textBaseline = "top";
  cards.forEach((card, i) => {
    const [ox, oy] = layout.origins[i] as readonly [number, number];
    const x = (units: number) => ox + units * s;
    const y = (units: number) => oy + units * s;

    // Header and the rule after it, like the reference's "// packet / buffer".
    surface.textAlign = "left";
    surface.font = `600 ${HEADER_FONT * s}px ${FONT_FAMILY}`;
    surface.fillStyle = INK(0.95);
    surface.fillText(card.header, x(14), y(HEADER_Y), (TEXT_RIGHT - 14) * s);
    const ruleFrom = Math.min(TEXT_RIGHT, 14 + surface.measureText(card.header).width / s + 3);
    surface.fillStyle = INK(0.3);
    surface.fillRect(
      x(ruleFrom),
      y(HEADER_Y + 2.6),
      (META_RIGHT - ruleFrom) * s,
      Math.max(1, 0.5 * s),
    );
    // A thin vertical rule down the number column.
    surface.fillRect(x(12), y(ROW_Y), Math.max(1, 0.4 * s), card.rows.length * ROW_PITCH * s);

    surface.font = `${ROW_FONT * s}px ${FONT_FAMILY}`;
    card.rows.forEach((row, j) => {
      const top = y(ROW_Y + j * ROW_PITCH);
      surface.textAlign = "right";
      surface.fillStyle = INK(0.42);
      if (row.num !== "") surface.fillText(row.num, x(NUM_RIGHT), top);
      surface.textAlign = "left";
      surface.fillStyle = row.flag ? FLAG_INK : INK(0.82);
      surface.fillText(row.text, x(CODE_X), top, (TEXT_RIGHT - CODE_X) * s);
    });

    // The neighbour fingerprint: dim dots, lit where the file connects.
    if (card.dotRows > 0) {
      const top = ROW_Y + card.rows.length * ROW_PITCH + 2;
      const lit = new Set(card.dots);
      for (let d = 0; d < DOT_COLS * card.dotRows; d++) {
        const cx = CODE_X + (d % DOT_COLS) * DOT_PITCH;
        const cy = top + Math.floor(d / DOT_COLS) * DOT_PITCH;
        surface.fillStyle = lit.has(d) ? INK(0.92) : INK(0.16);
        surface.fillRect(x(cx), y(cy), DOT_SIZE * s, DOT_SIZE * s);
      }
    }

    // Labels on the outer column, every other row.
    surface.textAlign = "right";
    surface.font = `${ROW_FONT * s}px ${FONT_FAMILY}`;
    surface.fillStyle = INK(0.6);
    card.meta.forEach((label, j) => {
      if (label !== "") surface.fillText(label, x(META_RIGHT), y(ROW_Y + j * 2 * ROW_PITCH));
    });
  });
}
