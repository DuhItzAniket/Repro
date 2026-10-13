/**
 * The panel contract (ARCHITECTURE §13, IMPLEMENTATION_PLAN §5): a panel is a pure view model
 * plus a pure `draw(ctx, view, size, t)` on a Canvas 2D context. The host draws only when the
 * panel's `version` or the motion settings change (its `isDirty`). Panels can therefore move to
 * an OffscreenCanvas worker later, and they are tested by recording their draw calls (B08).
 */
import { type Focus, focusKey } from "../focus/focus";
import { type Motion, motionKey, NORMAL_MOTION } from "../motion/motion";
import { COLOR } from "../styles/palette";

/** The Canvas 2D subset panels use: what a real context and the test recorder both provide. */
export interface Ctx2D {
  fillStyle: string | CanvasGradient | CanvasPattern;
  strokeStyle: string | CanvasGradient | CanvasPattern;
  font: string;
  textBaseline: CanvasTextBaseline;
  textAlign: CanvasTextAlign;
  globalAlpha: number;
  lineWidth: number;
  fillRect(x: number, y: number, w: number, h: number): void;
  strokeRect(x: number, y: number, w: number, h: number): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillText(text: string, x: number, y: number, maxWidth?: number): void;
  beginPath(): void;
  moveTo(x: number, y: number): void;
  lineTo(x: number, y: number): void;
  arc(x: number, y: number, r: number, start: number, end: number): void;
  stroke(): void;
  fill(): void;
  save(): void;
  restore(): void;
}

export interface PanelSize {
  readonly w: number;
  readonly h: number;
}

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

/**
 * Something on a panel the user can focus (B11): a row or a cell. Its rectangle is where it is
 * drawn, or null when it does not fit (the "+k more" line); the keyboard mirror lists it anyway.
 */
export interface PanelTarget {
  /** `focusKey(focus)`. */
  readonly key: string;
  readonly focus: Focus;
  /** Accessible name, e.g. "C3 refactor: flagged". */
  readonly label: string;
  readonly rect: Rect | null;
  /** Listed in the keyboard mirror. Cells are not; the drawer lists a row's cells. */
  readonly listed: boolean;
  /** Further columns when the mirror is a table (the first column is the label's button). */
  readonly cells?: readonly string[];
}

/** What a panel outlines: the focused item and the item the keyboard is on. */
export interface Highlight {
  readonly selected: string;
  readonly keyboard: string;
}

export const NO_HIGHLIGHT: Highlight = { selected: "", keyboard: "" };

/** A target for `focus`, drawn at `rect`. */
export const target = (
  focus: Focus,
  label: string,
  rect: Rect | null,
  listed = true,
  cells?: readonly string[],
): PanelTarget => ({
  key: focusKey(focus),
  focus,
  label,
  rect,
  listed,
  ...(cells === undefined ? {} : { cells }),
});

export interface Panel<V> {
  readonly id: string;
  /**
   * A number that changes whenever the drawing at (t, cursor) would change: usually the cursor,
   * plus an animation phase while something on the panel moves. Equal versions are never redrawn.
   * Animated panels take their wall-clock durations from `motion` (ADR-0011; default: normal).
   */
  version(t: number, cursor: number, motion?: Motion): number;
  view(t: number, cursor: number, motion?: Motion): V;
  draw(ctx: Ctx2D, view: V, size: PanelSize, t: number): void;
  /** The panel's focusable rows and cells at this size (B11). */
  targets?(view: V, size: PanelSize): readonly PanelTarget[];
}

/**
 * Largest canvas side in CSS pixels. If CSS ever stops constraining a panel canvas, its own
 * backing size would feed back through the ResizeObserver and grow without bound (seen once with
 * a stale dev-server stylesheet); the clamp keeps that from allocating a huge canvas.
 */
export const MAX_SIDE = 4096;

/** Animation phases per cursor before a version could repeat (2^26: weeks of 33 ms frames). */
const PHASES = 67_108_864;

/**
 * Combines a cursor and an animation phase into one version number. Exact for cursors below
 * 2^27, so equal versions mean equal (cursor, phase).
 */
export const versionOf = (cursor: number, phase = 0): number => cursor * PHASES + (phase % PHASES);

/** Draws one panel into its canvas at the device pixel ratio, only when dirty. */
export class PanelHost<V> {
  private drawn = Number.NaN;
  private drawnMotion = Number.NaN;
  private drawnSelected = "";
  private drawnKeyboard = "";
  private current: readonly PanelTarget[] = [];
  private currentKeys = "";
  /** Called when the panel's targets change (the keyboard mirror re-renders). */
  onTargets: ((targets: readonly PanelTarget[]) => void) | null = null;
  private size: PanelSize = { w: 0, h: 0 };
  private dpr = 1;
  private readonly context: CanvasRenderingContext2D | null;

  constructor(
    readonly panel: Panel<V>,
    private readonly canvas: HTMLCanvasElement,
  ) {
    this.context = canvas.getContext("2d");
  }

  /** Call when the canvas's CSS size or the display's pixel ratio changes. */
  resize(width: number, height: number, dpr: number): void {
    const w = Math.min(MAX_SIDE, Math.max(0, width));
    const h = Math.min(MAX_SIDE, Math.max(0, height));
    const ratio = Math.min(2, Math.max(1, dpr));
    if (w === this.size.w && h === this.size.h && ratio === this.dpr) return;
    this.size = { w, h };
    this.dpr = ratio;
    this.canvas.width = Math.max(1, Math.round(w * ratio));
    this.canvas.height = Math.max(1, Math.round(h * ratio));
    this.drawn = Number.NaN;
  }

  /** Forces the next frame to redraw (fonts loaded, theme changed). */
  invalidate(): void {
    this.drawn = Number.NaN;
  }

  /** The targets as last drawn. */
  get targets(): readonly PanelTarget[] {
    return this.current;
  }

  /** The drawn target under a point in panel CSS px, if any (the smallest wins: cells in rows). */
  hit(x: number, y: number): PanelTarget | null {
    let best: PanelTarget | null = null;
    for (const t of this.current) {
      const r = t.rect;
      if (r === null || x < r.x || y < r.y || x >= r.x + r.w || y >= r.y + r.h) continue;
      if (best === null || (best.rect as Rect).w * (best.rect as Rect).h > r.w * r.h) best = t;
    }
    return best;
  }

  /**
   * Redraws if the panel's version, the motion settings or the highlight changed; returns
   * whether it drew.
   */
  frame(
    t: number,
    cursor: number,
    motion: Motion = NORMAL_MOTION,
    highlight: Highlight = NO_HIGHLIGHT,
  ): boolean {
    const ctx = this.context;
    if (ctx === null || this.size.w === 0 || this.size.h === 0) return false;
    const version = this.panel.version(t, cursor, motion);
    const key = motionKey(motion);
    if (
      version === this.drawn &&
      key === this.drawnMotion &&
      highlight.selected === this.drawnSelected &&
      highlight.keyboard === this.drawnKeyboard
    )
      return false;
    this.drawn = version;
    this.drawnMotion = key;
    this.drawnSelected = highlight.selected;
    this.drawnKeyboard = highlight.keyboard;
    // Clear the whole backing store in device pixels: w × dpr is rarely an integer, and a clear
    // in CSS pixels would leave a stale sliver at the edges (and keep Chrome from discarding
    // the canvas's pending draw operations).
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    const view = this.panel.view(t, cursor, motion);
    this.panel.draw(ctx, view, this.size, t);
    const targets = this.panel.targets?.(view, this.size) ?? [];
    for (const target of targets) {
      const r = target.rect;
      if (r === null) continue;
      if (target.key === highlight.selected) {
        ctx.globalAlpha = 0.1;
        ctx.fillStyle = COLOR.hot;
        ctx.fillRect(r.x, r.y, r.w, r.h);
        ctx.globalAlpha = 1;
        ctx.strokeStyle = COLOR.dim;
        ctx.lineWidth = 1;
        ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
      }
      if (target.key === highlight.keyboard) {
        ctx.globalAlpha = 1;
        ctx.strokeStyle = COLOR.hot;
        ctx.lineWidth = 1;
        ctx.strokeRect(r.x - 0.5, r.y - 0.5, r.w + 1, r.h + 1);
      }
    }
    const keys = targets.map((t) => `${t.key}=${t.label}`).join("\n");
    this.current = targets;
    if (keys !== this.currentKeys) {
      this.currentKeys = keys;
      this.onTargets?.(targets);
    }
    return true;
  }
}
