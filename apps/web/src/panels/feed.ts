/**
 * Investigation feed (DESIGN.md panel 1): a scrolling log of `log.line` events as
 * `seq  verb  message`. The newest row is bold and slides in over 150 ms of wall-clock time
 * (instantly under reduced motion); warnings and errors are tinted. Purely from the KindIndex:
 * the rows at cursor k are the last log lines before k.
 */
import type { LogLinePayload } from "@repro/events";
import type { CockpitModel } from "../model/cockpit";
import { type Motion, NORMAL_MOTION } from "../motion/motion";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { charsIn, clip, easeOutCubic, font } from "./text";

export const ROW_HEIGHT = 13;
export const INSERT_MS = 150;
const MAX_ROWS = 32;
const INSERT_STEPS = 8;
const SIZE = 10;

export interface FeedRow {
  readonly seq: number;
  readonly verb: string;
  readonly message: string;
  readonly level: LogLinePayload["level"];
}

export interface FeedView {
  readonly rows: readonly FeedRow[];
  /** 0–1: how far the newest row has slid in. */
  readonly insert: number;
}

export function feedPanel(model: CockpitModel): Panel<FeedView> {
  const insertAt = (
    t: number,
    cursor: number,
    motion: Motion,
  ): { count: number; progress: number } => {
    const count = model.kinds.count("log.line", cursor);
    const last = model.kinds.lastIndex("log.line", cursor);
    const raw =
      last < 0 || motion.reduced
        ? 1
        : Math.min(1, (t - (model.store.time[last] as number)) / (INSERT_MS * motion.speed));
    // Quantised like the version, so equal versions always draw the same thing (B10 found the
    // view sliding between steps while the host kept the drawing from the step's start).
    const progress = raw >= 1 ? 1 : Math.floor(raw * INSERT_STEPS) / INSERT_STEPS;
    return { count, progress };
  };
  return {
    id: "feed",
    version(t, cursor, motion = NORMAL_MOTION) {
      const { count, progress } = insertAt(t, cursor, motion);
      return versionOf(count, progress * INSERT_STEPS);
    },
    view(t, cursor, motion = NORMAL_MOTION) {
      const rows = model.kinds.last("log.line", cursor, MAX_ROWS).flatMap((i): FeedRow[] => {
        const event = model.store.event(i);
        if (event?.kind !== "log.line") return [];
        return [
          {
            seq: event.seq,
            verb: event.payload.verb,
            message: event.payload.message,
            level: event.payload.level,
          },
        ];
      });
      return { rows, insert: insertAt(t, cursor, motion).progress };
    },
    draw(ctx, view, size) {
      const { rows } = view;
      const shift = (1 - easeOutCubic(view.insert)) * ROW_HEIGHT;
      const messageX = 82;
      const chars = charsIn(size.w - messageX, SIZE);
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      for (
        let k = rows.length - 1, y = size.h - ROW_HEIGHT + shift;
        k >= 0 && y > -ROW_HEIGHT;
        k--, y -= ROW_HEIGHT
      ) {
        const row = rows[k] as FeedRow;
        const newest = k === rows.length - 1;
        const flagged = row.level === "warning" || row.level === "error";
        ctx.globalAlpha = newest ? Math.max(0.15, easeOutCubic(view.insert)) : 1;
        ctx.font = font(SIZE, newest ? 700 : 400);
        ctx.fillStyle = COLOR.faint;
        ctx.fillText(String(row.seq % 1000).padStart(3, "0"), 0, y);
        ctx.fillStyle = newest ? COLOR.text : COLOR.dim;
        ctx.fillText(row.verb, 34, y);
        ctx.fillStyle = flagged ? COLOR.flag : newest ? COLOR.text : COLOR.dim;
        ctx.fillText(clip(row.message, chars), messageX, y);
      }
      ctx.globalAlpha = 1;
    },
  };
}
