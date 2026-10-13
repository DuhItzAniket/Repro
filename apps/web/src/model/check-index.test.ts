import { describe, expect, it } from "vitest";
import { type CheckIndexView, checkIndex } from "./check-index";
import { CockpitModel, headerCounters, indexFooter } from "./cockpit";
import type { CheckResult } from "./projections/checks";
import { runEvents } from "./test-support";

const model = new CockpitModel();
model.ingest(runEvents());
const at = (cursor: number): CheckIndexView =>
  checkIndex(model.folder.stateAt(cursor), model.changes, cursor);

describe("change×check index", () => {
  it("counts the same results as the footer and header at every cursor (single projection)", () => {
    for (let k = 0; k <= model.store.length; k += 7) {
      const view = at(k);
      const state = model.folder.stateAt(k);
      const counts: Record<CheckResult, number> = {
        passed: 0,
        flagged: 0,
        unassessed: 0,
        pending: 0,
      };
      for (const result of view.results) counts[result]++;
      const footer = indexFooter(state);
      expect({ checks: view.results.length, ...counts }).toEqual({ ...footer });
      const header = headerCounters(state);
      expect([header.checks, header.flagged]).toEqual([view.results.length, counts.flagged]);
    }
  });

  it("puts every check in at least one row, and only unrelated checks in 'other'", () => {
    const view = at(model.store.length);
    const covered = new Set(view.rows.flatMap((r) => r.checks));
    expect(covered.size).toBe(view.results.length);
    const other = view.rows.find((r) => r.kind === "other");
    const elsewhere = new Set(view.rows.filter((r) => r.kind !== "other").flatMap((r) => r.checks));
    for (const i of other?.checks ?? []) expect(elsewhere.has(i)).toBe(false);
  });

  it("rows the demo's claims and unclaimed changes with their status", () => {
    const view = at(model.store.length);
    expect(view.rows.map((r) => [r.label, r.status])).toEqual([
      ["C1 fix", "verified"],
      ["C2 perf", "flagged"], // a covering test gained a skip
      ["C3 refactor", "flagged"], // contradicted
      ["C4 deps", "flagged"], // violates the no-new-dependencies invariant
      ["_split_iso", "review"],
      ["fmt.py", "review"],
      ["_by_month", "flagged"],
      ["_fold_offset", "review"],
      ["other", "verified"],
    ]);
  });

  it("relates a claim to checks its verdict cites, even with no shared target", () => {
    const view = at(model.store.length);
    const state = model.folder.stateAt(model.store.length);
    const c4 = view.rows.find((r) => r.id === "C4");
    const kinds = c4?.checks.map((i) => state.checks.list[i]?.kind);
    expect(kinds).toContain("invariant.result");
    expect(kinds).toContain("diff.deps");
  });

  it("relates a check that names a symbol only to rows covering that symbol", () => {
    const view = at(model.store.length);
    const state = model.folder.stateAt(model.store.length);
    for (const row of view.rows) {
      if (row.kind !== "change") continue;
      for (const i of row.checks) {
        const symbol = state.checks.list[i]?.target?.symbol;
        if (symbol !== undefined)
          expect(row.label === "fmt.py" || symbol.includes(row.label)).toBe(true);
      }
    }
  });

  it("before verdicts, flags a claim only through a check flagged on its own", () => {
    const beforeVerdicts = model.kinds.lastIndex("diff.perf", model.store.length) + 1;
    const view = at(beforeVerdicts);
    expect(view.rows.filter((r) => r.kind === "claim").map((r) => r.status)).toEqual([
      "review",
      "flagged", // C2: the skip-added check is flagged on its own
      "flagged", // C3: the P2F outcome is flagged on its own
      "review",
    ]);
  });
});
