/**
 * Agent workspace (DESIGN.md panel 3): the focused agent's recent tool calls typed out like
 * code, with a block cursor that blinks while the agent works. The focused agent is the one
 * with the latest `agent.state` (B11 lets the user pin one). Typing is a pure function of
 * `t` since the line's event.
 */
import type { CockpitModel } from "../model/cockpit";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { charsIn, clip, font } from "./text";

/** Typing speed for the newest line (ms per character). */
export const TYPE_MS = 18;
export const BLINK_MS = 530;
const SIZE = 10;
const LINE_HEIGHT = 13;

export interface WorkspaceLine {
  readonly seq: number;
  readonly text: string;
  /** Characters visible so far. */
  readonly typed: number;
}

export interface WorkspaceView {
  readonly heading: string | null;
  readonly lines: readonly WorkspaceLine[];
  /** Whether the block cursor is drawn this frame (blinks while the agent works). */
  readonly cursor: boolean;
}

export function workspacePanel(model: CockpitModel): Panel<WorkspaceView> {
  const typedOf = (t: number, seq: number, text: string): number =>
    Math.max(
      0,
      Math.min(text.length, Math.floor((t - (model.store.time[seq - 1] as number)) / TYPE_MS)),
    );
  return {
    id: "workspace",
    version(t, cursor) {
      const last = model.kinds.lastIndex("agent.state", cursor);
      if (last < 0) return versionOf(0);
      const event = model.store.event(last);
      const text = event?.kind === "agent.state" ? (event.payload.detail ?? "") : "";
      const working =
        event?.kind === "agent.state" &&
        event.payload.state !== "done" &&
        event.payload.state !== "failed";
      const typed = typedOf(t, last + 1, text);
      const blink = working ? Math.floor(t / BLINK_MS) % 2 : 0;
      return versionOf(last + 1, typed * 2 + blink);
    },
    view(t, cursor) {
      const last = model.kinds.lastIndex("agent.state", cursor);
      const event = last < 0 ? null : model.store.event(last);
      if (event === null || event.agent === null)
        return { heading: null, lines: [], cursor: false };
      const agent = model.folder.stateAt(cursor).agents.byId.get(event.agent);
      if (agent === undefined) return { heading: null, lines: [], cursor: false };
      const recent = agent.recent;
      const lines = recent.map(
        (line, i): WorkspaceLine => ({
          seq: line.seq,
          text: line.text,
          typed: i === recent.length - 1 ? typedOf(t, line.seq, line.text) : line.text.length,
        }),
      );
      const working = agent.state !== "done" && agent.state !== "failed";
      return {
        heading: `${agent.id} · ${agent.role} · ${agent.model}`,
        lines,
        cursor: working && Math.floor(t / BLINK_MS) % 2 === 0,
      };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      if (view.heading === null) {
        ctx.font = font(SIZE);
        ctx.fillStyle = COLOR.faint;
        ctx.fillText("no agent running", 0, 0);
        return;
      }
      ctx.font = font(8);
      ctx.fillStyle = COLOR.dim;
      ctx.fillText(clip(view.heading.toUpperCase(), charsIn(size.w, 8)), 0, 0);
      const codeX = 34;
      const chars = charsIn(size.w - codeX, SIZE);
      const rows = Math.max(1, Math.floor((size.h - 16) / LINE_HEIGHT));
      const lines = view.lines.slice(-rows);
      lines.forEach((line, i) => {
        const y = 16 + i * LINE_HEIGHT;
        const newest = i === lines.length - 1;
        ctx.font = font(SIZE);
        ctx.fillStyle = COLOR.faint;
        ctx.fillText(String(line.seq % 1000).padStart(3, "0"), 0, y);
        const shown = clip(line.text.slice(0, line.typed), chars);
        ctx.fillStyle = newest ? COLOR.text : COLOR.dim;
        ctx.fillText(shown, codeX, y);
        if (newest && view.cursor) {
          ctx.fillStyle = COLOR.hot;
          ctx.fillRect(codeX + shown.length * SIZE * 0.6 + 1, y, SIZE * 0.6, SIZE + 1);
        }
      });
    },
  };
}
