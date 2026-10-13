/**
 * The bridge from folded cockpit state to Preact signals. The frame loop calls `update` only
 * when the fold cursor moves, and a signal is written only when its value actually changes. So
 * the shell re-renders on new information, never on every frame (DESIGN.md "Performance
 * budget").
 */
import { type Signal, signal } from "@preact/signals";
import type { CardStatus, Stage, Status } from "@repro/events";
import {
  type CockpitState,
  type HeaderCounters,
  headerCounters,
  indexFooter,
  indexFooterText,
} from "../model/cockpit";

export interface StageSegment {
  readonly name: Stage;
  readonly state: "pending" | "active" | "done";
  readonly outcome: Status | null;
}

export interface RunLabel {
  readonly repo: string | null;
  readonly pr: string | null;
  readonly cardStatus: CardStatus | null;
}

export interface ShellView {
  readonly counters: Signal<HeaderCounters>;
  readonly stages: Signal<readonly StageSegment[]>;
  readonly run: Signal<RunLabel>;
  /** The change×check index footer text (same counts as the header). */
  readonly indexFooter: Signal<string>;
  /** Whether the run has finished (some captions change when it has). */
  readonly finished: Signal<boolean>;
  /** Loading or error message from the app, if any (not derived from events). */
  readonly status: Signal<string | null>;
  update(state: CockpitState): void;
}

const ZERO: HeaderCounters = { claims: 0, agents: 0, files: 0, checks: 0, flagged: 0 };

const sameCounters = (a: HeaderCounters, b: HeaderCounters): boolean =>
  a.claims === b.claims &&
  a.agents === b.agents &&
  a.files === b.files &&
  a.checks === b.checks &&
  a.flagged === b.flagged;

function sameStages(state: CockpitState, current: readonly StageSegment[]): boolean {
  const stages = state.run.stages;
  if (stages.length !== current.length) return false;
  for (let i = 0; i < stages.length; i++) {
    const a = stages[i];
    const b = current[i];
    if (a === undefined || b === undefined || a.state !== b.state || a.outcome !== b.outcome) {
      return false;
    }
  }
  return true;
}

export function createShellView(): ShellView {
  const counters = signal<HeaderCounters>(ZERO);
  const stages = signal<readonly StageSegment[]>([]);
  const run = signal<RunLabel>({ repo: null, pr: null, cardStatus: null });
  const footer = signal("");
  const finished = signal(false);
  const status = signal<string | null>(null);

  return {
    counters,
    stages,
    run,
    indexFooter: footer,
    finished,
    status,
    update(state) {
      const next = headerCounters(state);
      if (!sameCounters(next, counters.value)) counters.value = next;

      if (!sameStages(state, stages.value)) {
        stages.value = state.run.stages.map(({ name, state: s, outcome }) => ({
          name,
          state: s,
          outcome,
        }));
      }

      const { repo, pr, cardStatus } = state.run;
      const prLabel =
        pr === null ? null : pr.number === null ? pr.title : `#${pr.number} ${pr.title}`;
      const label = run.value;
      if (label.repo !== repo || label.pr !== prLabel || label.cardStatus !== cardStatus) {
        run.value = { repo, pr: prLabel, cardStatus };
      }

      const text = indexFooterText(indexFooter(state));
      if (text !== footer.value) footer.value = text;
      const done = state.run.finishedAt !== null;
      if (done !== finished.value) finished.value = done;
    },
  };
}
