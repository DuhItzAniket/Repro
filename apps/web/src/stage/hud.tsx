/**
 * Perf HUD (B04): frame-interval and CPU percentiles, draw calls, instances per layer, DPR and
 * GPU. It is refreshed a few times per second from the host's statistics, never per frame.
 */
import type { Signal } from "@preact/signals";
import type { StageHost, StageInfo } from "./host";
import type { FrameReport } from "./stats";

export interface HudSnapshot {
  readonly gpu: string;
  readonly dpr: number;
  readonly drawCalls: number;
  readonly instances: readonly [string, number][];
  readonly interval: FrameReport["interval"];
  readonly cpu: FrameReport["cpu"];
  readonly frames: number;
}

export function snapshot(info: StageInfo, report: FrameReport): HudSnapshot {
  return {
    gpu: info.gpu,
    dpr: info.dpr,
    drawCalls: info.drawCalls,
    instances: Object.entries(info.instances),
    interval: { ...report.interval },
    cpu: { ...report.cpu },
    frames: report.frames,
  };
}

/** Publishes a snapshot of the host's statistics into `target` every `everyMs`. Returns a stop function. */
export function pollHud(
  host: StageHost,
  target: Signal<HudSnapshot | null>,
  everyMs = 250,
): () => void {
  const timer = setInterval(() => {
    target.value = snapshot(host.info, host.stats.summarise());
  }, everyMs);
  return () => clearInterval(timer);
}

const ms = (value: number) => (Number.isNaN(value) ? "–" : value.toFixed(1));

export function PerfHud({ hud }: { hud: Signal<HudSnapshot | null> }) {
  const s = hud.value;
  if (s === null) return null;
  const fps = Number.isNaN(s.interval.p50) ? "–" : (1000 / s.interval.p50).toFixed(0);
  const total = s.instances.reduce((sum, [, n]) => sum + n, 0);
  return (
    <aside class="perf-hud" aria-label="Performance">
      <div>{`${fps} fps · dpr ${s.dpr} · ${s.drawCalls} draws · ${total} inst`}</div>
      <div>{`frame p50 ${ms(s.interval.p50)} p95 ${ms(s.interval.p95)} p99 ${ms(s.interval.p99)} ms`}</div>
      <div>{`cpu   p50 ${ms(s.cpu.p50)} p95 ${ms(s.cpu.p95)} p99 ${ms(s.cpu.p99)} ms`}</div>
      <div>{s.instances.map(([name, n]) => `${name} ${n}`).join(" · ")}</div>
      <div class="perf-hud-gpu">{s.gpu}</div>
    </aside>
  );
}
