/**
 * Agents / dispatch (DESIGN.md panel 7): the 12 dispatch slots in two columns of six. Each shows
 * `id role`, a segmented progress bar and a tiny status under it: working, waiting, done or
 * flagged. A bar is tinted `--flag-deep` when its agent failed or contradicted a claim.
 */
import type { CockpitModel } from "../model/cockpit";
import type { AgentView } from "../model/projections/agents";
import { COLOR } from "../styles/palette";
import { type Panel, versionOf } from "./panel";
import { charsIn, clip, font } from "./text";

export const SLOTS = 12;
export const SEGMENTS = 10;

export type DispatchStatus = "working" | "waiting" | "done" | "flagged";

export interface SlotView {
  readonly slot: number;
  readonly id: string | null;
  readonly role: string;
  readonly progress: number;
  readonly status: DispatchStatus | null;
  /** The tool in use while working. */
  readonly tool: string | null;
  readonly flagged: boolean;
}

export interface DispatchView {
  readonly slots: readonly SlotView[];
}

export function statusOf(agent: AgentView): { status: DispatchStatus; flagged: boolean } {
  const flagged = agent.state === "failed" || agent.verdicts.contradicted > 0;
  const finished = agent.state === "done" || agent.state === "failed";
  if (finished) return { status: flagged ? "flagged" : "done", flagged };
  if (agent.state === "thinking" || agent.state === "tool_call")
    return { status: "working", flagged };
  return { status: "waiting", flagged };
}

const RELEVANT = ["agent.spawned", "agent.state", "verdict.issued", "verdict.rejected"] as const;

export function dispatchPanel(model: CockpitModel): Panel<DispatchView> {
  return {
    id: "dispatch",
    version(_t, cursor) {
      let sum = 0;
      for (const kind of RELEVANT) sum += model.kinds.count(kind, cursor);
      return versionOf(sum);
    },
    view(_t, cursor) {
      const { agents } = model.folder.stateAt(cursor);
      const slots: SlotView[] = [];
      for (let slot = 0; slot < SLOTS; slot++) {
        const id = agents.slots[slot] ?? null;
        const agent = id === null ? undefined : agents.byId.get(id);
        if (agent === undefined) {
          slots.push({
            slot,
            id: null,
            role: "",
            progress: 0,
            status: null,
            tool: null,
            flagged: false,
          });
          continue;
        }
        const { status, flagged } = statusOf(agent);
        slots.push({
          slot,
          id: agent.id,
          role: agent.role,
          // A finished agent's bar is full even if it never reported progress.
          progress: status === "done" || status === "flagged" ? 1 : agent.progress,
          status,
          // MCP tools are named `mcp__<server>__<tool>`; the server prefix is noise here.
          tool: status === "working" ? (agent.tool?.replace(/^mcp__[^_]+__/, "") ?? null) : null,
          flagged,
        });
      }
      return { slots };
    },
    draw(ctx, view, size) {
      ctx.textBaseline = "top";
      ctx.textAlign = "left";
      const gap = 12;
      const colW = (size.w - gap) / 2;
      const rowH = size.h / (SLOTS / 2);
      const labelW = 62;
      const barW = Math.max(10, colW - labelW);
      const segW = barW / SEGMENTS;
      const barH = Math.max(3, Math.min(7, rowH * 0.4));
      view.slots.forEach((s, i) => {
        const x = i < SLOTS / 2 ? 0 : colW + gap;
        const y = (i % (SLOTS / 2)) * rowH;
        ctx.globalAlpha = 1;
        ctx.font = font(9);
        ctx.fillStyle = s.id === null ? COLOR.faint : COLOR.dim;
        ctx.fillText(s.id ?? String(s.slot + 1).padStart(2, "0"), x, y + 1);
        ctx.fillStyle = s.id === null ? COLOR.faint : COLOR.text;
        ctx.fillText(clip(s.role, charsIn(labelW - 26, 9)), x + 26, y + 1);
        const filled = Math.round(s.progress * SEGMENTS);
        for (let k = 0; k < SEGMENTS; k++) {
          const on = k < filled;
          ctx.globalAlpha = on ? 1 : 0.6;
          ctx.fillStyle = !on
            ? "#1c1c1c"
            : s.flagged
              ? COLOR.flagDeep
              : s.status === "done"
                ? COLOR.dim
                : COLOR.text;
          ctx.fillRect(x + labelW + k * segW, y + 2, Math.max(1, segW - 1), barH);
        }
        if (s.status === null) return;
        ctx.globalAlpha = 1;
        ctx.font = font(7);
        ctx.fillStyle =
          s.status === "flagged" ? COLOR.flag : s.status === "working" ? COLOR.text : COLOR.dim;
        const status = s.tool === null ? s.status : `${s.status} · ${s.tool}`;
        ctx.fillText(clip(status, charsIn(barW, 7)), x + labelW, y + 3 + barH);
      });
      ctx.globalAlpha = 1;
    },
  };
}
