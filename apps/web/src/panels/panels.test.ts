import { readFileSync } from "node:fs";
import { signal } from "@preact/signals";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { COLOR, TOKEN_OF } from "../styles/palette";
import { behaviourPanel } from "./behaviour";
import { type ExecutionSides, executionPanel } from "./execution";
import { feedPanel, INSERT_MS } from "./feed";
import { type Panel, PanelHost } from "./panel";
import { RecordingContext } from "./recorder";
import { TYPE_MS, workspacePanel } from "./workspace";

const model = new CockpitModel();
model.ingest(runEvents());
const at = (t: number) => ({ t, cursor: model.store.cursorAt(t) });
const SIZE = { w: 330, h: 150 };

function record<V>(panel: Panel<V>, t: number): string {
  const ctx = new RecordingContext();
  const { cursor } = at(t);
  panel.draw(ctx, panel.view(t, cursor), SIZE, t);
  return ctx.text();
}

describe("palette", () => {
  it("mirrors tokens.css exactly", () => {
    const css = readFileSync(new URL("../styles/tokens.css", import.meta.url), "utf8");
    for (const [name, token] of Object.entries(TOKEN_OF)) {
      const match = css.match(new RegExp(`${token}:\\s*(#[0-9a-f]{6})`));
      expect(match?.[1], token).toBe(COLOR[name as keyof typeof COLOR]);
    }
  });
});

describe("PanelHost (redraws only when dirty)", () => {
  it("draws once per version and again after a resize or invalidation", () => {
    let draws = 0;
    const ctx = new RecordingContext() as unknown as CanvasRenderingContext2D & {
      setTransform(): void;
    };
    (ctx as unknown as { setTransform: () => void }).setTransform = () => {};
    const canvas = { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
    let version = 1;
    const host = new PanelHost(
      {
        id: "x",
        version: () => version,
        view: () => null,
        draw: () => {
          draws++;
        },
      },
      canvas,
    );
    expect(host.frame(0, 0)).toBe(false); // no size yet
    host.resize(100, 50, 2);
    expect([canvas.width, canvas.height]).toEqual([200, 100]);
    expect(host.frame(0, 0)).toBe(true);
    expect(host.frame(16, 0)).toBe(false);
    version = 2;
    expect(host.frame(32, 0)).toBe(true);
    host.invalidate();
    expect(host.frame(48, 0)).toBe(true);
    host.resize(100, 50, 2); // unchanged: no redraw
    expect(host.frame(64, 0)).toBe(false);
    host.resize(101, 50, 2);
    expect(host.frame(80, 0)).toBe(true);
    expect(draws).toBe(4);
  });
});

describe("investigation feed", () => {
  const panel = feedPanel(model);
  it("lists the latest log lines before the cursor, newest last", () => {
    const { t, cursor } = at(30_500);
    const view = panel.view(t, cursor);
    const expected = model.kinds
      .last("log.line", cursor, 32)
      .map((i) => model.store.envelope(i).seq);
    expect(view.rows.map((r) => r.seq)).toEqual(expected);
    expect(view.rows.at(-1)?.level).toBeDefined();
  });

  it("slides the newest row in over 150 ms, then stops redrawing", () => {
    const last = model.kinds.lastIndex("log.line", model.store.length);
    const time = model.store.time[last] as number;
    const cursor = last + 1;
    expect(panel.view(time + INSERT_MS / 2, cursor).insert).toBeCloseTo(0.5, 6);
    expect(panel.version(time + INSERT_MS, cursor)).toBe(panel.version(time + 5_000, cursor));
    expect(panel.version(time + 10, cursor)).not.toBe(panel.version(time + 100, cursor));
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, 30_500)).toMatchFileSnapshot("./__snapshots__/feed-30500.txt");
  });
});

describe("execution", () => {
  const sides = signal<ExecutionSides>("both");
  const panel = executionPanel(model, sides);

  it("counts runs and failures per lane as of the cursor", () => {
    const { t, cursor } = at(26_000);
    const view = panel.view(t, cursor);
    const counts = (side: string) => {
      const runs = model.tests.runs.filter((r) => r.side === side && r.started < cursor);
      const failed = runs.filter(
        (r) =>
          r.finished >= 0 &&
          r.finished < cursor &&
          (r.outcome === "failed" || r.outcome === "error"),
      );
      return { run: runs.length, failed: failed.length };
    };
    for (const lane of view.lanes) {
      expect(lane.counts).toEqual(counts(lane.side));
      // The BASE lane also carries the repeat base run (A′), counted separately.
      const repeat = lane.side === "base" ? counts("base_repeat") : null;
      expect(lane.repeat).toEqual(repeat);
      expect(lane.particles).toHaveLength(lane.counts.run + (repeat?.run ?? 0));
      expect(lane.particles.filter((p) => p.repeat)).toHaveLength(repeat?.run ?? 0);
      for (const p of lane.particles) {
        if (p.kind === "running") expect(p.x).toBeLessThanOrEqual(0.64);
        else expect(p.x).toBeGreaterThanOrEqual(0.7);
      }
    }
  });

  it("shows only the chosen side", () => {
    const { t, cursor } = at(26_000);
    sides.value = "head";
    expect(panel.view(t, cursor).lanes.map((l) => l.side)).toEqual(["head"]);
    sides.value = "both";
  });

  it("redraws while tests run and stays still otherwise", () => {
    const quiet = at(10_000);
    expect(panel.version(quiet.t, quiet.cursor)).toBe(panel.version(quiet.t + 500, quiet.cursor));
    const first = model.tests.runs[0];
    if (first === undefined) throw new Error("no runs");
    const t = (model.store.time[first.started] as number) + 1;
    const cursor = model.store.cursorAt(t);
    expect(panel.version(t, cursor)).not.toBe(panel.version(t + 100, cursor));
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, 26_000)).toMatchFileSnapshot("./__snapshots__/execution-26000.txt");
  });
});

describe("agent workspace", () => {
  const panel = workspacePanel(model);

  it("follows the agent with the latest state change and types its newest line", () => {
    const last = model.kinds.lastIndex("agent.state", model.store.cursorAt(24_500));
    const event = model.store.event(last);
    if (event?.kind !== "agent.state") throw new Error("no agent state");
    const time = model.store.time[last] as number;
    const typedAt = (dt: number) => panel.view(time + dt, last + 1).lines.at(-1)?.typed ?? -1;
    expect(panel.view(time, last + 1).heading?.startsWith(`${event.agent} · `)).toBe(true);
    expect(typedAt(0)).toBe(0);
    expect(typedAt(TYPE_MS * 3)).toBe(3);
    expect(typedAt(60_000)).toBe(event.payload.detail?.length);
  });

  it("blinks the cursor only while the agent works", () => {
    const end = model.store.length;
    const done = panel.view(model.store.endTime, end);
    expect(done.cursor).toBe(false); // the last agent (QA) has finished
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, 24_500)).toMatchFileSnapshot("./__snapshots__/workspace-24500.txt");
  });
});

describe("behaviour diff field", () => {
  const panel = behaviourPanel(model);
  const final = panel.view(model.store.endTime, model.store.length);
  const statusOf = (test: string, symbol: string) =>
    final.cells.find((c) => c.test.endsWith(test) && c.symbol.includes(symbol))?.status;

  it("flags the same differences the engine reports", () => {
    expect(statusOf("test_cli_parse", "parse_date")).toBe("differs");
    expect(statusOf("test_relative_hours", "format_duration")).toBe("differs");
    expect(statusOf("test_large_count", "expand_rrule")).toBe("unstable");
    expect(statusOf("test_naive_input", "parse_date")).toBe("same");
    for (const event of runEvents()) {
      if (event.kind !== "diff.behaviour") continue;
      const status = statusOf(event.payload.test, event.payload.symbol_id);
      expect(status).toBe(event.payload.stability === "unstable" ? "unstable" : "differs");
    }
  });

  it("counts differing cells per module in the histogram", () => {
    const sum = final.histogram.reduce((s, b) => s + b.differs, 0);
    expect(sum).toBe(final.cells.filter((c) => c.status === "differs").length);
    expect(final.histogram.map((b) => b.module)).toEqual(
      [...final.histogram.map((b) => b.module)].sort(),
    );
  });

  it("is empty before any trace and grows as samples arrive", () => {
    expect(panel.view(0, 0).cells).toHaveLength(0);
    const mid = at(24_500);
    const some = panel.view(mid.t, mid.cursor).cells.length;
    expect(some).toBeGreaterThan(0);
    expect(final.cells.length).toBeGreaterThanOrEqual(some);
  });

  it("draws the same thing for the same moment (golden)", async () => {
    await expect(record(panel, model.store.endTime)).toMatchFileSnapshot(
      "./__snapshots__/behaviour-final.txt",
    );
  });
});
