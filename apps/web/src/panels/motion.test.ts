// B10: panels in wall-clock time, reduced motion, and "scrub = play" for the panels.
import { signal } from "@preact/signals";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import type { Motion } from "../motion/motion";
import { behaviourPanel } from "./behaviour";
import { indexPanel } from "./check-index";
import { dispatchPanel } from "./dispatch";
import { executionPanel } from "./execution";
import { feedPanel, INSERT_MS } from "./feed";
import type { Panel } from "./panel";
import { RecordingContext } from "./recorder";
import { routesPanel } from "./routes";
import { signalsPanel } from "./signals";
import { TYPE_MS, workspacePanel } from "./workspace";

const model = new CockpitModel();
model.ingest(runEvents());
const SIZE = { w: 330, h: 90 };
const panels: Panel<unknown>[] = [
  feedPanel(model),
  executionPanel(model, signal("both")),
  workspacePanel(model),
  behaviourPanel(model),
  routesPanel(model),
  signalsPanel(model),
  dispatchPanel(model),
  indexPanel(model),
] as Panel<unknown>[];

function draw(panel: Panel<unknown>, t: number, motion: Motion): string {
  const ctx = new RecordingContext();
  panel.draw(ctx, panel.view(t, model.store.cursorAt(t), motion), SIZE, t);
  return ctx.text();
}

describe("panels in wall-clock time (ADR-0011)", () => {
  const lastLog = model.kinds.lastIndex("log.line", model.store.length);
  const logTime = model.store.time[lastLog] as number;

  it("slides a feed row in over 150 ms of wall-clock time at any speed", () => {
    const feed = feedPanel(model);
    for (const speed of [0.5, 1, 4, 16]) {
      const motion = { speed, reduced: false };
      expect(feed.view(logTime + (INSERT_MS * speed) / 2, lastLog + 1, motion).insert).toBeCloseTo(
        0.5,
        9,
      );
    }
  });

  it("types at 18 ms per character of wall-clock time", () => {
    const workspace = workspacePanel(model);
    const last = model.kinds.lastIndex("agent.state", model.store.cursorAt(24_500));
    const time = model.store.time[last] as number;
    for (const speed of [1, 16]) {
      const view = workspace.view(time + TYPE_MS * 4 * speed, last + 1, { speed, reduced: false });
      expect(view.lines.at(-1)?.typed).toBe(4);
    }
  });
});

describe("reduced motion", () => {
  const reduced = { speed: 1, reduced: true };

  it("shows feed rows and typed lines whole at once", () => {
    const last = model.kinds.lastIndex("log.line", model.store.length);
    expect(feedPanel(model).view(model.store.time[last] as number, last + 1, reduced).insert).toBe(
      1,
    );
    const state = model.kinds.lastIndex("agent.state", model.store.cursorAt(24_500));
    const line = workspacePanel(model)
      .view(model.store.time[state] as number, state + 1, reduced)
      .lines.at(-1);
    expect(line?.typed).toBe(line?.text.length);
  });

  it("stops every panel's own animation: nothing redraws while no event arrives", () => {
    for (const panel of panels) {
      for (let t = 0; t < model.store.endTime; t += 250) {
        const cursor = model.store.cursorAt(t);
        // Same cursor 100 ms later (if no event lands in between): same version.
        if (model.store.cursorAt(t + 100) !== cursor) continue;
        expect(panel.version(t + 100, cursor, reduced), panel.id).toBe(
          panel.version(t, cursor, reduced),
        );
      }
    }
  });
});

describe("scrubbing gives the same panels as playing", () => {
  // A panel host shows the drawing from the last version change. So playing equals scrubbing
  // if equal versions always mean equal drawings: checked frame by frame across busy stretches.
  const WINDOWS = [
    [9_500, 11_500],
    [23_300, 25_300],
    [32_500, 34_500],
  ] as const;

  for (const motion of [
    { speed: 1, reduced: false },
    { speed: 16, reduced: false },
    { speed: 1, reduced: true },
  ]) {
    it(`never shows a stale drawing at ×${motion.speed}${motion.reduced ? " (reduced)" : ""}`, () => {
      for (const panel of panels) {
        for (const [from, to] of WINDOWS) {
          let previous: { version: number; drawing: string } | null = null;
          for (let t = from; t < to; t += 1000 / 60) {
            const version = panel.version(t, model.store.cursorAt(t), motion);
            if (previous !== null && previous.version === version) {
              expect(draw(panel, t, motion), `${panel.id} at ${t.toFixed(1)}`).toBe(
                previous.drawing,
              );
              continue;
            }
            previous = { version, drawing: draw(panel, t, motion) };
          }
        }
      }
    });
  }
});
