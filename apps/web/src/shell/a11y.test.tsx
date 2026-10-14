// @vitest-environment jsdom
// B11: the accessible parallel DOM, the evidence drawer's keyboard behaviour, and axe-core.
import { signal } from "@preact/signals";
import axe from "axe-core";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { type DrawerView, drawerView } from "../focus/evidence";
import type { Focus } from "../focus/focus";
import { PresentationClock } from "../model/clock";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { indexPanel } from "../panels/check-index";
import { dispatchPanel } from "../panels/dispatch";
import type { PanelTarget } from "../panels/panel";
import { routesPanel } from "../panels/routes";
import { DEFAULT_LOOK } from "../stage/look";
import { App, type FocusUi } from "./app";
import { computeLayout } from "./layout";
import { createTransportState } from "./transport";
import { createShellView } from "./view";

const model = new CockpitModel();
model.ingest(runEvents());
const END = model.store.length;
const SIZE = { w: 330, h: 90 };
const targetsOf = <V,>(panel: {
  view(t: number, c: number): V;
  targets?(v: V, s: typeof SIZE): readonly PanelTarget[];
}) => signal(panel.targets?.(panel.view(model.store.endTime, END), SIZE) ?? []);

let root: HTMLElement;
let focused: (Focus | null)[];
let ui: FocusUi;
beforeEach(() => {
  root = document.createElement("div");
  document.body.append(root);
  focused = [];
  const drawer = signal<DrawerView | null>(null);
  ui = {
    drawer,
    targets: {
      routes: targetsOf(routesPanel(model)),
      dispatch: targetsOf(dispatchPanel(model)),
      index: targetsOf(indexPanel(model)),
    },
    keyboard: signal(""),
    feed: signal([{ id: 0, text: "review: C3 contradicted (2/2 agree)" }]),
    files: signal(["timekeeper/fmt.py", "timekeeper/parse.py"]),
    stageLabel: signal("Stage at 0:48.7: 1500 dependency edges, 147 files on the ring."),
    onFocus: (focus) => {
      focused.push(focus);
      drawer.value = focus === null ? null : drawerView(focus, model, END);
    },
  };
  const view = createShellView();
  view.update(model.folder.stateAt(END));
  const clock = new PresentationClock(() => 0);
  clock.setEnd(model.store.endTime);
  act(() =>
    render(
      <App
        layout={signal(computeLayout(1440, 900))}
        view={view}
        transport={{ state: createTransportState(), clock, reduced: signal(false) }}
        focus={ui}
        settings={{ open: signal(true), look: signal(DEFAULT_LOOK) }}
      />,
      root,
    ),
  );
});
afterEach(() => {
  render(null, root);
  root.remove();
});

const button = (scope: string, label: string) => {
  const found = [...root.querySelectorAll<HTMLButtonElement>(`${scope} button`)].find(
    (b) => b.textContent === label,
  );
  if (found === undefined) throw new Error(`no ${label} in ${scope}`);
  return found;
};

describe("accessible parallel DOM", () => {
  it("mirrors the canvases: a feed log, panel rows and a labelled stage", () => {
    expect(root.querySelector('[role="log"]')?.textContent).toContain("C3 contradicted");
    expect(root.querySelector(".stage-canvas")?.getAttribute("aria-label")).toContain("0:48.7");
    const caption = root.querySelector('[data-panel="index"] table caption');
    expect(caption?.textContent).toBe("Change × check index");
    const firstRow = root.querySelector('[data-panel="index"] tbody tr');
    expect(firstRow?.textContent).toBe("C1 fixverified9 related checks");
    expect(root.querySelectorAll('[data-panel="dispatch"] li button')).toHaveLength(12);
    expect(root.querySelectorAll('[data-panel="routes"] li button')).toHaveLength(7);
  });

  it("appends to the log without rewriting what was already announced", () => {
    const entries = Array.from({ length: 20 }, (_, id) => ({ id, text: `line ${id}` }));
    act(() => {
      ui.feed.value = entries;
    });
    const log = root.querySelector('[role="log"]') as HTMLElement;
    const kept = [...log.children].slice(1);
    act(() => {
      ui.feed.value = [...entries.slice(1), { id: 20, text: "line 20" }];
    });
    // The 19 kept entries are the same nodes with the same text; only one node is new.
    expect([...log.children].slice(0, 19)).toEqual(kept);
    expect(kept.map((p) => p.textContent)).toEqual(entries.slice(1).map((e) => e.text));
    expect(log.lastElementChild?.textContent).toBe("line 20");
  });

  it("puts the keyboard on a row and focuses it with Enter (a click)", () => {
    const c3 = button('[data-panel="index"]', "C3 refactor");
    act(() => c3.focus());
    expect(ui.keyboard.value).toBe("claim:C3");
    act(() => c3.click());
    expect(focused).toEqual([{ kind: "claim", id: "C3" }]);
    act(() => c3.blur());
    expect(ui.keyboard.value).toBe("");
  });
});

describe("evidence drawer", () => {
  it("opens on focus, takes keyboard focus, links onwards, and Escape returns focus", () => {
    const c3 = button('[data-panel="index"]', "C3 refactor");
    act(() => c3.focus());
    act(() => c3.click());
    const drawer = root.querySelector(".drawer");
    expect(drawer?.getAttribute("aria-labelledby")).toBe("drawer-title");
    expect(document.activeElement?.id).toBe("drawer-title");
    // A related check links onwards to its own evidence.
    const check = drawer?.querySelector<HTMLButtonElement>("table.rows button");
    act(() => check?.click());
    expect(focused.at(-1)?.kind).toBe("check");
    expect(root.querySelector("#drawer-title")?.textContent).toMatch(/^Check #\d+ · /);
    act(() => {
      document.activeElement?.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
      );
    });
    expect(root.querySelector(".drawer")).toBeNull();
    expect(document.activeElement).toBe(c3);
  });

  it("presents facts and evidence as semantic tables", () => {
    act(() => ui.onFocus({ kind: "claim", id: "C3" }));
    const facts = root.querySelectorAll(".drawer table.facts th[scope='row']");
    expect([...facts].map((th) => th.textContent)).toContain("Verdict");
    expect(root.querySelector(".drawer table.rows thead th[scope='col']")?.textContent).toBe(
      "Check",
    );
  });
});

describe("axe-core", () => {
  it("reports no serious or critical violations, with the drawer open", async () => {
    act(() => ui.onFocus({ kind: "claim", id: "C3" }));
    // jsdom has no layout or canvas rendering, so contrast cannot be computed here (B12 checks
    // it in a real browser).
    const result = await axe.run(root, { rules: { "color-contrast": { enabled: false } } });
    const serious = result.violations.filter(
      (v) => v.impact === "serious" || v.impact === "critical",
    );
    expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    expect(result.violations.map((v) => v.id)).toEqual([]);
  });
});
