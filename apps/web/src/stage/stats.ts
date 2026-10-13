/**
 * Frame-time statistics for the perf HUD and the adaptive DPR controller. A fixed ring buffer
 * and a preallocated scratch array, so recording a frame never allocates (DESIGN.md
 * "Performance budget").
 */

export interface Percentiles {
  p50: number;
  p95: number;
  p99: number;
}

export class RollingSamples {
  private readonly ring: Float64Array;
  private readonly scratch: Float64Array;
  private next = 0;
  private filled = 0;

  constructor(readonly capacity = 240) {
    this.ring = new Float64Array(capacity);
    this.scratch = new Float64Array(capacity);
  }

  get count(): number {
    return this.filled;
  }

  push(value: number): void {
    this.ring[this.next] = value;
    this.next = (this.next + 1) % this.capacity;
    if (this.filled < this.capacity) this.filled++;
  }

  clear(): void {
    this.next = 0;
    this.filled = 0;
  }

  /** Nearest-rank percentiles of the samples held, written into `out` (NaN when empty). */
  percentiles(out: Percentiles): Percentiles {
    const n = this.filled;
    if (n === 0) {
      out.p50 = Number.NaN;
      out.p95 = Number.NaN;
      out.p99 = Number.NaN;
      return out;
    }
    this.scratch.set(this.ring);
    // Unused slots sort to the end, so the first n entries are the samples in order.
    for (let i = n; i < this.capacity; i++) this.scratch[i] = Number.POSITIVE_INFINITY;
    this.scratch.sort();
    const rank = (p: number) =>
      this.scratch[Math.min(n - 1, Math.ceil((p / 100) * n) - 1)] as number;
    out.p50 = rank(50);
    out.p95 = rank(95);
    out.p99 = rank(99);
    return out;
  }
}

export interface FrameReport {
  /** Time between consecutive frames (ms): shows dropped frames, whatever their cause. */
  interval: Percentiles;
  /** Main-thread time spent in the stage's own frame work (update + render submission). */
  cpu: Percentiles;
  frames: number;
}

export class FrameStats {
  private readonly intervals: RollingSamples;
  private readonly cpu: RollingSamples;
  private lastStart = Number.NaN;
  private total = 0;
  readonly report: FrameReport = {
    interval: { p50: Number.NaN, p95: Number.NaN, p99: Number.NaN },
    cpu: { p50: Number.NaN, p95: Number.NaN, p99: Number.NaN },
    frames: 0,
  };

  constructor(window = 240) {
    this.intervals = new RollingSamples(window);
    this.cpu = new RollingSamples(window);
  }

  /** Records one frame that started at `start` and spent `cpuMs` in stage work. */
  record(start: number, cpuMs: number): void {
    if (!Number.isNaN(this.lastStart)) this.intervals.push(start - this.lastStart);
    this.lastStart = start;
    this.cpu.push(cpuMs);
    this.total++;
  }

  /** Recomputes `report` (call a few times per second, not every frame). */
  summarise(): FrameReport {
    this.intervals.percentiles(this.report.interval);
    this.cpu.percentiles(this.report.cpu);
    this.report.frames = this.total;
    return this.report;
  }

  intervalPercentiles(out: Percentiles): Percentiles {
    return this.intervals.percentiles(out);
  }

  reset(): void {
    this.intervals.clear();
    this.cpu.clear();
    this.lastStart = Number.NaN;
    this.total = 0;
  }
}
