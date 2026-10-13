import { KIND_STAGES, type ReproEvent } from "@repro/events";
import { validator } from "@repro/events/testing";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { toJsonl } from "./jsonl";
import { DEMO, FIXTURE_SEED, STRESS } from "./profiles";
import { generateRun, type SyntheticRun } from "./scenario";

const validateEvent = validator("event.schema.json");
const demo = generateRun(DEMO, FIXTURE_SEED);
const stress = generateRun(STRESS, FIXTURE_SEED);

type Of<K extends ReproEvent["kind"]> = Extract<ReproEvent, { kind: K }>;
const ofKind = <K extends ReproEvent["kind"]>(events: readonly ReproEvent[], kind: K): Of<K>[] =>
  events.filter((e): e is Of<K> => e.kind === kind);

/** Evidence ids an event cites (mirrors `_cited_evidence` in repro_events/log.py). */
function cited(event: ReproEvent): string[] {
  switch (event.kind) {
    case "verdict.issued":
      return [
        ...event.payload.verdict.cited_evidence,
        ...event.payload.verdict.quotes.map((q) => q.evidence_id),
      ];
    case "invariant.result":
      return event.payload.evidence_ids;
    case "diff.outcome":
    case "diff.tests":
    case "diff.behaviour":
    case "diff.probe":
    case "diff.api":
    case "diff.deps":
    case "diff.perf":
      return [event.payload.evidence_id];
    default:
      return [];
  }
}

/** Log-level invariants of ADR-0002, the same ones `repro-events validate` enforces in Python. */
function logIssues(events: readonly ReproEvent[]): string[] {
  const issues: string[] = [];
  const ids = new Set<string>();
  const evidence = new Set<string>();
  let previousTs = "";
  const runId = events[0]?.run_id;
  events.forEach((event, i) => {
    const at = `seq ${event.seq} (${event.kind})`;
    if (event.seq !== i + 1) issues.push(`${at}: expected seq ${i + 1}`);
    if (event.run_id !== runId) issues.push(`${at}: run_id differs`);
    if (ids.has(event.id)) issues.push(`${at}: duplicate id`);
    if (event.parent != null && !ids.has(event.parent)) issues.push(`${at}: parent is not earlier`);
    ids.add(event.id);
    if (event.ts < previousTs) issues.push(`${at}: timestamp goes backwards`);
    previousTs = event.ts;
    if (!(KIND_STAGES[event.kind] as readonly string[]).includes(event.stage)) {
      issues.push(`${at}: stage ${event.stage} not allowed`);
    }
    for (const id of cited(event)) {
      if (!evidence.has(id)) issues.push(`${at}: cites ${id} before it exists`);
    }
    if (event.kind === "evidence.created") {
      evidence.add(event.payload.evidence.id);
      if (event.payload.evidence.seq !== event.seq) {
        issues.push(`${at}: evidence.seq is not its event's seq`);
      }
    }
  });
  if (events[0]?.kind !== "run.started") issues.push("first event is not run.started");
  if (events.at(-1)?.kind !== "run.finished") issues.push("last event is not run.finished");
  return issues;
}

const CHECK_KINDS = new Set([
  "diff.outcome",
  "diff.tests",
  "diff.behaviour",
  "diff.probe",
  "diff.api",
  "diff.deps",
  "diff.perf",
  "invariant.result",
]);

/**
 * An independent recount of the check model (ADR-0015) from events alone: what the header
 * counters and the index footer must show once the run has finished.
 */
function recountChecks(events: readonly ReproEvent[]) {
  const explained = new Set<string>();
  for (const v of ofKind(events, "verdict.issued")) {
    if (v.payload.verdict.verdict === "supported") {
      for (const id of v.payload.verdict.cited_evidence) explained.add(id);
    }
  }
  const counts = { checks: 0, passed: 0, flagged: 0, unassessed: 0 };
  for (const e of events) {
    if (!CHECK_KINDS.has(e.kind)) continue;
    counts.checks++;
    const notAssessable =
      (e.kind === "diff.outcome" &&
        ["flaky", "modified", "F2F", "removed"].includes(e.payload.class)) ||
      (e.kind === "diff.behaviour" && e.payload.stability === "unstable") ||
      (e.kind === "diff.perf" && e.payload.verdict === "not_assessable") ||
      (e.kind === "invariant.result" && e.payload.result === "not_evaluated");
    if (notAssessable) counts.unassessed++;
    else if (e.status === "ok") counts.passed++;
    else if (e.status === "fail") counts.flagged++;
    else {
      // warn: a difference that needs a supported claim to explain it.
      const ids = cited(e);
      if (ids.some((id) => explained.has(id))) counts.passed++;
      else counts.flagged++;
    }
  }
  return counts;
}

function maxInWindow(times: readonly number[], windowMs: number): number {
  let best = 0;
  for (let i = 0, j = 0; i < times.length; i++) {
    while ((times[i] as number) - (times[j] as number) >= windowMs) j++;
    best = Math.max(best, i - j + 1);
  }
  return best;
}

describe.each([
  ["demo", demo],
  ["stress", stress],
] as const)("%s run", (_name, run: SyntheticRun) => {
  const { events, summary } = run;

  it("is byte-identical for the same seed and differs for another seed", () => {
    expect(toJsonl(generateRun(run.profile, FIXTURE_SEED).events)).toBe(toJsonl(events));
    expect(toJsonl(generateRun(run.profile, FIXTURE_SEED + 1).events)).not.toBe(toJsonl(events));
  });

  it("validates against the event schema (Ajv, draft 2020-12)", () => {
    const errors: string[] = [];
    for (const e of events) {
      const valid: boolean = validateEvent(e); // a plain boolean: Ajv's type guard would narrow `e`
      if (!valid) errors.push(`${e.seq} ${e.kind}: ${JSON.stringify(validateEvent.errors)}`);
    }
    expect(errors.slice(0, 3)).toEqual([]);
  });

  it("satisfies the log invariants", () => {
    expect(logIssues(events)).toEqual([]);
  });

  it("references only graph nodes that exist", () => {
    const nodes = new Set(ofKind(events, "graph.node").map((e) => e.payload.node.id));
    const dangling = [
      ...ofKind(events, "graph.edge").flatMap((e) => [e.payload.source, e.payload.target]),
      ...ofKind(events, "test.selected").map((e) => e.target?.test ?? ""),
      ...ofKind(events, "trace.sample").map((e) => e.payload.symbol_id),
      ...ofKind(events, "blast.computed").flatMap((e) =>
        e.payload.affected.map((a) => a.symbol_id),
      ),
    ].filter((id) => !nodes.has(id));
    expect(dangling).toEqual([]);
  });

  it("quotes only text that appears in the cited evidence", () => {
    const summaries = new Map(
      ofKind(events, "evidence.created").map((e) => [
        e.payload.evidence.id,
        e.payload.evidence.summary,
      ]),
    );
    for (const v of ofKind(events, "verdict.issued")) {
      for (const q of v.payload.verdict.quotes) {
        expect(summaries.get(q.evidence_id)).toContain(q.text);
      }
    }
  });

  it("reports counts that match an independent recount of its events", () => {
    const moduleFiles = new Set(
      ofKind(events, "graph.node")
        .filter((e) => e.payload.node.type === "module")
        .map((e) => e.payload.node.file),
    );
    const finished = ofKind(events, "run.finished")[0];
    const card = ofKind(events, "card.published")[0];
    const verdicts = ofKind(events, "verdict.issued").map((e) => e.payload.verdict.verdict);
    expect({
      events: events.length,
      claims: ofKind(events, "claim.extracted").length,
      agents: new Set(ofKind(events, "agent.spawned").map((e) => e.agent)).size,
      files: moduleFiles.size,
      graphNodes: ofKind(events, "graph.node").length,
      graphEdges: ofKind(events, "graph.edge").length,
      selectedTests: ofKind(events, "test.selected").length,
      ...recountChecks(events),
      evidence: ofKind(events, "evidence.created").length,
      missing: ofKind(events, "missing.recorded").length,
    }).toEqual({
      events: summary.events,
      claims: summary.claims,
      agents: summary.agents,
      files: summary.files,
      graphNodes: summary.graphNodes,
      graphEdges: summary.graphEdges,
      selectedTests: summary.selectedTests,
      checks: summary.checks,
      passed: summary.passed,
      flagged: summary.flagged,
      unassessed: summary.unassessed,
      evidence: summary.evidence,
      missing: summary.missing,
    });
    expect(finished?.payload.counts).toEqual({
      events: events.length,
      evidence: summary.evidence,
      missing: summary.missing,
    });
    expect(card?.payload).toEqual(summary.card);
    expect(card?.payload.counts).toMatchObject({
      claims: summary.claims,
      supported: verdicts.filter((v) => v === "supported").length,
      contradicted: verdicts.filter((v) => v === "contradicted").length,
      unverifiable: verdicts.filter((v) => v === "unverifiable").length,
      missing: summary.missing,
      invariants_failed: ofKind(events, "invariant.result").filter(
        (e) => e.payload.result === "fail",
      ).length,
    });
  });

  it("uses one dispatch slot per agent, all within the UI's 12", () => {
    const slots = ofKind(events, "agent.spawned").map((e) => e.payload.slot);
    expect(new Set(slots).size).toBe(slots.length);
    expect(Math.max(...slots)).toBeLessThan(12);
  });

  it("runs every stage once, in order", () => {
    expect(ofKind(events, "stage.started").map((e) => e.payload.index)).toEqual([
      0, 1, 2, 3, 4, 5, 6,
    ]);
    expect(ofKind(events, "stage.finished").map((e) => e.stage)).toEqual([
      "read",
      "build",
      "run",
      "diff",
      "check",
      "review",
      "card",
    ]);
  });
});

describe("demo profile matches the B01 spec", () => {
  it("1 PR, 4 claims, 12 agents, about 150 files, 28 checks, 4 flagged, 2–4k events", () => {
    const s = demo.summary;
    expect(ofKind(demo.events, "run.started")[0]?.payload.pr?.number).toBeTypeOf("number");
    expect([s.claims, s.agents, s.checks, s.flagged]).toEqual([4, 12, 28, 4]);
    expect(s.files).toBeGreaterThanOrEqual(140);
    expect(s.files).toBeLessThanOrEqual(160);
    expect(s.events).toBeGreaterThanOrEqual(2000);
    expect(s.events).toBeLessThanOrEqual(4000);
    expect(s.card.status).toBe("FLAGGED");
  });
});

describe("stress profile matches the B01 spec", () => {
  it("has 10k graph edges", () => {
    expect(ofKind(stress.events, "graph.edge")).toHaveLength(10_000);
  });

  it("has a burst of at least 2k execution events within one second", () => {
    const exec = new Set(["test.started", "test.finished", "trace.sample", "perf.sample"]);
    const times = stress.events.filter((e) => exec.has(e.kind)).map((e) => Date.parse(e.ts));
    expect(maxInWindow(times, 1000)).toBeGreaterThanOrEqual(2000);
  });
});

describe("any seed", () => {
  it("gives a valid run with the demo's spec counts", () => {
    fc.assert(
      fc.property(fc.nat({ max: 2 ** 32 - 1 }), (seed) => {
        const run = generateRun(DEMO, seed);
        expect(logIssues(run.events)).toEqual([]);
        expect(recountChecks(run.events)).toEqual({
          checks: 28,
          passed: 20,
          flagged: 4,
          unassessed: 4,
        });
      }),
      { numRuns: 15 },
    );
  });
});
