/** Run metadata and the seven-stage progress (header title line and progress bar). */
import type {
  CardPublishedPayload,
  CardStatus,
  GitRef,
  IsolationLevel,
  NetworkEnforcement,
  RunFinishedPayload,
  SandboxBackend,
  Side,
  Stage,
  Status,
} from "@repro/events";
import { STAGES } from "../codes";
import type { Projection } from "../projection";

export interface StageView {
  readonly name: Stage;
  state: "pending" | "active" | "done";
  /** Envelope status of `stage.finished`: ok, warn or fail. */
  outcome: Status | null;
  startedAt: number | null;
  finishedAt: number | null;
}

export interface SandboxView {
  readonly level: IsolationLevel;
  readonly network: NetworkEnforcement;
  readonly backend: SandboxBackend;
}

export interface RunState {
  runId: string | null;
  repo: string | null;
  pr: { title: string; number: number | null } | null;
  base: GitRef | null;
  head: GitRef | null;
  startedAt: number | null;
  finishedAt: number | null;
  outcome: RunFinishedPayload["outcome"] | null;
  cardStatus: CardStatus | null;
  card: CardPublishedPayload | null;
  stages: StageView[];
  /** Index of the stage in progress, or -1. */
  active: number;
  sandboxes: Partial<Record<Side, SandboxView>>;
}

export const runProjection: Projection<RunState> = {
  name: "run",
  init: () => ({
    runId: null,
    repo: null,
    pr: null,
    base: null,
    head: null,
    startedAt: null,
    finishedAt: null,
    outcome: null,
    cardStatus: null,
    card: null,
    stages: STAGES.map((name) => ({
      name,
      state: "pending",
      outcome: null,
      startedAt: null,
      finishedAt: null,
    })),
    active: -1,
    sandboxes: {},
  }),
  apply(state, event, { time }) {
    switch (event.kind) {
      case "run.started": {
        const { repo, pr, base, head } = event.payload;
        state.runId = event.run_id;
        state.repo = repo.name;
        state.pr = pr === null ? null : { title: pr.title, number: pr.number };
        state.base = base;
        state.head = head;
        state.startedAt = time;
        return state;
      }
      case "stage.started": {
        const index = STAGES.indexOf(event.stage);
        const stage = state.stages[index];
        if (stage !== undefined) {
          stage.state = "active";
          stage.startedAt = time;
          state.active = index;
        }
        return state;
      }
      case "stage.finished": {
        const index = STAGES.indexOf(event.stage);
        const stage = state.stages[index];
        if (stage !== undefined) {
          stage.state = "done";
          stage.outcome = event.status;
          stage.finishedAt = time;
          if (state.active === index) state.active = -1;
        }
        return state;
      }
      case "sandbox.ready": {
        const { side, isolation_level: level, network, backend } = event.payload;
        state.sandboxes[side] = { level, network, backend };
        return state;
      }
      case "card.published":
        state.card = event.payload;
        state.cardStatus = event.payload.status;
        return state;
      case "run.finished":
        state.finishedAt = time;
        state.outcome = event.payload.outcome;
        state.cardStatus = event.payload.card_status ?? state.cardStatus;
        if (state.active >= 0) state.active = -1;
        return state;
      default:
        return state;
    }
  },
};
