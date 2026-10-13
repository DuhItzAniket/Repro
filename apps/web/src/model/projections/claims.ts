/** Claims and their verdicts (index rows, card claims section). */
import type { ClaimKind, Target, VerdictAgreement, VerdictValue } from "@repro/events";
import type { Projection } from "../projection";

export interface ClaimView {
  readonly id: string;
  readonly kind: ClaimKind;
  readonly text: string;
  readonly targets: readonly Target[];
  readonly seq: number;
  verdict: VerdictValue | null;
  cited: string[];
  agreement: VerdictAgreement | null;
  /** Reviewer agent that issued the verdict. */
  agent: string | null;
  /** Verdict attempts that failed validation (`verdict.rejected`). */
  rejections: number;
}

export interface ClaimsState {
  list: ClaimView[];
  byId: Map<string, number>;
}

export const claimsProjection: Projection<ClaimsState> = {
  name: "claims",
  init: () => ({ list: [], byId: new Map() }),
  apply(state, event) {
    switch (event.kind) {
      case "claim.extracted": {
        const { id, kind, text, targets } = event.payload.claim;
        if (state.byId.has(id)) return state;
        state.byId.set(id, state.list.length);
        state.list.push({
          id,
          kind,
          text,
          targets,
          seq: event.seq,
          verdict: null,
          cited: [],
          agreement: null,
          agent: null,
          rejections: 0,
        });
        return state;
      }
      case "verdict.issued": {
        const v = event.payload.verdict;
        const claim = state.list[state.byId.get(v.claim_id) ?? -1];
        if (claim !== undefined) {
          claim.verdict = v.verdict;
          claim.cited = [...v.cited_evidence];
          claim.agreement = v.agreement;
          claim.agent = event.agent;
        }
        return state;
      }
      case "verdict.rejected": {
        const claim = state.list[state.byId.get(event.payload.claim_id) ?? -1];
        if (claim !== undefined) claim.rejections++;
        return state;
      }
      default:
        return state;
    }
  },
};
