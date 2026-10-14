// B11: focusing on the stage (hit testing, ring pin, highlight layer).
import { beforeAll, describe, expect, it } from "vitest";
import { focusTargets } from "../focus/focus";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { NORMAL_MOTION } from "../motion/motion";
import { computeLayout } from "../shell/layout";
import { focusLayers } from "./focus-layer";
import { ringBand, webRadius } from "./geometry";
import { hitStage } from "./hit";
import type { StageFrame } from "./layer";
import { AtlasService } from "./ring/atlas-service";
import { RingModel, rotationAt } from "./ring/layers";
import { computeInline, LayoutService } from "./web/layout-service";

const model = new CockpitModel();
model.ingest(runEvents());
const layout = new LayoutService(model.graph, computeInline);
const ring = new RingModel(model, new AtlasService(() => Promise.resolve(null)));
const { stage, ring: geometry } = computeLayout(1440, 900);
const END = model.store.endTime;
beforeAll(async () => {
  await layout.request();
  ring.sync();
});

const state = () => model.folder.stateAt(model.store.length);
const targetsOf = (file: string) => focusTargets({ kind: "file", file }, state(), model.changes);
const frameAt = (t: number, focus = targetsOf("")): StageFrame => ({
  t,
  cursor: model.store.cursorAt(t),
  width: stage.w,
  height: stage.h,
  ring: geometry,
  motion: NORMAL_MOTION,
  focus,
});

describe("stage hit testing", () => {
  it("hits a ring card at its drawn angle, rotation included", () => {
    const card = ring.content.cards.findIndex((c) => c.file === "timekeeper/recur.py");
    const rotation = rotationAt(ring, END, NORMAL_MOTION);
    const angle = ((ring.angles.start[card] as number) + (ring.angles.end[card] as number)) / 2;
    const radius = geometry.r + ringBand(geometry) / 2;
    const x = geometry.cx + Math.cos(angle + rotation) * radius;
    const y = geometry.cy + Math.sin(angle + rotation) * radius;
    const input = { t: END, ring: geometry, motion: NORMAL_MOTION };
    expect(hitStage(x, y, input, model, ring, layout)).toEqual({
      kind: "file",
      file: "timekeeper/recur.py",
    });
    // Before the card appears, nothing is there to hit.
    const appear = ring.content.cards[card]?.appear ?? 0;
    expect(hitStage(x, y, { ...input, t: appear - 1 }, model, ring, layout)).toBeNull();
  });

  it("hits a node of the web as its symbol (or its file for modules)", () => {
    const node = model.graph.nodeForSymbol("timekeeper.parse:parse_date#0") as number;
    const positions = layout.positions as Float32Array;
    const radius = webRadius(geometry);
    const x = geometry.cx + (positions[node * 2] as number) * radius;
    const y = geometry.cy + (positions[node * 2 + 1] as number) * radius;
    const hit = hitStage(
      x + 1,
      y - 1,
      { t: END, ring: geometry, motion: NORMAL_MOTION },
      model,
      ring,
      layout,
    );
    expect(hit).toEqual({
      kind: "symbol",
      symbol: "timekeeper.parse:parse_date#0",
      file: "timekeeper/parse.py",
    });
    // Far outside the ring and the web: nothing.
    expect(
      hitStage(
        stage.w - 2,
        2,
        { t: END, ring: geometry, motion: NORMAL_MOTION },
        model,
        ring,
        layout,
      ),
    ).toBeNull();
  });
});

describe("focus on the stage", () => {
  it("pins the focused file's card at 3 o'clock, without drift", () => {
    const focus = targetsOf("timekeeper/fmt.py");
    const card = ring.cardOf.get("timekeeper/fmt.py") as number;
    const centre = ((ring.angles.start[card] as number) + (ring.angles.end[card] as number)) / 2;
    for (const t of [20_000, 40_000]) {
      expect(rotationAt(ring, t, NORMAL_MOTION, focus) + centre).toBeCloseTo(0, 12);
    }
  });

  it("highlights the focused file's card, nodes and edges, and nothing without a focus", () => {
    const { web, ring: outline } = focusLayers(model, layout, ring);
    for (const layer of [web, outline]) {
      layer.update(frameAt(END));
      expect(layer.buffers.count).toBe(0);
      layer.update(frameAt(END, targetsOf("timekeeper/parse.py")));
      expect(layer.buffers.count).toBeGreaterThan(0);
      // No flares: the highlight never flashes.
      const flare = layer.buffers.array("flare");
      for (let i = 0; i < layer.buffers.count; i++) expect(flare[i]).toBe(0);
    }
    expect(outline.buffers.count).toBe(2 * 17); // the card's outline: two arcs and two sides
    // Web segments carry appearance times: scrubbing before the graph hides them.
    const appear = web.buffers.array("appear");
    const times = new Set<number>();
    for (let i = 0; i < web.buffers.count; i++) times.add(appear[i] as number);
    expect(times.size).toBeGreaterThan(1);
  });
});
