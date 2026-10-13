/**
 * The stress benchmark (B04). Plays the busiest second of the stress run (10k edges, the
 * 3k-events-per-second burst) through the proxy layers at fixed device-pixel ratios, and
 * reports frame-interval and CPU percentiles per ratio. Method and results are recorded in
 * `docs/phases/B04-stage-foundation.md`.
 */
import type { CockpitModel } from "../model/cockpit";
import type { Ring } from "../shell/layout";
import { StageHost } from "../stage/host";
import type { StageLayer } from "../stage/layer";

export interface BenchCase {
  readonly dpr: number;
  readonly seconds: number;
}

export interface Summary {
  readonly p50: number;
  readonly p95: number;
  readonly p99: number;
  readonly max: number;
}

export interface BenchResult {
  readonly dpr: number;
  readonly css: { readonly width: number; readonly height: number };
  readonly frames: number;
  /** Frame-to-frame interval from requestAnimationFrame timestamps (ms). */
  readonly interval: Summary;
  /** Stage CPU time per frame: layer updates, uploads and the render call (ms). */
  readonly cpu: Summary;
  /** Share of frames whose interval exceeded 1.5× the 60 Hz budget (a visibly dropped frame). */
  readonly dropped: number;
  readonly drawCalls: number;
  /** Instances in the last frame per layer, plus the peak streak count while measuring. */
  readonly instances: Record<string, number>;
  /** Times the page was hidden while measuring (hidden pages throttle frames). */
  readonly hiddenDuringRun: number;
}

export interface BenchReport {
  readonly gpu: string;
  readonly userAgent: string;
  readonly devicePixelRatio: number;
  readonly burstAtMs: number;
  readonly results: BenchResult[];
}

function summarise(values: number[]): Summary {
  const sorted = [...values].sort((a, b) => a - b);
  const rank = (p: number) =>
    sorted[Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)] ?? Number.NaN;
  return { p50: rank(50), p95: rank(95), p99: rank(99), max: sorted.at(-1) ?? Number.NaN };
}

/** Start of the one-second window with the most execution events. */
export function busiestSecond(model: CockpitModel): number {
  const times: number[] = [];
  for (const kind of ["test.started", "test.finished", "trace.sample", "perf.sample"] as const) {
    for (const i of model.kinds.last(kind, model.store.length, Number.MAX_SAFE_INTEGER)) {
      times.push(model.store.time[i] as number);
    }
  }
  times.sort((a, b) => a - b);
  let best = 0;
  let at = 0;
  for (let i = 0, j = 0; i < times.length; i++) {
    while ((times[i] as number) - (times[j] as number) >= 1000) j++;
    if (i - j + 1 > best) {
      best = i - j + 1;
      at = times[j] as number;
    }
  }
  return at;
}

const nextFrame = () => new Promise<number>((resolve) => requestAnimationFrame(resolve));

/** Length of the looped window: the busiest second plus streak lifetimes on either side. */
export const BURST_LOOP_MS = 1500;

export async function runCase(
  canvas: HTMLCanvasElement,
  model: CockpitModel,
  layers: () => StageLayer[],
  size: { width: number; height: number; ring: Ring },
  start: number,
  bench: BenchCase,
  onFrame?: (host: StageHost) => void,
): Promise<{ result: BenchResult; gpu: string }> {
  const host = new StageHost(canvas, { devicePixelRatio: bench.dpr, fixedDpr: bench.dpr });
  for (const layer of layers()) host.add(layer);
  host.resize(size.width, size.height, size.ring);
  const intervals: number[] = [];
  const cpu: number[] = [];
  const peak = { streaks: 0 };
  let hidden = 0;
  const onVisibility = () => {
    if (document.visibilityState !== "visible") hidden++;
  };
  document.addEventListener("visibilitychange", onVisibility);
  // Warm-up: render the first burst frame for a second (shader compilation, first uploads),
  // then measure while looping the burst window, so every measured frame is under burst load.
  const warmupMs = 1000;
  let previous = await nextFrame();
  const first = previous;
  for (;;) {
    const now = await nextFrame();
    const elapsed = now - first;
    const measuring = elapsed >= warmupMs;
    const t = start + (measuring ? (elapsed - warmupMs) % BURST_LOOP_MS : 0);
    const cursor = model.store.cursorAt(t);
    const before = performance.now();
    host.frame(t, cursor);
    const after = performance.now();
    onFrame?.(host);
    if (measuring) {
      intervals.push(now - previous);
      cpu.push(after - before);
      peak.streaks = Math.max(peak.streaks, host.info.instances.streaks ?? 0);
    }
    previous = now;
    if (elapsed >= warmupMs + bench.seconds * 1000) break;
  }
  document.removeEventListener("visibilitychange", onVisibility);
  const result: BenchResult = {
    dpr: bench.dpr,
    css: { width: size.width, height: size.height },
    frames: intervals.length,
    interval: summarise(intervals),
    cpu: summarise(cpu),
    dropped: intervals.filter((v) => v > (1000 / 60) * 1.5).length / Math.max(1, intervals.length),
    drawCalls: host.info.drawCalls,
    instances: { ...host.info.instances, streaksPeak: peak.streaks },
    hiddenDuringRun: hidden,
  };
  const gpu = host.info.gpu;
  host.dispose();
  return { result, gpu };
}
