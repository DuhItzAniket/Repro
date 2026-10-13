/**
 * Change routes (DESIGN.md panel 5): one row per changed symbol, following it through the
 * pipeline as FILE · SYMBOL · TEST · CHECK. The cell a route has reached is a pill whose fill
 * shows that step's progress; earlier steps are plain text. Routes come from `ChangeIndex`
 * and checks relate by the change×check index's rule, so the two panels always agree.
 */

import { nameOf } from "../model/changes";
import { basename, relates, routeTests } from "../model/check-index";
import type { CockpitModel } from "../model/cockpit";
import type { CheckResult } from "../model/projections/checks";
import { COLOR } from "../styles/palette";
import { type Panel, type PanelSize, target, versionOf } from "./panel";
import { charsIn, clip, font } from "./text";

/** The pipeline steps, in column order. */
export const STEPS = ["file", "symbol", "test", "check"] as const;
export type Step = (typeof STEPS)[number];

export interface RouteRow {
  readonly file: string;
  readonly symbol: string;
  /** Full file path and symbol id (for focus). */
  readonly path: string;
  readonly symbolId: string;
  readonly tests: number;
  /** The furthest step reached (index into STEPS) and the progress within it, 0–1. */
  readonly step: number;
  readonly progress: number;
  /** Results of the checks on this route so far. */
  readonly checks: Readonly<Record<CheckResult, number>>;
}

export interface RoutesView {
  readonly rows: readonly RouteRow[];
}

const RELEVANT = [
  "symbol.changed",
  "test.selected",
  "test.finished",
  "diff.outcome",
  "diff.tests",
  "diff.behaviour",
  "diff.probe",
  "diff.api",
  "diff.deps",
  "diff.perf",
  "invariant.result",
  "verdict.issued",
  "stage.started",
  "stage.finished",
  "run.finished",
] as const;

/** The CHECK cell's words: the most urgent result first. */
export function checkLabel(checks: Readonly<Record<CheckResult, number>>): string {
  if (checks.flagged > 0) return `${checks.flagged} flagged`;
  if (checks.pending > 0) return `${checks.pending} pending`;
  if (checks.passed > 0) return `${checks.passed} passed`;
  if (checks.unassessed > 0) return `${checks.unassessed} unassessed`;
  return "—";
}

/** Row geometry shared by drawing and focus targets. */
export function routesGeometry(rows: number, size: PanelSize) {
  const colW = size.w / STEPS.length;
  const top = 12;
  // Rows shrink with the panel, down to 9 px (7 px text), like the reference's dense tables.
  const pitch = Math.max(9, Math.min(16, (size.h - top) / Math.max(1, rows)));
  const textSize = Math.max(7, Math.min(9, Math.floor(pitch - 2)));
  const fit = Math.max(1, Math.floor((size.h - top) / pitch));
  const shown = rows > fit ? fit - 1 : rows;
  return { colW, top, pitch, textSize, shown, overflow: rows > fit };
}

export function routesPanel(model: CockpitModel): Panel<RoutesView> {
  return {
    id: "routes",
    version(_t, cursor) {
      let sum = 0;
      for (const kind of RELEVANT) sum += model.kinds.count(kind, cursor);
      return versionOf(sum);
    },
    view(_t, cursor) {
      const state = model.folder.stateAt(cursor);
      const testsOf = routeTests(model.changes, cursor);
      // Tests that have finished on HEAD by now.
      const finished = new Set<string>();
      for (const run of model.tests.runs) {
        if (run.started >= cursor) break;
        if (run.side === "head" && run.finished >= 0 && run.finished < cursor)
          finished.add(run.test);
      }
      const rows: RouteRow[] = [];
      model.changes.changed.forEach((change, c) => {
        if (change.index >= cursor) return;
        const tests = testsOf.get(c) ?? new Set<string>();
        const scope = {
          files: new Set<string>(),
          symbols: new Set([change.symbol]),
          tests,
          cited: new Set<string>(),
        };
        const checks: Record<CheckResult, number> = {
          passed: 0,
          flagged: 0,
          unassessed: 0,
          pending: 0,
        };
        let related = 0;
        for (const check of state.checks.list) {
          if (!relates(scope, check.target, check.evidence)) continue;
          checks[check.result]++;
          related++;
        }
        let done = 0;
        for (const test of tests) if (finished.has(test)) done++;
        const resolved = related - checks.pending;
        // The furthest step this route has reached, and how far along it is.
        const [step, progress] =
          related > 0
            ? [3, resolved / Math.max(related, tests.size)]
            : done > 0
              ? [2, done / tests.size]
              : tests.size > 0
                ? [1, 1]
                : [0, 1];
        rows.push({
          file: basename(change.file),
          symbol: nameOf(change.symbol),
          path: change.file,
          symbolId: change.symbol,
          tests: tests.size,
          step,
          progress: Math.min(1, progress),
          checks,
        });
      });
      return { rows };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      const { colW, top, pitch, textSize, overflow, ...g } = routesGeometry(view.rows.length, size);
      ctx.font = font(8);
      ctx.fillStyle = COLOR.dim;
      STEPS.forEach((step, i) => {
        ctx.fillText(step.toUpperCase(), i * colW, 0);
      });
      const chars = charsIn(colW - 8, textSize);
      const shown = view.rows.slice(0, g.shown);
      shown.forEach((row, r) => {
        const y = top + r * pitch;
        const cells = [
          row.file,
          row.symbol,
          row.tests === 0 ? "—" : `${row.tests} test${row.tests === 1 ? "" : "s"}`,
          checkLabel(row.checks),
        ];
        const flagged = row.checks.flagged > 0;
        cells.forEach((text, i) => {
          const x = i * colW;
          const cellW = colW - 6;
          if (i === row.step) {
            // The step this route has reached: a pill filled to its progress, with an
            // underline at the fill edge while it is still in progress.
            const tint = i === 3 && flagged ? COLOR.flagDeep : "#2a2a2a";
            ctx.globalAlpha = 1;
            ctx.fillStyle = "#1c1c1c";
            ctx.fillRect(x, y, cellW, pitch - 1);
            ctx.fillStyle = tint;
            ctx.fillRect(x, y, cellW * row.progress, pitch - 1);
            if (row.progress < 1) {
              ctx.fillStyle = COLOR.hot;
              ctx.fillRect(x, y + pitch - 2, Math.max(2, cellW * row.progress), 1);
            }
          }
          ctx.font = font(textSize, i === row.step ? 700 : 400);
          ctx.fillStyle = i === 3 && flagged ? COLOR.flag : i === row.step ? COLOR.text : COLOR.dim;
          ctx.fillText(clip(text, chars), x + 3, y + (pitch - 1 - textSize) / 2);
        });
      });
      if (overflow) {
        ctx.font = font(8);
        ctx.fillStyle = COLOR.dim;
        ctx.fillText(`+${view.rows.length - shown.length} more`, 3, top + shown.length * pitch + 1);
      }
      ctx.globalAlpha = 1;
    },
    targets(view, size) {
      const { top, pitch, shown } = routesGeometry(view.rows.length, size);
      return view.rows.map((row, r) =>
        target(
          { kind: "symbol", symbol: row.symbolId, file: row.path },
          `${row.symbol} in ${row.file}: ${row.tests} tests, ${checkLabel(row.checks)}`,
          r < shown ? { x: 0, y: top + r * pitch, w: size.w, h: pitch - 1 } : null,
        ),
      );
    },
  };
}
