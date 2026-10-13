/**
 * Adaptive device-pixel ratio for the stage (DESIGN.md "Performance budget"): capped at 2,
 * stepping down when frames are visibly dropped: the window's 95th-percentile interval exceeds
 * 1.5× the 60 Hz budget, which means more than 5% of frames took two refreshes. Plain
 * interval jitter (measured: p95 ≈ 18 ms on an idle stage in an embedded Chromium) must not
 * trigger it.
 *
 * Frame intervals are locked to the display's refresh, so "how much headroom is left" cannot be
 * read from them. Instead, after a run of windows within budget, the controller probes one step
 * up. If that probe immediately misses the budget, it steps back down and waits twice as long
 * before probing again (capped), so it settles instead of oscillating.
 */
import { type Percentiles, RollingSamples } from "./stats";

export const FRAME_BUDGET_MS = 1000 / 60;
/** p95 above this many budgets counts as dropping frames. */
export const MISS_FACTOR = 1.5;

/** Descending DPR levels for a display: its own ratio (capped at 2), then 1.5 and 1 below it. */
export function dprLevels(device: number): number[] {
  const cap = Math.max(1, Math.min(2, device));
  return [cap, ...[1.5, 1].filter((level) => level < cap)];
}

export interface DprOptions {
  /** The display's ratio (`window.devicePixelRatio`). */
  readonly device: number;
  /** Frames per evaluation window. */
  readonly window?: number;
  /** Consecutive windows within budget before probing one step up. */
  readonly recoverAfter?: number;
  /** Frames ignored at start (loading and first layout are not representative). */
  readonly warmup?: number;
}

const MAX_BACKOFF = 64;

export class AdaptiveDpr {
  private readonly levels: number[];
  private readonly samples: RollingSamples;
  private readonly scratch: Percentiles = { p50: 0, p95: 0, p99: 0 };
  private readonly windowSize: number;
  private recoverAfter: number;
  private warmup: number;
  private level = 0;
  private frames = 0;
  private comfortable = 0;
  /** True during the first window after stepping up. */
  private probing = false;

  constructor(options: DprOptions) {
    this.levels = dprLevels(options.device);
    this.windowSize = options.window ?? 90;
    this.recoverAfter = options.recoverAfter ?? 8;
    this.warmup = options.warmup ?? 60;
    this.samples = new RollingSamples(this.windowSize);
  }

  get dpr(): number {
    return this.levels[this.level] as number;
  }

  /** Feeds one frame interval (ms). Returns true when the DPR changed. */
  sample(intervalMs: number): boolean {
    if (this.warmup > 0) {
      this.warmup--;
      return false;
    }
    this.samples.push(intervalMs);
    if (++this.frames < this.windowSize) return false;
    this.frames = 0;
    const { p95 } = this.samples.percentiles(this.scratch);
    this.samples.clear();
    const probing = this.probing;
    this.probing = false;
    if (p95 > FRAME_BUDGET_MS * MISS_FACTOR) {
      this.comfortable = 0;
      if (probing) this.recoverAfter = Math.min(MAX_BACKOFF, this.recoverAfter * 2);
      if (this.level === this.levels.length - 1) return false;
      this.level++;
      return true;
    }
    if (this.level > 0 && ++this.comfortable >= this.recoverAfter) {
      this.comfortable = 0;
      this.level--;
      this.probing = true;
      return true;
    }
    return false;
  }
}
