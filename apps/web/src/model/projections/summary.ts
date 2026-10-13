/** Monotone counters for the header and the perf HUD. */
import type { Projection } from "../projection";

export interface SummaryState {
  /** Events this build interpreted (unknown kinds are counted by the store, not here). */
  events: number;
  claims: number;
  agents: Set<string>;
  /** Files of module nodes in the dependency graph (the header's FILES). */
  files: Set<string>;
  graphNodes: number;
  graphEdges: number;
  selectedTests: number;
  evidence: number;
  missing: number;
}

export const summaryProjection: Projection<SummaryState> = {
  name: "summary",
  init: () => ({
    events: 0,
    claims: 0,
    agents: new Set(),
    files: new Set(),
    graphNodes: 0,
    graphEdges: 0,
    selectedTests: 0,
    evidence: 0,
    missing: 0,
  }),
  apply(state, event) {
    state.events++;
    switch (event.kind) {
      case "claim.extracted":
        state.claims++;
        break;
      case "agent.spawned":
        if (event.agent !== null) state.agents.add(event.agent);
        break;
      case "graph.node":
        state.graphNodes++;
        if (event.payload.node.type === "module") state.files.add(event.payload.node.file);
        break;
      case "graph.edge":
        state.graphEdges++;
        break;
      case "test.selected":
        state.selectedTests++;
        break;
      case "evidence.created":
        state.evidence++;
        break;
      case "missing.recorded":
        state.missing++;
        break;
      default:
        break;
    }
    return state;
  },
};
