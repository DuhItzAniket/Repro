/**
 * Agent workspace (DESIGN.md panel 3): the focused agent's recent tool calls typed out like
 * code, with a block cursor that blinks while the agent works. The focused agent is the one
 * with the latest `agent.state`, unless the user has focused one (B11). Typing is a pure function of
 * `t` since the line's event, in wall-clock time; under reduced motion lines appear whole and
 * the cursor does not blink.
 */
import type { CockpitModel } from "../model/cockpit";
import type { AgentView } from "../model/projections/agents";
import { type Motion, NORMAL_MOTION } from "../motion/motion";
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

/**
 * `pinned` returns the agent the user focused (B11), or null to follow the agent with the latest
 * state change.
 */
export function workspacePanel(
  model: CockpitModel,
  pinned: () => string | null = () => null,
): Panel<WorkspaceView> {
  /** The agent shown at `cursor`: the pinned one if it has spawned, else the latest to change. */
  const followed = (cursor: number): AgentView | undefined => {
    const { agents } = model.folder.stateAt(cursor);
    const id = pinned();
    if (id !== null && agents.byId.has(id)) return agents.byId.get(id);
    const last = model.kinds.lastIndex("agent.state", cursor);
    const agent = last < 0 ? null : (model.store.event(last)?.agent ?? null);
    return agent === null ? undefined : agents.byId.get(agent);
  };
  const typedOf = (t: number, seq: number, text: string, motion: Motion): number =>
    motion.reduced
      ? text.length
      : Math.max(
          0,
          Math.min(
            text.length,
            Math.floor((t - (model.store.time[seq - 1] as number)) / (TYPE_MS * motion.speed)),
          ),
        );
  /** Blink phase (0 or 1) while working; steady under reduced motion. */
  const blinkOf = (t: number, motion: Motion): number =>
    motion.reduced ? 0 : Math.floor(t / (BLINK_MS * motion.speed)) % 2;
  return {
    id: "workspace",
    version(t, cursor, motion = NORMAL_MOTION) {
      const agent = followed(cursor);
      if (agent === undefined) return versionOf(0);
      const newest = agent.recent.at(-1);
      const typed = newest === undefined ? 0 : typedOf(t, newest.seq, newest.text, motion);
      const working = agent.state !== "done" && agent.state !== "failed";
      const blink = working ? blinkOf(t, motion) : 0;
      return versionOf(agent.lastSeq, typed * 2 + blink);
    },
    view(t, cursor, motion = NORMAL_MOTION) {
      const agent = followed(cursor);
      if (agent === undefined) return { heading: null, lines: [], cursor: false };
      const recent = agent.recent;
      const lines = recent.map(
        (line, i): WorkspaceLine => ({
          seq: line.seq,
          text: line.text,
          typed:
            i === recent.length - 1 ? typedOf(t, line.seq, line.text, motion) : line.text.length,
        }),
      );
      const working = agent.state !== "done" && agent.state !== "failed";
      return {
        heading: `${agent.id} · ${agent.role} · ${agent.model}`,
        lines,
        cursor: working && blinkOf(t, motion) === 0,
      };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      if (view.heading === null) {
        ctx.font = font(SIZE);
        ctx.fillStyle = COLOR.dim;
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
        ctx.fillStyle = COLOR.dim;
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
