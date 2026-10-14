/**
 * Execution (DESIGN.md panel 2): two lanes, BASE and HEAD. A running test is a particle moving
 * left to right; a finished one settles on the right as a dot coloured by outcome. Positions
 * are pure functions of the run's events, `t` and the motion settings, so scrubbing is exact.
 * The travel time constant is wall-clock; under reduced motion running tests hold still.
 *
 * The BASE lane also carries the repeat base run (A′, `base_repeat`), which measures noise. Its
 * particles are dimmer and its counts are shown separately, so BASE and HEAD stay comparable.
 */
import type { Signal } from "@preact/signals";
import type { Side } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../model/cockpit";
import type { TestRun } from "../model/runs";
import { NORMAL_MOTION } from "../motion/motion";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { font } from "./text";

export type ExecutionSides = "base" | "head" | "both";
export type ParticleKind = "running" | "passed" | "failed" | "skipped";

export interface Particle {
  /** 0–1 across the lane. */
  readonly x: number;
  /** 0–1 down the lane. */
  readonly y: number;
  readonly kind: ParticleKind;
  /** Whether the run is the repeat base run (A′). */
  readonly repeat: boolean;
}

export interface LaneCounts {
  readonly run: number;
  readonly failed: number;
}

export interface Lane {
  readonly side: "base" | "head";
  readonly particles: readonly Particle[];
  readonly counts: LaneCounts;
  /** The repeat base run (A′); BASE lane only. */
  readonly repeat: LaneCounts | null;
}

export interface ExecutionView {
  readonly lanes: readonly Lane[];
}

/** Running particles approach the settle line with this time constant (ms). */
const TRAVEL_MS = 350;
const RUN_FROM = 0.04;
const RUN_SPAN = 0.6;
const SETTLE_FROM = 0.7;
const SETTLE_SPAN = 0.28;
const SETTLE_ROWS = 8;
/** Running particles are redrawn at about 30 fps. */
const FRAME_MS = 33;

const laneOf = (side: Side): "base" | "head" => (side === "head" ? "head" : "base");

/** How a run is drawn as of `cursor`: running, or settled by outcome. */
export function kindOf(run: TestRun, cursor: number): ParticleKind {
  if (run.finished < 0 || run.finished >= cursor) return "running";
  if (run.outcome === "passed" || run.outcome === "xfailed") return "passed";
  if (run.outcome === "skipped") return "skipped";
  return "failed";
}

export function executionPanel(
  model: CockpitModel,
  sides: Signal<ExecutionSides>,
): Panel<ExecutionView> {
  const shown = (): readonly ("base" | "head")[] =>
    sides.value === "both" ? ["base", "head"] : [sides.value];
  return {
    id: "execution",
    version(t, cursor, motion = NORMAL_MOTION) {
      // Every run has one start and one finish, so tests are running while starts lead.
      const started = model.kinds.count("test.started", cursor);
      const finished = model.kinds.count("test.finished", cursor);
      const mode = sides.value === "both" ? 0 : sides.value === "base" ? 1 : 2;
      const moving = started > finished && !motion.reduced;
      const phase = moving ? Math.floor(t / (FRAME_MS * motion.speed)) : 0;
      return versionOf((started + finished) * 3 + mode, phase);
    },
    view(t, cursor, motion = NORMAL_MOTION) {
      // Running particles move in steps of the version's phase, so equal versions draw alike.
      const frame = FRAME_MS * motion.speed;
      const shownAt = Math.floor(t / frame) * frame;
      const lanes = shown().map((side): Lane => {
        const particles: Particle[] = [];
        let settled = 0;
        for (const r of model.tests.runs) {
          if (r.started >= cursor) break;
          if (laneOf(r.side) === side && kindOf(r, cursor) !== "running") settled++;
        }
        const columns = Math.max(1, Math.ceil(settled / SETTLE_ROWS));
        const main = { run: 0, failed: 0 };
        const again = { run: 0, failed: 0 };
        let s = 0;
        for (const r of model.tests.runs) {
          if (r.started >= cursor) break;
          if (laneOf(r.side) !== side) continue;
          const repeat = r.side === "base_repeat";
          const counts = repeat ? again : main;
          counts.run++;
          const kind = kindOf(r, cursor);
          const jitter = 0.08 + 0.84 * (hash32(`${r.side}|${r.test}`) / 4294967296);
          if (kind === "running") {
            const elapsed =
              Math.max(0, shownAt - (model.store.time[r.started] as number)) / motion.speed;
            particles.push({
              x: motion.reduced
                ? RUN_FROM + RUN_SPAN / 2
                : RUN_FROM + RUN_SPAN * (1 - Math.exp(-elapsed / TRAVEL_MS)),
              y: jitter,
              kind,
              repeat,
            });
          } else {
            if (kind === "failed") counts.failed++;
            const column = Math.floor(s / SETTLE_ROWS);
            const row = s % SETTLE_ROWS;
            particles.push({
              x: SETTLE_FROM + (SETTLE_SPAN * (column + 0.5)) / columns,
              y: (row + 0.5) / SETTLE_ROWS,
              kind,
              repeat,
            });
            s++;
          }
        }
        return { side, particles, counts: main, repeat: side === "base" ? again : null };
      });
      return { lanes };
    },
    draw(ctx, view, size) {
      const laneH = size.h / Math.max(1, view.lanes.length);
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      view.lanes.forEach((lane, i) => {
        const top = i * laneH;
        ctx.globalAlpha = 1;
        ctx.font = font(8);
        ctx.fillStyle = COLOR.dim;
        const label = (c: LaneCounts) =>
          `${c.run} run${c.failed > 0 ? ` · ${c.failed} failed` : ""}`;
        ctx.fillText(
          `${lane.side.toUpperCase()} · ${label(lane.counts)}${lane.repeat === null || lane.repeat.run === 0 ? "" : `   A′ · ${label(lane.repeat)}`}`,
          0,
          top + 2,
        );
        if (i > 0) {
          ctx.fillStyle = COLOR.border;
          ctx.fillRect(0, top, size.w, 1);
        }
        const bodyTop = top + 14;
        const bodyH = laneH - 18;
        // The settle line between running and finished tests.
        ctx.fillStyle = COLOR.faint;
        ctx.fillRect(size.w * (SETTLE_FROM - 0.02), bodyTop, 1, bodyH);
        for (const p of lane.particles) {
          const x = p.x * size.w;
          const y = bodyTop + p.y * bodyH;
          const dim = p.repeat ? 0.5 : 1;
          if (p.kind === "running") {
            ctx.globalAlpha = 0.85 * dim;
            ctx.fillStyle = COLOR.hot;
            ctx.fillRect(x - 6, y, 6, 1.5); // a short dash: a particle in motion
            continue;
          }
          ctx.globalAlpha = (p.kind === "passed" ? 0.75 : 1) * dim;
          ctx.fillStyle =
            p.kind === "failed" ? COLOR.flag : p.kind === "skipped" ? COLOR.faint : COLOR.text;
          ctx.fillRect(x - 1.25, y - 1.25, 2.5, 2.5);
        }
      });
      ctx.globalAlpha = 1;
    },
  };
}
