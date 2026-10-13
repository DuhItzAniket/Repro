/**
 * The check model (ADR-0015). One projection feeds the header's CHECKS and FLAGGED counters,
 * the change×check index cells and the index footer, so they can never disagree.
 */
import type { ReproEvent, Target } from "@repro/events";
import type { Projection } from "../projection";

export type CheckResult = "passed" | "flagged" | "unassessed" | "pending";

export interface CheckEntry {
  readonly seq: number;
  readonly kind: CheckKind;
  readonly target: Target | null;
  /** Evidence the check rests on; verdicts that cite any of these resolve it. */
  readonly evidence: readonly string[];
  /** The result before any verdict (from envelope status and payload). */
  readonly base: CheckResult;
  result: CheckResult;
}

export interface CheckCounts {
  checks: number;
  passed: number;
  flagged: number;
  unassessed: number;
  pending: number;
}

export interface ChecksState {
  list: CheckEntry[];
  /** Evidence id → indices into `list` of the checks resting on it. */
  byEvidence: Map<string, number[]>;
  supported: Set<string>;
  contradicted: Set<string>;
  /** True once review is over: pending checks with no supporting verdict become flagged. */
  reviewClosed: boolean;
  counts: CheckCounts;
}

export type CheckKind =
  | "diff.outcome"
  | "diff.tests"
  | "diff.behaviour"
  | "diff.probe"
  | "diff.api"
  | "diff.deps"
  | "diff.perf"
  | "invariant.result";

type CheckEvent = Extract<ReproEvent, { kind: CheckKind }>;

/** The result-bearing event kinds (ADR-0015 §1). */
export const CHECK_KINDS: readonly CheckKind[] = [
  "diff.outcome",
  "diff.tests",
  "diff.behaviour",
  "diff.probe",
  "diff.api",
  "diff.deps",
  "diff.perf",
  "invariant.result",
];

const CHECK_KIND_SET: ReadonlySet<string> = new Set(CHECK_KINDS);

export const isCheckEvent = (event: ReproEvent): event is CheckEvent =>
  CHECK_KIND_SET.has(event.kind);

/** Payloads that say the check could not be compared (ADR-0015 §3). */
function notAssessable(event: CheckEvent): boolean {
  switch (event.kind) {
    case "diff.outcome":
      return ["flaky", "modified", "F2F", "removed"].includes(event.payload.class);
    case "diff.behaviour":
      return event.payload.stability === "unstable";
    case "diff.perf":
      return event.payload.verdict === "not_assessable";
    case "invariant.result":
      return event.payload.result === "not_evaluated";
    default:
      return false;
  }
}

export function baseResult(event: CheckEvent): CheckResult {
  if (notAssessable(event)) return "unassessed";
  if (event.status === "ok") return "passed";
  if (event.status === "fail") return "flagged";
  return "pending";
}

function evidenceOf(event: CheckEvent): string[] {
  return event.kind === "invariant.result"
    ? [...event.payload.evidence_ids]
    : [event.payload.evidence_id];
}

function resolve(state: ChecksState, entry: CheckEntry): CheckResult {
  if (entry.base !== "pending") return entry.base;
  if (entry.evidence.some((id) => state.contradicted.has(id))) return "flagged";
  if (entry.evidence.some((id) => state.supported.has(id))) return "passed";
  return state.reviewClosed ? "flagged" : "pending";
}

function reresolve(state: ChecksState, entry: CheckEntry): void {
  const next = resolve(state, entry);
  if (next === entry.result) return;
  state.counts[entry.result]--;
  state.counts[next]++;
  entry.result = next;
}

export const checksProjection: Projection<ChecksState> = {
  name: "checks",
  init: () => ({
    list: [],
    byEvidence: new Map(),
    supported: new Set(),
    contradicted: new Set(),
    reviewClosed: false,
    counts: { checks: 0, passed: 0, flagged: 0, unassessed: 0, pending: 0 },
  }),
  apply(state, event) {
    if (isCheckEvent(event)) {
      const base = baseResult(event);
      const entry: CheckEntry = {
        seq: event.seq,
        kind: event.kind,
        target: event.target,
        evidence: evidenceOf(event),
        base,
        result: base,
      };
      entry.result = resolve(state, entry);
      const index = state.list.push(entry) - 1;
      for (const id of entry.evidence) {
        const list = state.byEvidence.get(id);
        if (list === undefined) state.byEvidence.set(id, [index]);
        else list.push(index);
      }
      state.counts.checks++;
      state.counts[entry.result]++;
      return state;
    }
    switch (event.kind) {
      case "verdict.issued": {
        const { verdict, cited_evidence: cited } = event.payload.verdict;
        if (verdict === "unverifiable") return state;
        const set = verdict === "supported" ? state.supported : state.contradicted;
        for (const id of cited) {
          set.add(id);
          for (const index of state.byEvidence.get(id) ?? []) {
            const entry = state.list[index];
            if (entry !== undefined) reresolve(state, entry);
          }
        }
        return state;
      }
      case "stage.finished":
      case "stage.started":
      case "run.finished": {
        // Review is over when it finishes, or when the run reaches the card stage or ends
        // without one (deterministic-only runs have no review stage).
        const closes =
          event.kind === "run.finished" ||
          (event.kind === "stage.finished" && event.stage === "review") ||
          (event.kind === "stage.started" && event.stage === "card");
        if (closes && !state.reviewClosed) {
          state.reviewClosed = true;
          for (const entry of state.list) if (entry.result === "pending") reresolve(state, entry);
        }
        return state;
      }
      default:
        return state;
    }
  },
};
