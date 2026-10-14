import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "./model/cockpit";
import { parseJsonl } from "./model/jsonl";
import { summarise } from "./test-hook";

const DEMO = new URL("../fixtures/demo-run.jsonl", import.meta.url);

describe("summarise (the gates' view of the cockpit)", () => {
  const model = new CockpitModel();
  model.ingest(parseJsonl(readFileSync(DEMO, "utf8")).values);
  const summary = summarise(model, "replay");

  it("counts the index's checks as the header does", () => {
    const { results } = summary.panels.index;
    expect(results).toHaveLength(summary.counters.checks);
    expect(results.filter((r) => r === "flagged")).toHaveLength(summary.counters.flagged);
  });

  it("lists every settled run in its Execution lane", () => {
    const finished = model.tests.runs.filter((run) => run.finished >= 0);
    const { base, base_repeat, head } = summary.panels.execution;
    expect(base.runs + base_repeat.runs + head.runs).toBe(finished.length);
    const failedOnHead = new Set(
      finished
        .filter(
          (run) =>
            run.side === "head" && !["passed", "xfailed", "skipped"].includes(run.outcome ?? ""),
        )
        .map((run) => run.test),
    );
    expect(head.failed).toEqual([...failedOnHead].sort());
  });

  it("has a Change routes row per changed symbol", () => {
    expect(summary.panels.routes).toHaveLength(model.changes.changed.length);
  });
});
