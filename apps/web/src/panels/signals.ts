/**
 * Signals (DESIGN.md panel 6): three live series on one time axis.
 * - PASS RATE: share of the last 8 finished HEAD tests that passed.
 * - BEHAVIOUR DRIFT: share of the last 16 base/head sample pairs (same test × symbol and call)
 *   whose result differs. Pairs whose base runs disagree (A ≠ A′) are left out as unstable.
 * - PERF Δ: head/base − 1 for each perf repetition measured on both sides.
 *
 * Ticks mark the checks that resolve each signal (P2F/F2P outcomes, behaviour diffs, perf
 * diffs). Each tick appears when its check arrives, at the point of the series it is about: the
 * test's HEAD finish, the cell's last HEAD sample, the test's last HEAD perf sample. The time
 * axis spans the series. Until the run completes the series are partial, which the footer says.
 */
import type { EventKind, ReproEvent } from "@repro/events";
import type { CockpitModel } from "../model/cockpit";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { font } from "./text";

export const PASS_WINDOW = 8;
export const DRIFT_WINDOW = 16;

export interface Point {
  readonly t: number;
  readonly v: number;
}

export interface Tick {
  readonly t: number;
  readonly flagged: boolean;
}

export interface Series {
  readonly label: string;
  readonly points: readonly Point[];
  readonly ticks: readonly Tick[];
  /** Value range for drawing; PERF Δ is symmetric around zero. */
  readonly min: number;
  readonly max: number;
  readonly latest: string;
}

export interface SignalsView {
  readonly series: readonly Series[];
  /** The shared time domain (ms since run start). */
  readonly from: number;
  readonly to: number;
}

const RELEVANT = [
  "test.finished",
  "trace.sample",
  "perf.sample",
  "diff.outcome",
  "diff.behaviour",
  "diff.perf",
] as const;

const pct = (v: number) => `${v >= 0 ? "+" : "−"}${Math.round(Math.abs(v) * 100)}%`;

export function signalsPanel(model: CockpitModel): Panel<SignalsView> {
  const timeOf = (i: number) => model.store.time[i] as number;
  return {
    id: "signals",
    version(_t, cursor) {
      let sum = 0;
      for (const kind of RELEVANT) sum += model.kinds.count(kind, cursor);
      return versionOf(sum);
    },
    view(_t, cursor) {
      // PASS RATE over HEAD finishes, in finish order.
      const finishes: { t: number; passed: boolean }[] = [];
      const headFinish = new Map<string, number>();
      for (const run of model.tests.runs) {
        if (run.started >= cursor) break;
        if (run.side !== "head" || run.finished < 0 || run.finished >= cursor) continue;
        headFinish.set(run.test, Math.max(headFinish.get(run.test) ?? 0, timeOf(run.finished)));
        finishes.push({
          t: timeOf(run.finished),
          passed: run.outcome === "passed" || run.outcome === "xfailed",
        });
      }
      finishes.sort((a, b) => a.t - b.t);
      const pass: Point[] = [];
      let passed = 0;
      finishes.forEach((f, i) => {
        passed += f.passed ? 1 : 0;
        const old = finishes[i - PASS_WINDOW];
        if (old?.passed) passed--;
        pass.push({ t: f.t, v: passed / Math.min(i + 1, PASS_WINDOW) });
      });

      // BEHAVIOUR DRIFT over base/head pairs, in the order they complete.
      const pairs = new Map<string, { base?: string; repeat?: string; head?: string }>();
      const compared: boolean[] = [];
      const drift: Point[] = [];
      const lastHeadSample = new Map<number, number>();
      let differing = 0;
      for (const s of model.observations.samples) {
        if (s.index >= cursor) break;
        if (s.side === "head") lastHeadSample.set(s.cell, timeOf(s.index));
        const key = `${s.cell}#${s.call}`;
        const pair = pairs.get(key) ?? {};
        const value = s.raised === null ? `${s.result}` : `raise ${s.raised}`;
        const complete = pair.base !== undefined && pair.head !== undefined;
        if (s.side === "base") pair.base = value;
        else if (s.side === "base_repeat") pair.repeat = value;
        else pair.head = value;
        pairs.set(key, pair);
        if (complete || pair.base === undefined || pair.head === undefined) continue;
        if (pair.repeat !== undefined && pair.repeat !== pair.base) continue; // unstable
        const differs = pair.base !== pair.head;
        compared.push(differs);
        differing += differs ? 1 : 0;
        if (compared.length > DRIFT_WINDOW && compared[compared.length - 1 - DRIFT_WINDOW])
          differing--;
        drift.push({ t: timeOf(s.index), v: differing / Math.min(compared.length, DRIFT_WINDOW) });
      }

      // PERF Δ per repetition measured on both sides.
      const reps = new Map<string, { base?: number; head?: number }>();
      const lastHeadPerf = new Map<string, number>();
      const perf: Point[] = [];
      for (const i of model.kinds.last("perf.sample", cursor, Number.MAX_SAFE_INTEGER)) {
        const event = model.store.event(i);
        if (event?.kind !== "perf.sample") continue;
        const { side, repetition, duration_ms: ms } = event.payload;
        if (side === "base_repeat") continue;
        const test = event.target?.test ?? "";
        if (side === "head") lastHeadPerf.set(test, timeOf(i));
        const key = `${test}|${repetition}`;
        const rep = reps.get(key) ?? {};
        const before = rep.base !== undefined && rep.head !== undefined;
        rep[side] = ms;
        reps.set(key, rep);
        if (!before && rep.base !== undefined && rep.head !== undefined && rep.base > 0)
          perf.push({ t: timeOf(i), v: rep.head / rep.base - 1 });
      }
      const perfSpan = perf.reduce((m, p) => Math.max(m, Math.abs(p.v)), 0.1);

      // Each check's tick sits at the data point it is about (undefined: no such point yet).
      const ticksOf = (kind: EventKind, at: (event: ReproEvent) => number | undefined): Tick[] => {
        const out: Tick[] = [];
        for (const i of model.kinds.last(kind, cursor, Number.MAX_SAFE_INTEGER)) {
          const event = model.store.event(i);
          const t = event === null ? undefined : at(event);
          if (t !== undefined) out.push({ t, flagged: event?.status === "fail" });
        }
        return out.sort((a, b) => a.t - b.t);
      };
      const outcomeTicks = ticksOf("diff.outcome", (event) =>
        event.kind === "diff.outcome" &&
        (event.payload.class === "P2F" || event.payload.class === "F2P")
          ? headFinish.get(event.target?.test ?? "")
          : undefined,
      );
      const driftTicks = ticksOf("diff.behaviour", (event) => {
        if (event.kind !== "diff.behaviour") return undefined;
        const cell = model.observations.cellOf(event.payload.test, event.payload.symbol_id);
        return cell === undefined ? undefined : lastHeadSample.get(cell);
      });
      const perfTicks = ticksOf("diff.perf", (event) => lastHeadPerf.get(event.target?.test ?? ""));
      const series: Series[] = [
        {
          label: "PASS RATE",
          points: pass,
          ticks: outcomeTicks,
          min: 0,
          max: 1,
          latest: pass.length === 0 ? "—" : `${(pass.at(-1) as Point).v.toFixed(2)}`,
        },
        {
          label: "DRIFT",
          points: drift,
          ticks: driftTicks,
          min: 0,
          max: 1,
          latest: drift.length === 0 ? "—" : `${(drift.at(-1) as Point).v.toFixed(2)}`,
        },
        {
          label: "PERF Δ",
          points: perf,
          ticks: perfTicks,
          min: -perfSpan,
          max: perfSpan,
          latest: perf.length === 0 ? "—" : pct((perf.at(-1) as Point).v),
        },
      ];
      let from = Number.POSITIVE_INFINITY;
      let to = Number.NEGATIVE_INFINITY;
      for (const s of series)
        for (const p of s.points) {
          from = Math.min(from, p.t);
          to = Math.max(to, p.t);
        }
      if (!Number.isFinite(from)) return { series, from: 0, to: 1 };
      return { series, from, to: Math.max(to, from + 1) };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      const labelW = 64;
      const plotW = Math.max(10, size.w - labelW);
      const bandH = size.h / view.series.length;
      const xOf = (t: number) => labelW + ((t - view.from) / (view.to - view.from)) * plotW;
      view.series.forEach((s, k) => {
        const top = k * bandH;
        const plotTop = top + 3;
        const plotH = Math.max(4, bandH - 8);
        const yOf = (v: number) => plotTop + plotH - ((v - s.min) / (s.max - s.min)) * plotH;
        ctx.globalAlpha = 1;
        ctx.font = font(8);
        ctx.fillStyle = COLOR.dim;
        ctx.fillText(s.label, 0, top + 2);
        ctx.fillStyle = COLOR.text;
        ctx.fillText(s.latest, 0, top + 12);
        // Baseline: zero for PERF Δ, the bottom otherwise.
        ctx.fillStyle = COLOR.border;
        ctx.fillRect(labelW, Math.round(yOf(s.min < 0 ? 0 : s.min)), plotW, 1);
        for (const tick of s.ticks) {
          ctx.fillStyle = tick.flagged ? COLOR.flag : COLOR.faint;
          ctx.fillRect(Math.round(xOf(tick.t)), plotTop, 1, plotH);
        }
        if (s.points.length === 0) return;
        // A polyline with at most one vertex per pixel column.
        ctx.strokeStyle = COLOR.text;
        ctx.lineWidth = 1;
        ctx.beginPath();
        let lastX = Number.NaN;
        s.points.forEach((p, i) => {
          const x = Math.round(xOf(p.t));
          const next = s.points[i + 1];
          if (next !== undefined && Math.round(xOf(next.t)) === x) return;
          const y = yOf(p.v);
          if (Number.isNaN(lastX)) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
          lastX = x;
        });
        ctx.stroke();
      });
      ctx.globalAlpha = 1;
    },
  };
}
