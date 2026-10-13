import { effect } from "@preact/signals";
import { describe, expect, it } from "vitest";
import { CockpitModel, headerCounters } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { createShellView } from "./view";

const model = new CockpitModel();
model.ingest(runEvents());
const n = model.store.length;

describe("shell view", () => {
  it("counters update from the fixture and end at the run's totals", () => {
    const view = createShellView();
    const seen: number[][] = [];
    const stop = effect(() => {
      const c = view.counters.value;
      seen.push([c.claims, c.agents, c.files, c.checks, c.flagged]);
    });
    for (let k = 0; k <= n; k++) view.update(model.folder.stateAt(k));
    stop();
    expect(seen[0]).toEqual([0, 0, 0, 0, 0]);
    expect(seen.at(-1)).toEqual([4, 12, 147, 28, 4]);
    // Written only on change: far fewer writes than updates, and each write differs.
    expect(seen.length).toBeLessThan(400);
    for (let i = 1; i < seen.length; i++) expect(seen[i]).not.toEqual(seen[i - 1]);
    // Counters never go down during a run.
    for (let i = 1; i < seen.length; i++) {
      for (const [j, value] of (seen[i] ?? []).entries()) {
        expect(value).toBeGreaterThanOrEqual(seen[i - 1]?.[j] ?? 0);
      }
    }
  });

  it("stage segments step through pending → active → done in pipeline order", () => {
    const view = createShellView();
    const snapshots: string[] = [];
    const stop = effect(() => {
      snapshots.push(view.stages.value.map((s) => s.state[0]).join(""));
    });
    for (let k = 0; k <= n; k++) view.update(model.folder.stateAt(k));
    stop();
    expect(snapshots).toContain("ddapppp");
    expect(snapshots.at(-1)).toBe("ddddddd");
    // Never two active stages, never a later stage done before an earlier one.
    for (const s of snapshots.slice(1)) {
      expect(s.split("a").length - 1).toBeLessThanOrEqual(1);
      expect(s).toMatch(/^d*a?p*$/);
    }
  });

  it("labels the run and keeps the footer in step with the header", () => {
    const view = createShellView();
    for (let k = 0; k <= n; k += 50) {
      const state = model.folder.stateAt(k);
      view.update(state);
      const { checks, flagged } = headerCounters(state);
      expect(view.indexFooter.value.startsWith(`${checks} checks /`)).toBe(true);
      expect(view.indexFooter.value).toContain(`/ ${flagged} flagged`);
    }
    view.update(model.folder.stateAt(n));
    expect(view.run.value).toEqual({
      repo: "synthetic/timekeeper",
      pr: "#128 Normalise timezone handling and speed up recurrence expansion",
      cardStatus: "FLAGGED",
    });
    expect(view.finished.value).toBe(true);
    expect(view.indexFooter.value).toBe("28 checks / 20 passed / 4 flagged / 4 unassessed");
  });
});
