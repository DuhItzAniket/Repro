import { describe, expect, it } from "vitest";
import { PresentationClock } from "../model/clock";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { FrameLoop, type FrameScheduler } from "./frame";
import { createShellView } from "./view";

function harness() {
  let wall = 0;
  const queue: (() => void)[] = [];
  const scheduler: FrameScheduler = {
    request: (callback) => queue.push(callback),
    cancel: () => {
      queue.length = 0;
    },
  };
  const model = new CockpitModel();
  model.ingest(runEvents());
  const clock = new PresentationClock(() => wall);
  const view = createShellView();
  let updates = 0;
  const update = view.update;
  view.update = (state) => {
    updates++;
    update(state);
  };
  const loop = new FrameLoop(model, clock, view, scheduler);
  const step = (ms: number) => {
    wall += ms;
    const next = queue.shift();
    next?.();
  };
  return { model, clock, view, loop, step, updates: () => updates, queue };
}

describe("FrameLoop", () => {
  it("updates the shell only when the fold cursor moves", () => {
    const h = harness();
    const ticks: number[] = [];
    h.loop.listen((t) => ticks.push(t));
    h.loop.start();
    h.step(16); // paused at t = 0: the first frame folds the initial cursor once
    for (let i = 0; i < 10; i++) h.step(16);
    expect(h.updates()).toBe(1);
    expect(ticks).toHaveLength(11); // listeners still see every frame
    h.clock.play();
    h.step(16);
    for (let i = 0; i < 100; i++) h.step(16);
    expect(h.updates()).toBeGreaterThan(1);
    expect(h.updates()).toBeLessThanOrEqual(102);
  });

  it("plays the demo run to its end and shows the final counters", () => {
    const h = harness();
    h.clock.setSpeed(16);
    h.clock.play();
    h.loop.start();
    for (let i = 0; i < 400 && h.view.finished.value === false; i++) h.step(16);
    expect(h.view.counters.value).toEqual({
      claims: 4,
      agents: 12,
      files: 147,
      checks: 28,
      flagged: 4,
    });
    expect(h.clock.time()).toBe(h.model.store.endTime);
  });

  it("stops scheduling after stop()", () => {
    const h = harness();
    h.loop.start();
    h.loop.stop();
    expect(h.queue).toHaveLength(0);
    h.loop.frame();
    expect(h.queue).toHaveLength(0);
  });
});
