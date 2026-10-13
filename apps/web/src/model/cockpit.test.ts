import type { ReproEvent } from "@repro/events";
import { DEMO, FIXTURE_SEED, generateRun } from "@repro/synth";
import { describe, expect, it } from "vitest";
import {
  CockpitModel,
  type CockpitState,
  cockpitProjection,
  headerCounters,
  indexFooter,
  indexFooterText,
  stageProgress,
} from "./cockpit";
import { Folder } from "./folder";
import { linearFold, renumber, runEvents, storeOf } from "./test-support";

const run = generateRun(DEMO, FIXTURE_SEED);
const model = new CockpitModel();
model.ingest(run.events);
const final = model.folder.stateAt(model.store.length);

describe("cockpit projections on the demo run", () => {
  it("agree with the generator's independently recounted plan", () => {
    const s = run.summary;
    expect(headerCounters(final)).toEqual({
      claims: s.claims,
      agents: s.agents,
      files: s.files,
      checks: s.checks,
      flagged: s.flagged,
    });
    expect({ ...indexFooter(final) }).toEqual({
      checks: s.checks,
      passed: s.passed,
      flagged: s.flagged,
      unassessed: s.unassessed,
      pending: 0,
    });
    expect(indexFooterText(indexFooter(final))).toBe(
      "28 checks / 20 passed / 4 flagged / 4 unassessed",
    );
    expect(final.summary).toMatchObject({
      graphNodes: s.graphNodes,
      graphEdges: s.graphEdges,
      selectedTests: s.selectedTests,
      evidence: s.evidence,
      missing: s.missing,
    });
  });

  it("ends with every stage done, the card FLAGGED and verdicts on all claims", () => {
    expect(stageProgress(final).map((stage) => stage.state)).toEqual(Array(7).fill("done"));
    expect(final.run).toMatchObject({ outcome: "completed", cardStatus: "FLAGGED", active: -1 });
    expect(final.run.card?.counts).toEqual(run.summary.card.counts);
    expect(final.claims.list.map((c) => [c.id, c.verdict, c.rejections])).toEqual([
      ["C1", "supported", 0],
      ["C2", "supported", 1],
      ["C3", "contradicted", 0],
      ["C4", "supported", 0],
    ]);
    expect(final.claims.list[2]?.agreement).toEqual({ runs: 2, agreeing: 2 });
    expect(final.agents.slots).toHaveLength(12);
    expect([...final.agents.byId.values()].every((a) => a.state === "done")).toBe(true);
    expect(final.agents.byId.get("a08")?.verdicts.contradicted).toBe(1);
    expect(final.run.sandboxes.head).toEqual({
      level: "L3",
      network: "enforced",
      backend: "docker",
    });
  });

  it("header counters and index footer read one projection and agree at every cursor", () => {
    const folder = new Folder(model.store, cockpitProjection, 128);
    let previousFlagged = 0;
    let previousChecks = 0;
    for (let k = 0; k <= model.store.length; k++) {
      const state: CockpitState = folder.stateAt(k);
      const header = headerCounters(state);
      const footer = indexFooter(state);
      expect(footer).toBe(state.checks.counts); // the very same object
      expect([header.checks, header.flagged]).toEqual([footer.checks, footer.flagged]);
      expect(footer.passed + footer.flagged + footer.unassessed + footer.pending).toBe(
        footer.checks,
      );
      // ADR-0015: FLAGGED and CHECKS never go down during a run.
      expect(footer.flagged).toBeGreaterThanOrEqual(previousFlagged);
      expect(footer.checks).toBeGreaterThanOrEqual(previousChecks);
      previousFlagged = footer.flagged;
      previousChecks = footer.checks;
    }
  });

  it("resolves pending checks only through verdicts and the end of review", () => {
    const seqOf = (predicate: (e: ReproEvent) => boolean): number =>
      run.events.find(predicate)?.seq ?? Number.NaN;
    const reviewStart = seqOf((e) => e.kind === "stage.started" && e.stage === "review");
    const verdict = (claim: string) =>
      seqOf((e) => e.kind === "verdict.issued" && e.payload.verdict.claim_id === claim);
    const behaviour = (symbol: string) =>
      seqOf((e) => e.kind === "diff.behaviour" && e.payload.symbol_id.includes(symbol));
    const resultAt = (cursor: number, checkSeq: number) =>
      model.folder.stateAt(cursor).checks.list.find((c) => c.seq === checkSeq)?.result;
    // Before review, three differences await a claim: two behaviour diffs and the new dependency.
    expect({ ...model.folder.stateAt(reviewStart).checks.counts }).toEqual({
      checks: 28,
      passed: 18,
      flagged: 3,
      unassessed: 4,
      pending: 3,
    });
    const parse = behaviour("parse_date");
    const fmt = behaviour("format_duration");
    expect(resultAt(verdict("C1") - 1, parse)).toBe("pending");
    expect(resultAt(verdict("C1"), parse)).toBe("passed"); // C1 (supported) cites it
    expect(resultAt(verdict("C3") - 1, fmt)).toBe("pending");
    expect(resultAt(verdict("C3"), fmt)).toBe("flagged"); // C3 (contradicted) cites it
    expect(model.folder.stateAt(model.store.length).checks.counts.pending).toBe(0);
  });

  it("is a projection of time: the run stage is active while tests run", () => {
    const firstTest = run.events.find((e) => e.kind === "test.started");
    const t = model.store.time[(firstTest?.seq ?? 1) - 1] as number;
    const { state } = model.stateAtTime(t);
    expect(state.run.active).toBe(2);
    expect(stageProgress(state).map((s) => s.state)).toEqual([
      "done",
      "done",
      "active",
      "pending",
      "pending",
      "pending",
      "pending",
    ]);
  });
});

describe("tolerance", () => {
  it("ignores unknown kinds and unsupported payload versions", () => {
    const demo = runEvents();
    const noise = [
      { ...(demo[5] as object), kind: "future.kind", payload: { anything: true } },
      { ...(demo[200] as object), pv: 9 },
    ];
    const mixed = renumber([
      ...demo.slice(0, 100),
      noise[0] as object,
      ...demo.slice(100, 900),
      noise[1] as object,
      ...demo.slice(900),
    ]);
    const store = storeOf(mixed);
    expect(store.unknownCount).toBe(2);
    const state = linearFold(store, cockpitProjection, store.length);
    const reference = linearFold(storeOf(demo), cockpitProjection, demo.length);
    // seq numbers shift by the inserted events, so compare everything that does not record seqs.
    expect(headerCounters(state)).toEqual(headerCounters(reference));
    expect(indexFooter(state)).toEqual(indexFooter(reference));
    expect(state.summary.events).toBe(reference.summary.events);
    expect(state.claims.list.map((c) => c.verdict)).toEqual(
      reference.claims.list.map((c) => c.verdict),
    );
  });

  it("closes review at the card stage when a run has no review stage", () => {
    const demo = runEvents();
    const withoutReview = renumber(
      demo.filter(
        (e) => e.stage !== "review" || e.kind === "log.line", // keep the feed; drop the stage, agents and verdicts
      ),
    );
    const state = linearFold(storeOf(withoutReview), cockpitProjection, withoutReview.length);
    // With no verdicts, every difference needing a claim is unexplained and flagged.
    expect(state.checks.counts).toEqual({
      checks: 28,
      passed: 18,
      flagged: 6,
      unassessed: 4,
      pending: 0,
    });
  });
});
