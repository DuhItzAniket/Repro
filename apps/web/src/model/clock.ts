/**
 * The presentation clock: which moment of the run the cockpit is showing (ARCHITECTURE §13).
 *
 * - **replay** advances at ×0.5/×1/×4/×16 and stops at the end of the data it has.
 * - **live** follows wall-clock time from the newest event (×1).
 * - **pause** freezes the presentation only. Ingestion keeps running (WCAG 2.2.2, ADR-0011).
 *
 * Wall-clock time is injected (`now`), so the clock is deterministic under test.
 */

export const SPEEDS = [0.5, 1, 4, 16] as const;
export type Speed = (typeof SPEEDS)[number];
export type ClockMode = "live" | "replay";

export interface ClockStatus {
  readonly mode: ClockMode;
  readonly speed: Speed;
  readonly paused: boolean;
  /** Presentation time in ms since the run started. */
  readonly t: number;
  /** Latest presentation time with data. */
  readonly end: number;
}

export class PresentationClock {
  private anchorWall: number;
  private anchorT = 0;
  private _mode: ClockMode = "replay";
  private _speed: Speed = 1;
  private _paused = true;
  private _end = 0;

  constructor(private readonly now: () => number) {
    this.anchorWall = now();
  }

  get mode(): ClockMode {
    return this._mode;
  }

  get speed(): Speed {
    return this._speed;
  }

  get paused(): boolean {
    return this._paused;
  }

  get end(): number {
    return this._end;
  }

  /** Presentation time now. Replay never runs past the data; it waits at the end. */
  time(): number {
    if (this._paused) return this.anchorT;
    const wall = this.now();
    const rate = this._mode === "live" ? 1 : this._speed;
    const t = this.anchorT + (wall - this.anchorWall) * rate;
    if (this._mode === "replay" && t > this._end) {
      // Wait at the end; re-anchor so later data does not make the clock jump ahead.
      this.anchorT = this._end;
      this.anchorWall = wall;
      return this._end;
    }
    return t;
  }

  status(): ClockStatus {
    return {
      mode: this._mode,
      speed: this._speed,
      paused: this._paused,
      t: this.time(),
      end: this._end,
    };
  }

  /** Tells the clock how far the data reaches (call after ingesting). */
  setEnd(end: number): void {
    this._end = Math.max(this._end, end);
  }

  private reanchor(t: number): void {
    this.anchorT = t;
    this.anchorWall = this.now();
  }

  play(): void {
    if (!this._paused) return;
    this.reanchor(this.anchorT);
    this._paused = false;
  }

  /** Global pause (Space). Leaving live this way resumes as a ×1 replay behind the live edge. */
  pause(): void {
    if (this._paused) return;
    this.reanchor(this.time());
    this._paused = true;
    if (this._mode === "live") {
      this._mode = "replay";
      this._speed = 1;
    }
  }

  toggle(): void {
    if (this._paused) this.play();
    else this.pause();
  }

  setSpeed(speed: Speed): void {
    this.reanchor(this.time());
    this._speed = speed;
    this._mode = "replay";
  }

  /** Jumps to `t`, clamped to the data. Keeps the play/pause state. */
  seek(t: number): void {
    this.reanchor(Math.min(Math.max(0, t), this._end));
    this._mode = "replay";
  }

  /** Follows the newest data at ×1 (and resumes if paused). */
  goLive(): void {
    this.reanchor(this._end);
    this._mode = "live";
    this._paused = false;
  }
}
