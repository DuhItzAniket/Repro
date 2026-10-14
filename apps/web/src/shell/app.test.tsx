// @vitest-environment jsdom
import { signal } from "@preact/signals";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { App } from "./app";
import { computeLayout } from "./layout";
import { PANELS } from "./panels";
import { createShellView } from "./view";

const model = new CockpitModel();
model.ingest(runEvents());

let root: HTMLElement;
beforeEach(() => {
  root = document.createElement("div");
  document.body.append(root);
});
afterEach(() => {
  render(null, root);
  root.remove();
});

const text = (selector: string) =>
  [...root.querySelectorAll(selector)].map((e) => e.textContent ?? "");

describe("App shell", () => {
  it("renders header, stage and the eight panels at the computed rectangles", () => {
    const view = createShellView();
    const layout = signal(computeLayout(1440, 900));
    act(() => render(<App layout={layout} view={view} />, root));
    expect(root.querySelector(".title")?.textContent).toBe("Repro");
    expect(text(".panel-title")).toEqual(PANELS.map((p) => p.title));
    // Every panel draws on its own canvas (B08, B09).
    const canvases = [...root.querySelectorAll<HTMLCanvasElement>(".panel-canvas")];
    expect(canvases.map((c) => c.dataset.panel)).toEqual(PANELS.map((p) => p.id));
    const stage = root.querySelector<HTMLElement>(".stage");
    expect([stage?.style.top, stage?.style.width, stage?.style.height]).toEqual([
      "56px",
      "904px",
      "844px",
    ]);
    const last = root.querySelectorAll<HTMLElement>(".panel")[7];
    expect([last?.style.left, last?.style.top, last?.style.width, last?.style.height]).toEqual([
      "1176px",
      "691px",
      "256px",
      "201px",
    ]);
    act(() => {
      layout.value = computeLayout(1920, 1080);
    });
    expect(root.querySelector<HTMLElement>(".stage")?.style.height).toBe("1024px");
  });

  it("shows counters, stage progress and the index footer from the event stream", () => {
    const view = createShellView();
    act(() => render(<App layout={signal(computeLayout(1440, 900))} view={view} />, root));
    expect(text(".counter dd")).toEqual(["0", "0", "0", "0", "0"]);
    // While the run is partial, Signals says its series are illustrative (DESIGN.md panel 6).
    act(() => view.update(model.folder.stateAt(model.store.cursorAt(26_000))));
    expect(root.querySelector('[data-panel="signals"] .panel-footer')?.textContent).toBe(
      "illustrative until run completes",
    );
    act(() => view.update(model.folder.stateAt(model.store.length)));
    expect(text(".counter dt")).toEqual(["Claims", "Agents", "Files", "Checks", "Flagged"]);
    expect(text(".counter dd")).toEqual(["4", "12", "147", "28", "4"]);
    expect(root.querySelector('.counter[data-alert="true"] dt')?.textContent).toBe("Flagged");
    const segments = [...root.querySelectorAll<HTMLElement>(".progress .segment")];
    expect(segments.map((s) => s.dataset.state)).toEqual(Array(7).fill("done"));
    expect(text(".progress .visually-hidden")[2]).toBe("run: done");
    expect(root.querySelector('[data-panel="index"] .panel-footer')?.textContent).toBe(
      "28 checks / 20 passed / 4 flagged / 4 unassessed",
    );
    // The Signals caption disappears once the run has finished.
    expect(root.querySelector('[data-panel="signals"] .panel-footer')).toBeNull();
    expect(root.querySelector(".subtitle")?.textContent).toContain("synthetic/timekeeper #128");
  });

  it("labels the panels for assistive technology", () => {
    act(() =>
      render(<App layout={signal(computeLayout(1440, 900))} view={createShellView()} />, root),
    );
    for (const panel of root.querySelectorAll(".panel")) {
      const id = panel.getAttribute("aria-labelledby");
      expect(id).not.toBeNull();
      expect(root.querySelector(`#${id}`)?.textContent).not.toBe("");
    }
    expect(root.querySelector(".progress")?.getAttribute("aria-label")).toBe("Pipeline stages");
  });
});
