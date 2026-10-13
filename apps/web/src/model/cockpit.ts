/**
 * The cockpit's model: one store, its indexes, and the folded cockpit state, plus the selectors
 * views read from. Views never fold events themselves; they ask for the state at a time.
 */

import { Folder } from "./folder";
import { combine, type StateOf } from "./projection";
import { agentsProjection } from "./projections/agents";
import { type CheckCounts, checksProjection } from "./projections/checks";
import { claimsProjection } from "./projections/claims";
import { runProjection, type StageView } from "./projections/run";
import { summaryProjection } from "./projections/summary";
import { type AppendSummary, EventStore } from "./store";
import { KindIndex, WindowIndex } from "./window";

export const cockpitProjection = combine("cockpit", {
  run: runProjection,
  summary: summaryProjection,
  checks: checksProjection,
  claims: claimsProjection,
  agents: agentsProjection,
});

export type CockpitState = StateOf<typeof cockpitProjection>;

export interface HeaderCounters {
  readonly claims: number;
  readonly agents: number;
  readonly files: number;
  readonly checks: number;
  readonly flagged: number;
}

/** The header's five counters. CHECKS and FLAGGED come from the check model (ADR-0015). */
export function headerCounters(state: CockpitState): HeaderCounters {
  const { checks, flagged } = state.checks.counts;
  return {
    claims: state.summary.claims,
    agents: state.summary.agents.size,
    files: state.summary.files.size,
    checks,
    flagged,
  };
}

/**
 * The change×check index footer. It reads the very same counts object as `headerCounters`,
 * which is why the two cannot disagree (B02 acceptance; tested at every cursor).
 */
export function indexFooter(state: CockpitState): Readonly<CheckCounts> {
  return state.checks.counts;
}

/** Footer text, e.g. "28 checks / 20 passed / 4 flagged / 4 unassessed". */
export function indexFooterText(counts: Readonly<CheckCounts>): string {
  const parts = [`${counts.checks} checks`, `${counts.passed} passed`, `${counts.flagged} flagged`];
  if (counts.unassessed > 0) parts.push(`${counts.unassessed} unassessed`);
  if (counts.pending > 0) parts.push(`${counts.pending} pending`);
  return parts.join(" / ");
}

export function stageProgress(state: CockpitState): readonly StageView[] {
  return state.run.stages;
}

/** Default snapshot interval: about 70 snapshots for the 18.5k-event stress run. */
export const SNAPSHOT_EVERY = 256;

export class CockpitModel {
  readonly store = new EventStore();
  readonly kinds = new KindIndex(this.store);
  readonly window = new WindowIndex(this.store);
  readonly folder: Folder<CockpitState>;

  constructor(snapshotEvery = SNAPSHOT_EVERY) {
    this.folder = new Folder(this.store, cockpitProjection, snapshotEvery);
  }

  /** Appends events (parsed JSON objects) and brings every index up to date. */
  ingest(events: Iterable<unknown>): AppendSummary {
    const summary = this.store.appendAll(events);
    this.kinds.sync();
    this.folder.sync();
    return summary;
  }

  /** The folded state as of presentation time `t` (ms since the run started). Valid until the next call. */
  stateAtTime(t: number): { cursor: number; state: CockpitState } {
    const cursor = this.store.cursorAt(t);
    return { cursor, state: this.folder.stateAt(cursor) };
  }
}
