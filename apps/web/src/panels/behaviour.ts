/**
 * Behaviour diff field (DESIGN.md panel 4): BASE and HEAD grids with one cell per observed
 * (test, function) pair. A HEAD cell glows `--flag` where the same input gave a different output
 * and dim `--flag-deep` where the base itself was unstable (A ≠ A′, masked). A histogram of
 * differing cells per module runs underneath.
 *
 * A cell differs if, for some call, base and head results differ while A and A′ agree, or if
 * the engine reported a stable `diff.behaviour` for it. That is the same rule the engine's
 * behaviour differ applies (ARCHITECTURE §4.3), at sample granularity, so the field lights up
 * during the run, before the diff stage confirms it.
 */
import type { CockpitModel } from "../model/cockpit";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { font } from "./text";

export type CellStatus = "same" | "differs" | "unstable";

export interface FieldCell {
  readonly test: string;
  readonly symbol: string;
  readonly module: string;
  /** Samples observed per side (capped at 4 for brightness). */
  readonly base: number;
  readonly head: number;
  readonly status: CellStatus;
}

export interface FieldView {
  readonly cells: readonly FieldCell[];
  readonly histogram: readonly { readonly module: string; readonly differs: number }[];
}

const CAP = 4;
const MAX_DOT = 3;

export function behaviourPanel(model: CockpitModel): Panel<FieldView> {
  return {
    id: "behaviour",
    version(_t, cursor) {
      return versionOf(
        model.kinds.count("trace.sample", cursor) +
          1_000_000 * model.kinds.count("diff.behaviour", cursor),
      );
    },
    view(_t, cursor) {
      const { cells, samples } = model.observations;
      const n = cells.length;
      const base = new Int32Array(n);
      const head = new Int32Array(n);
      const seen = new Uint8Array(n);
      // Per (cell, call): results on each side, to compare like with like.
      const results = new Map<
        string,
        { base?: string | null; repeat?: string | null; head?: string | null }
      >();
      for (const s of samples) {
        if (s.index >= cursor) break;
        seen[s.cell] = 1;
        if (s.side === "base") base[s.cell] = (base[s.cell] ?? 0) + 1;
        if (s.side === "head") head[s.cell] = (head[s.cell] ?? 0) + 1;
        const key = `${s.cell}#${s.call}`;
        const entry = results.get(key) ?? {};
        const value = s.raised === null ? s.result : `raise ${s.raised}`;
        if (s.side === "base") entry.base = value;
        else if (s.side === "base_repeat") entry.repeat = value;
        else entry.head = value;
        results.set(key, entry);
      }
      const status = new Array<CellStatus>(n).fill("same");
      for (const [key, r] of results) {
        const cell = Number(key.slice(0, key.indexOf("#")));
        if (r.base !== undefined && r.repeat !== undefined && r.base !== r.repeat)
          status[cell] = "unstable";
        else if (
          status[cell] === "same" &&
          r.base !== undefined &&
          r.head !== undefined &&
          r.base !== r.head
        ) {
          if (r.repeat === undefined || r.repeat === r.base) status[cell] = "differs";
        }
      }
      // The engine's verdicts win: a stable diff.behaviour marks the cell, an unstable one masks it.
      for (const i of model.kinds.last("diff.behaviour", cursor, Number.MAX_SAFE_INTEGER)) {
        const event = model.store.event(i);
        if (event?.kind !== "diff.behaviour") continue;
        const cell = model.observations.cellOf(event.payload.test, event.payload.symbol_id);
        if (cell !== undefined)
          status[cell] = event.payload.stability === "unstable" ? "unstable" : "differs";
      }
      const shown: FieldCell[] = [];
      for (let i = 0; i < n; i++) {
        if (seen[i] !== 1) continue;
        const cell = cells[i];
        if (cell === undefined) continue;
        shown.push({
          ...cell,
          base: Math.min(CAP, base[i] ?? 0),
          head: Math.min(CAP, head[i] ?? 0),
          status: status[i] ?? "same",
        });
      }
      shown.sort((a, b) =>
        a.module < b.module
          ? -1
          : a.module > b.module
            ? 1
            : a.test < b.test
              ? -1
              : a.test > b.test
                ? 1
                : a.symbol < b.symbol
                  ? -1
                  : 1,
      );
      const byModule = new Map<string, number>();
      for (const c of shown)
        byModule.set(c.module, (byModule.get(c.module) ?? 0) + (c.status === "differs" ? 1 : 0));
      const histogram = [...byModule.entries()].map(([module, differs]) => ({ module, differs }));
      return { cells: shown, histogram };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      ctx.font = font(8);
      ctx.fillStyle = COLOR.dim;
      const gap = 10;
      const gridW = (size.w - gap) / 2;
      ctx.fillText("BASE", 0, 0);
      ctx.fillText("HEAD", gridW + gap, 0);
      const top = 12;
      const histogramH = 14;
      const gridH = Math.max(10, size.h - top - histogramH - 6);
      const n = view.cells.length;
      if (n > 0) {
        // A dot matrix like the reference: cells spread over the whole grid, dots never larger
        // than MAX_DOT px, so a small field reads as a sparse matrix rather than big squares.
        const columns = Math.max(1, Math.ceil(Math.sqrt((n * gridW) / gridH)));
        const rows = Math.max(1, Math.ceil(n / columns));
        const stepX = gridW / columns;
        const stepY = gridH / rows;
        const radius = Math.min(MAX_DOT, Math.max(0.8, Math.min(stepX, stepY) * 0.32));
        view.cells.forEach((cell, i) => {
          const cx = (i % columns) * stepX + stepX / 2;
          const cy = top + Math.floor(i / columns) * stepY + stepY / 2;
          // BASE grid: brightness by samples observed.
          ctx.globalAlpha = cell.base === 0 ? 0.25 : 0.3 + 0.17 * cell.base;
          ctx.fillStyle = cell.base === 0 ? COLOR.faint : COLOR.text;
          ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
          // HEAD grid: the same cell, tinted where behaviour differs.
          ctx.globalAlpha = cell.head === 0 ? 0.25 : 0.3 + 0.17 * cell.head;
          ctx.fillStyle =
            cell.status === "differs"
              ? COLOR.flag
              : cell.status === "unstable"
                ? COLOR.flagDeep
                : cell.head === 0
                  ? COLOR.faint
                  : COLOR.text;
          if (cell.status === "differs") ctx.globalAlpha = 1;
          ctx.fillRect(gridW + gap + cx - radius, cy - radius, radius * 2, radius * 2);
        });
      }
      // Histogram of differing cells per module.
      const baseY = size.h - 2;
      const bins = view.histogram.length;
      const most = view.histogram.reduce((m, b) => Math.max(m, b.differs), 0);
      ctx.globalAlpha = 1;
      view.histogram.forEach((bin, i) => {
        const x = (i / Math.max(1, bins)) * size.w;
        const w = Math.max(1, size.w / Math.max(1, bins) - 2);
        const h = bin.differs === 0 || most === 0 ? 1 : 2 + (histogramH - 2) * (bin.differs / most);
        ctx.fillStyle = bin.differs === 0 ? COLOR.faint : COLOR.flag;
        ctx.fillRect(x, baseY - h, w, h);
      });
    },
  };
}
