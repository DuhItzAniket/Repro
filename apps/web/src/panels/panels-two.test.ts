import { readFileSync } from "node:fs";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { parseJsonl } from "../model/jsonl";
import { runEvents } from "../model/test-support";
import { columnRanges, indexPanel, MIN_PITCH } from "./check-index";
import { dispatchPanel, SLOTS } from "./dispatch";
import { MAX_SIDE, type Panel, PanelHost } from "./panel";
import { RecordingContext } from "./recorder";
import { routesPanel, STEPS } from "./routes";
import { PASS_WINDOW, signalsPanel } from "./signals";

const model = new CockpitModel();
model.ingest(runEvents());
const at = (t: number) => ({ t, cursor: model.store.cursorAt(t) });
const END = { t: model.store.endTime, cursor: model.store.length };
const SIZE = { w: 330, h: 90 };

function record<V>(panel: Panel<V>, t: number): string {
  const ctx = new RecordingContext();
  panel.draw(ctx, panel.view(t, model.store.cursorAt(t)), SIZE, t);
  return ctx.text();
}

describe("change routes", () => {
  const panel = routesPanel(model);

  it("follows each changed symbol from file to checks", () => {
    const mid = panel.view(26_000, at(26_000).cursor);
    expect(mid.rows).toHaveLength(7);
    // Mid-run: every route has its tests and is executing them; no checks yet.
    for (const row of mid.rows) {
      expect(STEPS[row.step]).toBe("test");
      expect(row.progress).toBeGreaterThan(0);
    }
    const end = panel.view(END.t, END.cursor);
    for (const row of end.rows) expect([STEPS[row.step], row.progress]).toEqual(["check", 1]);
    const fold = end.rows.find((r) => r.symbol === "_fold_offset");
    expect(fold).toMatchObject({ file: "fold.py", tests: 2 });
    expect(fold?.checks.passed).toBe(2);
    expect(end.rows.find((r) => r.symbol === "format_duration")?.checks.flagged).toBe(2);
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, 26_000)).toMatchFileSnapshot("./__snapshots__/routes-26000.txt");
    await expect(record(panel, END.t)).toMatchFileSnapshot("./__snapshots__/routes-final.txt");
  });
});

describe("signals", () => {
  const panel = signalsPanel(model);

  it("derives each series from its events", () => {
    const view = panel.view(END.t, END.cursor);
    const [pass, drift, perf] = view.series;
    const headFinishes = model.tests.runs.filter((r) => r.side === "head").length;
    expect(pass?.points).toHaveLength(headFinishes);
    // The first PASS_WINDOW points average over what has finished so far.
    for (const p of [...(pass?.points ?? []), ...(drift?.points ?? [])]) {
      expect(p.v).toBeGreaterThanOrEqual(0);
      expect(p.v).toBeLessThanOrEqual(1);
    }
    expect(PASS_WINDOW).toBe(8);
    // Perf: the daily rule's head runs about twice as fast as base.
    expect(perf?.points.some((p) => p.v < -0.4)).toBe(true);
    expect((perf?.min ?? 0) + (perf?.max ?? 0)).toBeCloseTo(0, 9);
  });

  it("ticks each resolving check at its data point, inside the time axis", () => {
    const view = panel.view(END.t, END.cursor);
    const [pass, drift, perf] = view.series;
    expect(pass?.ticks).toHaveLength(3); // one P2F, two F2P
    expect(pass?.ticks.filter((t) => t.flagged)).toHaveLength(1);
    expect(drift?.ticks).toHaveLength(3);
    expect(perf?.ticks).toHaveLength(2);
    for (const s of view.series)
      for (const tick of s.ticks) {
        expect(tick.t).toBeGreaterThanOrEqual(view.from);
        expect(tick.t).toBeLessThanOrEqual(view.to);
      }
  });

  it("is empty before tests finish and redraws only on its events", () => {
    const early = at(10_000);
    expect(panel.view(early.t, early.cursor).series.every((s) => s.points.length === 0)).toBe(true);
    expect(panel.version(early.t, early.cursor)).toBe(panel.version(early.t + 999, early.cursor));
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, END.t)).toMatchFileSnapshot("./__snapshots__/signals-final.txt");
  });
});

describe("agents / dispatch", () => {
  const panel = dispatchPanel(model);

  it("shows twelve slots with status, progress and flags", () => {
    const end = panel.view(END.t, END.cursor);
    expect(end.slots).toHaveLength(SLOTS);
    expect(end.slots.find((s) => s.id === "a08")).toMatchObject({
      status: "flagged",
      flagged: true,
    });
    expect(end.slots.filter((s) => s.status === "done")).toHaveLength(11);
    for (const s of end.slots) expect(s.progress).toBe(1);
    const mid = panel.view(26_000, at(26_000).cursor);
    expect(mid.slots.filter((s) => s.id === null).length).toBeGreaterThan(0);
    for (const s of mid.slots)
      if (s.status === "working" && s.tool !== null) expect(s.tool).not.toMatch(/^mcp__/);
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, 26_000)).toMatchFileSnapshot("./__snapshots__/dispatch-26000.txt");
  });
});

describe("change × check index panel", () => {
  const panel = indexPanel(model);

  it("splits any number of checks into contiguous columns that cover each check once", () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 5000 }), fc.integer({ min: 1, max: 2000 }), (n, w) => {
        const ranges = columnRanges(n, w);
        expect(ranges.length).toBeLessThanOrEqual(Math.max(1, Math.floor(w / MIN_PITCH)));
        let next = 0;
        for (const [from, to] of ranges) {
          expect(from).toBe(next);
          expect(to).toBeGreaterThan(from);
          next = to;
        }
        expect(next).toBe(n);
      }),
    );
  });

  it("buckets the stress run's 611 checks into the columns that fit", () => {
    const text = readFileSync(new URL("../../fixtures/stress-run.jsonl", import.meta.url), "utf8");
    const stress = new CockpitModel();
    stress.ingest(parseJsonl(text).values);
    const view = indexPanel(stress).view(stress.store.endTime, stress.store.length);
    expect(view.results).toHaveLength(611);
    expect(columnRanges(view.results.length, 204)).toHaveLength(68);
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, END.t)).toMatchFileSnapshot("./__snapshots__/index-final.txt");
  });
});

describe("PanelHost size clamp", () => {
  it("never allocates a canvas side above MAX_SIDE CSS px", () => {
    const ctx = new RecordingContext() as unknown as CanvasRenderingContext2D;
    const canvas = { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
    const host = new PanelHost(
      { id: "x", version: () => 1, view: () => null, draw: () => {} },
      canvas,
    );
    host.resize(19_173_962, 19_173_962, 2);
    expect([canvas.width, canvas.height]).toEqual([MAX_SIDE * 2, MAX_SIDE * 2]);
  });
});
