// F05: the Reproduction Card in the drawer, from the run's card.published payload.
import type { CardPublishedPayload, ReproductionCard } from "@repro/events";
import { describe, expect, it } from "vitest";
import { cardView, STATUS_LINE, verifiedWhy } from "./card";

const EV = "ev_01JBAAHWY0000000000000VBKN";
const OTHER = "ev_01JBAAHWY0000000000000VBKP";

const CARD: ReproductionCard = {
  card_version: 1,
  run_id: "run_01JBAAHWY00000000000003E08",
  status: "FLAGGED",
  repo: { name: "demo", url: null },
  pr: null,
  conditions: {
    base: { ref: "main", sha: "a".repeat(40) },
    head: { ref: "fix", sha: "b".repeat(40) },
    python_version: "3.13.13",
    platform: "linux",
    isolation_level: "L3",
    network: "enforced",
    lock_sha256: { base: null, head: null },
    selected_tests: 2,
    seeds: { hash_seed: 0, hash_seed_repeat: 1 },
    repro_version: "0.6.0",
    models: [],
  },
  claims: [],
  verdicts: [],
  status_reasons: [
    {
      rule: "gap_flagged",
      detail: "1 diff.behaviour flagged (result_changed)",
      evidence_ids: [EV],
      targets: [],
      decides: true,
    },
    {
      rule: "invariant_not_evaluated",
      detail: "invariants not evaluated: perf_budget",
      evidence_ids: [],
      targets: [],
      decides: false,
    },
  ],
  gap: [
    {
      evidence_id: EV,
      type: "behaviour_diff",
      check: "diff.behaviour",
      kind: "result_changed",
      summary: "result_changed: f in test_f",
      origin: "introduced",
      stability: "stable",
      resolution: "flagged",
      explained_by: [],
    },
    {
      evidence_id: OTHER,
      type: "test_outcome",
      check: "diff.outcome",
      kind: "F2P",
      summary: "F2P: test_g",
      origin: "introduced",
      stability: "stable",
      resolution: "passed",
      explained_by: ["C1"],
    },
  ],
  invariants: [
    {
      name: "perf_budget",
      result: "not_evaluated",
      message: "the tests were not timed",
      evidence_ids: [],
    },
  ],
  missing: [
    {
      reason: "perf_not_assessable",
      targets: [{ test: "tests/test_a.py::test_f" }],
      detail: "too fast to time",
      resolution: null,
    },
  ],
  replay: { event_log_sha256: "c".repeat(64), event_count: 90 },
  generated_at: "2026-10-15T10:00:00.000Z",
};

const PAYLOAD: CardPublishedPayload = {
  status: "FLAGGED",
  card_sha256: "d".repeat(64),
  counts: {
    claims: 0,
    supported: 0,
    contradicted: 0,
    unverifiable: 0,
    gap_items: 2,
    unexplained: 1,
    missing: 1,
    invariants_failed: 0,
  },
  card: CARD,
};

describe("the card in the drawer", () => {
  it("says when the run has published no card yet", () => {
    expect(cardView(null, () => null)).toEqual({
      title: "Reproduction Card",
      subtitle: "not published yet",
      sections: [],
    });
  });

  it("shows status, reasons, gap, invariants, missing items, conditions and replay", () => {
    const view = cardView(PAYLOAD, (id) => (id === EV ? 7 : null));
    expect(view.title).toBe("Reproduction Card · FLAGGED");
    expect(view.subtitle).toBe(STATUS_LINE.FLAGGED);
    expect(view.sections.map((s) => s.title)).toEqual([
      "Status",
      "Why",
      "Also not checked",
      "Claims",
      "Gap",
      "Invariants",
      "Missing",
      "Conditions",
      "Replay",
    ]);
    const why = view.sections.find((s) => s.title === "Why");
    expect(why?.paragraphs).toEqual(["1 diff.behaviour flagged (result_changed) (gap flagged)"]);
    const gap = view.sections.find((s) => s.title === "Gap")?.table;
    expect(gap?.columns).toEqual(["Difference", "Result"]); // two columns fit the drawer
    expect(gap?.rows.map((r) => r.cells[1])).toEqual([
      "flagged: result_changed: f in test_f",
      "passed (by C1): F2P: test_g",
    ]);
    // A gap item links to the check that reported it, when the cockpit has it.
    expect(gap?.rows.map((r) => r.focus)).toEqual([{ kind: "check", index: 7 }, undefined]);
    const invariants = view.sections.find((s) => s.title === "Invariants")?.table;
    expect(invariants?.rows[0]?.cells).toEqual([
      "perf_budget",
      "not_evaluated: the tests were not timed",
    ]);
    const missing = view.sections.find((s) => s.title === "Missing")?.table;
    expect(missing?.rows[0]?.cells).toEqual(["perf_not_assessable", "too fast to time"]);
    const conditions = view.sections.find((s) => s.title === "Conditions")?.facts;
    expect(conditions?.find((f) => f.label === "Hash seeds (A, A2)")?.value).toBe("0, 1");
    expect(conditions?.find((f) => f.label === "Lock, base")?.value).toBe("—");
  });

  it("notes only what is unusual about a gap item", () => {
    const item = CARD.gap[1];
    if (item === undefined) throw new Error("no second gap item");
    const card = {
      ...CARD,
      gap: [
        {
          ...item,
          explained_by: [],
          origin: "pre-existing" as const,
          stability: "unstable" as const,
        },
      ],
    };
    const view = cardView({ ...PAYLOAD, card }, () => null);
    const gap = view.sections.find((s) => s.title === "Gap")?.table;
    expect(gap?.rows[0]?.cells[1]).toBe("passed (pre-existing, unstable): F2P: test_g");
  });

  it("says everything was checked only when nothing is missing (H06)", () => {
    const verified = { ...CARD, status: "VERIFIED" as const, status_reasons: [] };
    expect(verifiedWhy({ ...verified, missing: [] })).toBe(
      "Nothing flags, and everything was checked.",
    );
    expect(verifiedWhy(verified)).toContain("under Missing");
  });

  it("shows what a payload without its card holds", () => {
    const { card: _card, ...bare } = PAYLOAD;
    const view = cardView(bare, () => null);
    expect(view.sections.map((s) => s.title)).toEqual(["Status", "Card"]);
    expect(view.sections[0]?.facts?.find((f) => f.label === "Unexplained")?.value).toBe("1");
  });
});
