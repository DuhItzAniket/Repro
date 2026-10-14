// @vitest-environment jsdom
import { signal } from "@preact/signals";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { PresentationClock } from "../model/clock";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import type { Motion } from "../motion/motion";
import { FrameLoop, type FrameScheduler } from "./frame";
import { computeLayout } from "./layout";
import { SETTINGS_ID } from "./settings";
import {
  createTransportState,
  formatTime,
  spaceToPause,
  syncTransport,
  TIME_STEP,
  Transport,
} from "./transport";
import { createShellView } from "./view";

let wall = 0;
let clock: PresentationClock;
let root: HTMLElement;
beforeEach(() => {
  wall = 0;
  clock = new PresentationClock(() => wall);
  clock.setEnd(48_700);
  root = document.createElement("div");
  document.body.append(root);
});
afterEach(() => {
  render(null, root);
  root.remove();
});

function mount() {
  const state = createTransportState();
  const reduced = signal(false);
  const sync = () => syncTransport(state, clock);
  sync();
  const { transport } = computeLayout(1440, 900);
  act(() =>
    render(
      <Transport rect={transport} state={state} clock={clock} reduced={reduced} onCommand={sync} />,
      root,
    ),
  );
  const buttons = () => [...root.querySelectorAll<HTMLButtonElement>("button")];
  const button = (label: string) => {
    const found = buttons().find((b) => b.textContent === label);
    if (found === undefined) throw new Error(`no ${label} button`);
    return found;
  };
  return { state, reduced, sync, button, buttons };
}

describe("transport controls", () => {
  it("plays, pauses and shows the speed that is in effect", () => {
    const { button } = mount();
    expect(clock.paused).toBe(true);
    act(() => button("Play").click());
    expect(clock.paused).toBe(false);
    act(() => button("×16").click());
    expect(clock.speed).toBe(16);
    expect(button("×16").getAttribute("aria-pressed")).toBe("true");
    expect(button("×1").getAttribute("aria-pressed")).toBe("false");
    act(() => button("Pause").click());
    expect(clock.paused).toBe(true);
  });

  it("scrubs to a time and labels it for assistive technology", () => {
    const { state } = mount();
    const scrubber = root.querySelector<HTMLInputElement>('input[type="range"]');
    if (scrubber === null) throw new Error("no scrubber");
    expect(scrubber.getAttribute("aria-label")).toBe("Run time");
    expect(scrubber.max).toBe(String(48_700));
    act(() => {
      scrubber.value = "24500";
      scrubber.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(clock.time()).toBe(24_500);
    expect(state.value.t).toBe(24_500);
    expect(scrubber.getAttribute("aria-valuetext")).toBe("0:24.5 of 0:48.7");
  });

  it("jumps to live and toggles reduced motion", () => {
    const { button, reduced } = mount();
    act(() => button("Live").click());
    expect(clock.mode).toBe("live");
    expect(button("Live").getAttribute("aria-pressed")).toBe("true");
    // Following live runs at ×1, so no replay speed shows as pressed.
    expect(button("×1").getAttribute("aria-pressed")).toBe("false");
    act(() => button("Reduce motion").click());
    expect(reduced.value).toBe(true);
    expect(button("Reduce motion").getAttribute("aria-pressed")).toBe("true");
  });

  it("opens and closes the stage settings, and says which menu it controls (B15)", () => {
    const state = createTransportState();
    const settings = signal(false);
    const { transport } = computeLayout(1440, 900);
    act(() =>
      render(
        <Transport
          rect={transport}
          state={state}
          clock={clock}
          reduced={signal(false)}
          settings={settings}
        />,
        root,
      ),
    );
    const toggle = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent === "Settings",
    );
    if (toggle === undefined) throw new Error("no Settings button");
    expect(toggle.getAttribute("aria-controls")).toBe(SETTINGS_ID);
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    act(() => toggle.click());
    expect(settings.value).toBe(true);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    act(() => toggle.click());
    expect(settings.value).toBe(false);
  });

  it("has no Settings button without a menu to open", () => {
    const { buttons } = mount();
    expect(buttons().some((b) => b.textContent === "Settings")).toBe(false);
  });

  it("re-renders only when what it shows changes (100 ms steps)", () => {
    const state = createTransportState();
    clock.play();
    syncTransport(state, clock);
    const first = state.value;
    wall = TIME_STEP / 2;
    syncTransport(state, clock);
    expect(state.value).toBe(first); // same 100 ms step: no new value, no re-render
    wall = TIME_STEP;
    syncTransport(state, clock);
    expect(state.value.t).toBe(TIME_STEP);
  });

  it("formats run time as m:ss.s", () => {
    expect(formatTime(0)).toBe("0:00.0");
    expect(formatTime(48_716)).toBe("0:48.7");
    expect(formatTime(61_050)).toBe("1:01.0");
  });
});

describe("Space pauses everything (WCAG 2.2.2)", () => {
  const press = (target: EventTarget, init: KeyboardEventInit = {}) => {
    const event = new KeyboardEvent("keydown", {
      key: " ",
      bubbles: true,
      cancelable: true,
      ...init,
    });
    target.dispatchEvent(event);
    return event;
  };
  beforeEach(() => {
    window.addEventListener("keydown", handler);
  });
  afterEach(() => {
    window.removeEventListener("keydown", handler);
  });
  const handler = (event: KeyboardEvent) => spaceToPause(event, clock);

  it("toggles the clock from anywhere that is not a control", () => {
    const event = press(document.body);
    expect(clock.paused).toBe(false);
    expect(event.defaultPrevented).toBe(true); // the page does not scroll
    press(document.body);
    expect(clock.paused).toBe(true);
  });

  it("leaves Space to focused controls and ignores held-down repeats", () => {
    const { button } = mount();
    press(button("×4"));
    expect(clock.paused).toBe(true);
    const scrubber = root.querySelector('input[type="range"]');
    if (scrubber === null) throw new Error("no scrubber");
    press(scrubber);
    press(document.body, { repeat: true });
    expect(clock.paused).toBe(true);
  });
});

describe("frame loop motion", () => {
  it("passes the replay speed and reduced motion to listeners, ×1 when live", () => {
    const model = new CockpitModel();
    model.ingest(runEvents());
    const reduced = signal(false);
    const scheduler: FrameScheduler = { request: () => 1, cancel: () => {} };
    const loop = new FrameLoop(model, clock, createShellView(), scheduler, reduced);
    const seen: Motion[] = [];
    loop.listen((_t, _cursor, motion) => seen.push({ ...motion }));
    loop.start();
    clock.setSpeed(4);
    loop.frame();
    reduced.value = true;
    clock.goLive();
    loop.frame();
    expect(seen).toEqual([
      { speed: 4, reduced: false },
      { speed: 1, reduced: true },
    ]);
  });

  it("lays the transport along the bottom of the stage", () => {
    for (const [w, h] of [
      [1440, 900],
      [900, 700],
    ] as const) {
      const { stage, transport } = computeLayout(w, h);
      expect(transport.y + transport.h).toBeLessThanOrEqual(stage.y + stage.h);
      expect(transport.y).toBeGreaterThan(stage.y + stage.h / 2);
      expect(transport.x).toBeGreaterThanOrEqual(stage.x);
      expect(transport.x + transport.w).toBeLessThanOrEqual(stage.x + stage.w);
    }
  });
});
