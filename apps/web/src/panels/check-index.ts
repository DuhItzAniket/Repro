/**
 * Change × check index (DESIGN.md panel 8, ADR-0015): a dot matrix with claims and unclaimed
 * changes as rows and every check as a column. A dot is filled where the check passed, rose
 * where it is flagged, hollow where it could not be assessed, and dim while it waits for review;
 * a faint point marks a check unrelated to the row. The right column gives each row's status.
 *
 * When there are more checks than columns fit, each column covers a run of adjacent checks and
 * shows the most urgent related result among them. The footer (`indexFooterText`) and the
 * header's counters count the same results the columns show.
 */

import type { Focus } from "../focus/focus";
import { type CheckIndexView, checkIndex, type RowStatus } from "../model/check-index";
import type { CockpitModel } from "../model/cockpit";
import { CHECK_KINDS, type CheckResult } from "../model/projections/checks";
import { COLOR } from "../styles/palette";
import { type Panel, type PanelSize, type PanelTarget, target, versionOf } from "./panel";
import { charsIn, clip, font } from "./text";

/** Smallest column pitch (px) before adjacent checks share a column. */
export const MIN_PITCH = 3;
const MAX_DOT = 5;

const URGENCY: Readonly<Record<CheckResult, number>> = {
  flagged: 4,
  pending: 3,
  unassessed: 2,
  passed: 1,
};

const STATUS_COLOR: Readonly<Record<RowStatus, string>> = {
  verified: COLOR.ok,
  flagged: COLOR.flag,
  review: COLOR.dim,
};

const RELEVANT = [
  ...CHECK_KINDS,
  "claim.extracted",
  "verdict.issued",
  "symbol.changed",
  "test.selected",
  "stage.started",
  "stage.finished",
  "run.finished",
] as const;

/** Checks per drawn column: `[from, to)` ranges over the check list. */
export function columnRanges(checks: number, width: number): [number, number][] {
  const columns = Math.min(checks, Math.max(1, Math.floor(width / MIN_PITCH)));
  const out: [number, number][] = [];
  for (let k = 0; k < columns; k++)
    out.push([Math.floor((k * checks) / columns), Math.floor(((k + 1) * checks) / columns)]);
  return out;
}

const LABEL_W = 74;
const STATUS_W = 52;
const TOP = 11;

/** Geometry shared by drawing and focus targets. */
export function indexGeometry(view: CheckIndexView, size: PanelSize) {
  const matrixW = Math.max(10, size.w - LABEL_W - STATUS_W);
  // Rows shrink with the panel, down to 7 px (7 px text), like the reference's dense index.
  const pitchY = Math.max(7, Math.min(13, (size.h - TOP) / Math.max(1, view.rows.length)));
  const fit = Math.max(1, Math.floor((size.h - TOP) / pitchY));
  const overflow = view.rows.length > fit;
  const ranges = columnRanges(view.results.length, matrixW);
  const pitchX = matrixW / Math.max(1, ranges.length);
  return {
    matrixW,
    pitchY,
    text: Math.max(7, Math.min(9, Math.floor(pitchY - 1))),
    shown: overflow ? fit - 1 : view.rows.length,
    overflow,
    ranges,
    pitchX,
    dot: Math.max(1.5, Math.min(MAX_DOT, pitchX - 2, pitchY - 3)),
  };
}

/** The most urgent check of `row` within `[from, to)`, or -1. */
function worstIn(view: CheckIndexView, related: ReadonlySet<number>, from: number, to: number) {
  let worst = -1;
  for (let i = from; i < to; i++) {
    if (!related.has(i)) continue;
    const result = view.results[i] as CheckResult;
    if (worst < 0 || URGENCY[result] > URGENCY[view.results[worst] as CheckResult]) worst = i;
  }
  return worst;
}

const rowFocus = (row: CheckIndexView["rows"][number]): Focus | null =>
  row.kind === "claim"
    ? { kind: "claim", id: row.id }
    : row.kind === "change"
      ? { kind: "file", file: row.id }
      : null;

export function indexPanel(model: CockpitModel): Panel<CheckIndexView> {
  return {
    id: "index",
    version(_t, cursor) {
      let sum = 0;
      for (const kind of RELEVANT) sum += model.kinds.count(kind, cursor);
      return versionOf(sum);
    },
    view(_t, cursor) {
      return checkIndex(model.folder.stateAt(cursor), model.changes, cursor);
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      const labelW = LABEL_W;
      const statusW = STATUS_W;
      const { pitchY, text, ranges, pitchX, dot, overflow, ...g } = indexGeometry(view, size);
      ctx.font = font(8);
      ctx.fillStyle = COLOR.dim;
      ctx.fillText("CLAIM / CHANGE", 0, 0);
      ctx.fillText(`CHECKS (${view.results.length})`, labelW, 0);
      ctx.fillText("STATUS", size.w - statusW + 6, 0);
      const top = TOP;
      const rows = view.rows;
      const shown = rows.slice(0, g.shown);
      shown.forEach((row, r) => {
        const y = top + r * pitchY;
        const cy = y + pitchY / 2;
        ctx.globalAlpha = 1;
        ctx.font = font(text, row.kind === "claim" ? 700 : 400);
        ctx.fillStyle = row.kind === "claim" ? COLOR.text : COLOR.dim;
        ctx.fillText(clip(row.label, charsIn(labelW - 6, text)), 0, cy - text / 2);
        const related = new Set(row.checks);
        ranges.forEach(([from, to], k) => {
          const index = worstIn(view, related, from, to);
          const worst = index < 0 ? null : (view.results[index] as CheckResult);
          const cx = labelW + k * pitchX + pitchX / 2;
          if (worst === null) {
            // Unrelated: a backdrop point, so the matrix reads as a grid.
            const d = Math.max(1, dot * 0.4);
            ctx.globalAlpha = 1;
            ctx.fillStyle = COLOR.border;
            ctx.fillRect(cx - d / 2, cy - d / 2, d, d);
            return;
          }
          const x = cx - dot / 2;
          const yy = cy - dot / 2;
          if (worst === "unassessed") {
            ctx.globalAlpha = 1;
            ctx.strokeStyle = COLOR.dim;
            ctx.lineWidth = 1;
            ctx.strokeRect(x + 0.5, yy + 0.5, dot - 1, dot - 1);
            return;
          }
          ctx.globalAlpha = worst === "pending" ? 0.6 : 1;
          ctx.fillStyle =
            worst === "flagged" ? COLOR.flag : worst === "pending" ? COLOR.faint : COLOR.text;
          ctx.fillRect(x, yy, dot, dot);
        });
        ctx.globalAlpha = 1;
        ctx.font = font(text);
        ctx.fillStyle = STATUS_COLOR[row.status];
        ctx.fillText(row.status, size.w - statusW + 6, cy - text / 2);
      });
      if (overflow) {
        ctx.font = font(8);
        ctx.fillStyle = COLOR.dim;
        ctx.fillText(`+${rows.length - shown.length} more`, 0, top + shown.length * pitchY + 2);
      }
      ctx.globalAlpha = 1;
    },
    targets(view, size) {
      const { pitchY, shown, ranges, pitchX } = indexGeometry(view, size);
      const out: PanelTarget[] = [];
      view.rows.forEach((row, r) => {
        const focus = rowFocus(row);
        const y = TOP + r * pitchY;
        const visible = r < shown;
        if (focus !== null) {
          const n = row.checks.length;
          const counts = `${n} related ${n === 1 ? "check" : "checks"}`;
          out.push(
            target(focus, row.label, visible ? { x: 0, y, w: size.w, h: pitchY } : null, true, [
              row.status,
              counts,
            ]),
          );
        }
        if (!visible) return;
        // Cells: each column with a related check focuses its most urgent one.
        const related = new Set(row.checks);
        ranges.forEach(([from, to], k) => {
          const index = worstIn(view, related, from, to);
          if (index < 0) return;
          out.push(
            target(
              { kind: "check", index },
              `${row.label}, check ${index + 1}: ${view.results[index]}`,
              { x: LABEL_W + k * pitchX, y, w: pitchX, h: pitchY },
              false,
            ),
          );
        });
      });
      return out;
    },
  };
}
