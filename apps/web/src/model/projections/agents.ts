/** Agents in their dispatch slots, with the recent tool calls the agent workspace types out. */
import type { AgentRole, AgentStatePayload } from "@repro/events";
import type { Projection } from "../projection";

/** How many recent `detail` lines each agent keeps for the workspace panel. */
export const RECENT_DETAILS = 10;

export interface AgentView {
  readonly id: string;
  readonly role: AgentRole;
  readonly model: string;
  readonly slot: number;
  state: AgentStatePayload["state"] | "spawned";
  tool: string | null;
  progress: number;
  /** Most recent `detail` lines, oldest first, with the seq that set each. */
  recent: { seq: number; text: string }[];
  lastSeq: number;
  verdicts: { supported: number; contradicted: number; unverifiable: number };
  rejected: number;
}

export interface AgentsState {
  byId: Map<string, AgentView>;
  /** Agent id per dispatch slot (the UI shows 12); a later agent may reuse a slot. */
  slots: (string | null)[];
}

export const agentsProjection: Projection<AgentsState> = {
  name: "agents",
  init: () => ({ byId: new Map(), slots: [] }),
  apply(state, event) {
    if (event.agent === null) return state;
    switch (event.kind) {
      case "agent.spawned": {
        const { role, model, slot } = event.payload;
        state.byId.set(event.agent, {
          id: event.agent,
          role,
          model,
          slot,
          state: "spawned",
          tool: null,
          progress: 0,
          recent: [],
          lastSeq: event.seq,
          verdicts: { supported: 0, contradicted: 0, unverifiable: 0 },
          rejected: 0,
        });
        while (state.slots.length <= slot) state.slots.push(null);
        state.slots[slot] = event.agent;
        return state;
      }
      case "agent.state": {
        const agent = state.byId.get(event.agent);
        if (agent === undefined) return state;
        const { state: next, tool, detail, progress } = event.payload;
        agent.state = next;
        agent.tool = tool;
        if (progress !== null) agent.progress = progress;
        if (detail !== null) {
          agent.recent.push({ seq: event.seq, text: detail });
          if (agent.recent.length > RECENT_DETAILS) agent.recent.shift();
        }
        agent.lastSeq = event.seq;
        return state;
      }
      case "verdict.issued": {
        const agent = state.byId.get(event.agent);
        if (agent !== undefined) agent.verdicts[event.payload.verdict.verdict]++;
        return state;
      }
      case "verdict.rejected": {
        const agent = state.byId.get(event.agent);
        if (agent !== undefined) agent.rejected++;
        return state;
      }
      default:
        return state;
    }
  },
};
