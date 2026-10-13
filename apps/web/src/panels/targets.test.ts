// B11: focusable rows and cells on the canvas panels, and how the host outlines them.
import { describe, expect, it } from "vitest";
import { focusKey } from "../focus/focus";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { indexPanel } from "./check-index";
import { dispatchPanel } from "./dispatch";
import { type Panel, PanelHost, type PanelTarget } from "./panel";
import { RecordingContext } from "./recorder";
import { routesPanel } from "./routes";

const model = new CockpitModel();
model.ingest(runEvents());
const END = { t: model.store.endTime, cursor: model.store.length };
const SIZE = { w: 330, h: 90 };

function host<V>(panel: Panel<V>) {
  const ctx = new RecordingContext();
  const canvas = { width: 0, height: 0, getContext: () => ctx } as unknown as HTMLCanvasElement;
  (ctx as unknown as { setTransform: () => void }).setTransform = () => {};
  const h = new PanelHost(panel, canvas);
  h.resize(SIZE.w, SIZE.h, 1);
  return { host: h, ctx };
}
const centre = (t: PanelTarget) => {
  const r = t.rect;
  if (r === null) throw new Error(`${t.label} is not drawn`);
  return [r.x + r.w / 2, r.y + r.h / 2] as const;
};

describe("panel targets", () => {
  it("routes: one listed row per changed symbol, hit where it is drawn", () => {
    const { host: h } = host(routesPanel(model));
    h.frame(END.t, END.cursor);
    expect(h.targets).toHaveLength(7);
    const fold = h.targets.find((t) => t.label.startsWith("_fold_offset"));
    if (fold === undefined) throw new Error("no _fold_offset row");
    expect(fold.focus).toEqual({
      kind: "symbol",
      symbol: "timekeeper.tz.fold:_fold_offset#0",
      file: "timekeeper/tz/fold.py",
    });
    expect(h.hit(...centre(fold))?.key).toBe(fold.key);
  });

  it("index: rows are listed for the keyboard, cells are not, and a cell wins a hit", () => {
    const { host: h } = host(indexPanel(model));
    h.frame(END.t, END.cursor);
    const rows = h.targets.filter((t) => t.listed);
    expect(rows.map((t) => t.label)).toEqual([
      "C1 fix",
      "C2 perf",
      "C3 refactor",
      "C4 deps",
      "_split_iso",
      "fmt.py",
      "_by_month",
      "_fold_offset",
    ]);
    expect(rows[2]?.cells).toEqual(["flagged", "4 related checks"]);
    const cells = h.targets.filter((t) => !t.listed);
    expect(cells.length).toBeGreaterThan(rows.length);
    const flagged = cells.find(
      (t) => t.label.startsWith("C3 refactor") && t.label.endsWith("flagged"),
    );
    if (flagged === undefined) throw new Error("no flagged C3 cell");
    expect(h.hit(...centre(flagged))?.focus.kind).toBe("check");
    // The row's label area focuses the claim.
    const c3 = rows[2] as PanelTarget;
    expect(h.hit(4, centre(c3)[1])?.focus).toEqual({ kind: "claim", id: "C3" });
  });

  it("dispatch: one target per spawned agent", () => {
    const { host: h } = host(dispatchPanel(model));
    h.frame(END.t, END.cursor);
    expect(h.targets.map((t) => t.focus)).toEqual(
      Array.from({ length: 12 }, (_, i) => ({
        kind: "agent",
        id: `a${String(i + 1).padStart(2, "0")}`,
      })),
    );
    const a08 = h.targets[7] as PanelTarget;
    expect(h.hit(...centre(a08))?.label).toBe("a08 review: flagged");
  });
});

describe("panel host outlines (B11)", () => {
  it("outlines the selected and the keyboard target, redrawing only when they change", () => {
    const { host: h, ctx } = host(indexPanel(model));
    let notified = 0;
    h.onTargets = () => notified++;
    const outlines = () => ctx.calls.filter((c) => c.startsWith("strokeRect")).length;
    expect(h.frame(END.t, END.cursor)).toBe(true);
    expect(notified).toBe(1);
    const plain = outlines(); // hollow (unassessed) cells are outlined too
    expect(h.frame(END.t, END.cursor)).toBe(false);
    const c3 = focusKey({ kind: "claim", id: "C3" });
    ctx.calls.length = 0;
    expect(h.frame(END.t, END.cursor, undefined, { selected: c3, keyboard: "" })).toBe(true);
    expect(outlines()).toBe(plain + 1);
    ctx.calls.length = 0;
    expect(h.frame(END.t, END.cursor, undefined, { selected: c3, keyboard: c3 })).toBe(true);
    expect(outlines()).toBe(plain + 2);
    // Same targets as before: the mirror is not re-rendered.
    expect(notified).toBe(1);
  });
});
