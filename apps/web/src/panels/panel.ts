/**
 * The panel contract (ARCHITECTURE §13, IMPLEMENTATION_PLAN §5): a panel is a pure view model
 * plus a pure `draw(ctx, view, size, t)` on a Canvas 2D context. The host draws only when the
 * panel's `version` changes (its `isDirty`). Panels can therefore move to an OffscreenCanvas
 * worker later, and they are tested by recording their draw calls (B08).
 */

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

export interface Panel<V> {
  readonly id: string;
  /**
   * A number that changes whenever the drawing at (t, cursor) would change: usually the cursor,
   * plus an animation phase while something on the panel moves. Equal versions are never redrawn.
   */
  version(t: number, cursor: number): number;
  view(t: number, cursor: number): V;
  draw(ctx: Ctx2D, view: V, size: PanelSize, t: number): void;
}

/** Combines a cursor and a small animation phase into one version number. */
export const versionOf = (cursor: number, phase = 0): number => cursor * 4096 + (phase % 4096);

/** Draws one panel into its canvas at the device pixel ratio, only when dirty. */
export class PanelHost<V> {
  private drawn = Number.NaN;
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
  resize(w: number, h: number, dpr: number): void {
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

  /** Redraws if the panel's version changed; returns whether it drew. */
  frame(t: number, cursor: number): boolean {
    const ctx = this.context;
    if (ctx === null || this.size.w === 0 || this.size.h === 0) return false;
    const version = this.panel.version(t, cursor);
    if (version === this.drawn) return false;
    this.drawn = version;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, this.size.w, this.size.h);
    this.panel.draw(ctx, this.panel.view(t, cursor), this.size, t);
    return true;
  }
}
