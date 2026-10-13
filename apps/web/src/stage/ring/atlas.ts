/**
 * The card atlas: every card's text drawn once into one texture, so the whole ring is a
 * single instanced draw call (ADR-0008: "ring cards from a Canvas-2D atlas"). Packing is a pure
 * function; drawing takes any Canvas-2D context, the worker's OffscreenCanvas or the main
 * thread's fallback.
 */

/** Cell sizes in CSS pixels; the atlas is drawn at `ATLAS_SCALE` device pixels per CSS pixel. */
export const CONTENT_CELL = { w: 120, h: 40 } as const;
export const META_CELL = { w: 72, h: 40 } as const;
export const ATLAS_SCALE = 1.5;
/** WebGL 2 guarantees textures of at least 2048 px per side. */
export const ATLAS_MAX = 2048;
const LINE_HEIGHT = 4;
const FONT_SIZE = 3.4;

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
  readonly content: readonly CellRect[];
  readonly meta: readonly CellRect[];
  /** Device-pixel origin of each pair of cells. */
  readonly origins: readonly (readonly [number, number])[];
}

export interface AtlasCard {
  readonly lines: readonly string[];
  readonly meta: readonly string[];
}

export function atlasLayout(count: number): AtlasLayout {
  const pairW = (CONTENT_CELL.w + META_CELL.w) * ATLAS_SCALE;
  const cellH = CONTENT_CELL.h * ATLAS_SCALE;
  const perRow = Math.max(1, Math.floor(ATLAS_MAX / pairW));
  const rows = Math.max(1, Math.ceil(count / perRow));
  const width = Math.min(ATLAS_MAX, Math.ceil(perRow * pairW));
  const height = Math.ceil(rows * cellH);
  if (height > ATLAS_MAX) throw new RangeError(`${count} cards do not fit a ${ATLAS_MAX} px atlas`);
  const content: CellRect[] = [];
  const meta: CellRect[] = [];
  const origins: (readonly [number, number])[] = [];
  for (let i = 0; i < count; i++) {
    const x = (i % perRow) * pairW;
    const y = Math.floor(i / perRow) * cellH;
    const contentW = CONTENT_CELL.w * ATLAS_SCALE;
    origins.push([x, y]);
    content.push({
      u0: x / width,
      v0: y / height,
      u1: (x + contentW) / width,
      v1: (y + cellH) / height,
    });
    meta.push({
      u0: (x + contentW) / width,
      v0: y / height,
      u1: (x + pairW) / width,
      v1: (y + cellH) / height,
    });
  }
  return { width, height, content, meta, origins };
}

/** The drawing surface the atlas needs: a subset of CanvasRenderingContext2D. */
export interface TextSurface {
  font: string;
  fillStyle: string | CanvasGradient | CanvasPattern;
  textBaseline: CanvasTextBaseline;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number, maxWidth?: number): void;
}

/** White text on transparent; the card shader supplies background and tint. */
export function drawAtlas(
  surface: TextSurface,
  layout: AtlasLayout,
  cards: readonly AtlasCard[],
): void {
  surface.clearRect(0, 0, layout.width, layout.height);
  surface.fillStyle = "#ffffff";
  surface.textBaseline = "top";
  surface.font = `${FONT_SIZE * ATLAS_SCALE}px "JetBrains Mono Variable", ui-monospace, monospace`;
  const pad = 2 * ATLAS_SCALE;
  const maxContent = Math.floor((CONTENT_CELL.h - 4) / LINE_HEIGHT);
  cards.forEach((card, i) => {
    const [x, y] = layout.origins[i] as readonly [number, number];
    card.lines.slice(0, maxContent).forEach((line, j) => {
      surface.fillText(
        line,
        x + pad,
        y + pad + j * LINE_HEIGHT * ATLAS_SCALE,
        CONTENT_CELL.w * ATLAS_SCALE - 2 * pad,
      );
    });
    const metaX = x + CONTENT_CELL.w * ATLAS_SCALE;
    card.meta.forEach((line, j) => {
      surface.fillText(
        line,
        metaX + pad,
        y + pad + j * LINE_HEIGHT * 2 * ATLAS_SCALE,
        META_CELL.w * ATLAS_SCALE - 2 * pad,
      );
    });
  });
}
