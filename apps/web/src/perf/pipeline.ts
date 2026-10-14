/**
 * The cockpit's per-frame work without a GPU or a DOM (B12): every stage layer's update, the
 * callout tracker and every panel's redraw on a no-op canvas, in the frame loop's order. The
 * allocation test and the frame-cost benchmark both run it, so they measure what the browser
 * runs each frame, minus WebGL and the DOM.
 */
import { signal } from "@preact/signals";
import { busiestSecond } from "../bench/run";
import { type FocusTargets, NO_FOCUS } from "../focus/focus";
import { CockpitModel } from "../model/cockpit";
import { type Motion, NORMAL_MOTION } from "../motion/motion";
import { behaviourPanel } from "../panels/behaviour";
import { indexPanel } from "../panels/check-index";
import { dispatchPanel } from "../panels/dispatch";
import { executionPanel } from "../panels/execution";
import { feedPanel } from "../panels/feed";
import { type Ctx2D, NO_HIGHLIGHT, type Panel, PanelHost } from "../panels/panel";
import { routesPanel } from "../panels/routes";
import { signalsPanel } from "../panels/signals";
import { workspacePanel } from "../panels/workspace";
import { computeLayout } from "../shell/layout";
import { focusLayers } from "../stage/focus-layer";
import { FLASH_BUDGET, FlashGovernor } from "../stage/governor";
import type { StageFrame, StageLayer } from "../stage/layer";
import { AtlasService } from "../stage/ring/atlas-service";
import { ringLayers } from "../stage/ring/layers";
import { CalloutTracker } from "../stage/streams/callouts";
import { webLayers } from "../stage/web/layers";
import { computeInline, LayoutService } from "../stage/web/layout-service";

const noop = () => {};

/** A Canvas 2D context that draws nothing and allocates nothing. */
const NULL_CONTEXT: Ctx2D & { setTransform(): void } = {
  fillStyle: "#000",
  strokeStyle: "#000",
  font: "",
  textBaseline: "top",
  textAlign: "left",
  globalAlpha: 1,
  lineWidth: 1,
  fillRect: noop,
  strokeRect: noop,
  clearRect: noop,
  fillText: noop,
  beginPath: noop,
  moveTo: noop,
  lineTo: noop,
  arc: noop,
  stroke: noop,
  fill: noop,
  save: noop,
  restore: noop,
  setTransform: noop,
};

export interface Pipeline {
  readonly model: CockpitModel;
  readonly layers: readonly StageLayer[];
  /** Start of the log's busiest second of execution events (the stress run's burst). */
  readonly burst: number;
  /** One frame at `t`: stage layers, callouts, panels. */
  frame(t: number, motion?: Motion, focus?: FocusTargets): void;
  /** Stage layers and callouts only (the allocation-free part). */
  stage(t: number, motion?: Motion): void;
}

/** Builds the pipeline for a log at the desktop layout (1440×900), with the web laid out. */
export async function pipeline(events: readonly unknown[]): Promise<Pipeline> {
  const model = new CockpitModel();
  model.ingest(events);
  const layout = new LayoutService(model.graph, computeInline);
  await layout.request();
  const { stage, ring: geometry, panels: rects } = computeLayout(1440, 900);
  const ring = ringLayers(model, new AtlasService(() => Promise.resolve(null)));
  const governor = new FlashGovernor(model, layout, FLASH_BUDGET, ring.ring);
  const focus = focusLayers(model, layout, ring.ring);
  const layers: StageLayer[] = [
    ...webLayers(model, layout, governor, ring.ring),
    focus.web,
    ...ring.layers,
    focus.ring,
  ];
  const panels: Panel<never>[] = [
    feedPanel(model),
    executionPanel(model, signal("both")),
    workspacePanel(model),
    behaviourPanel(model),
    routesPanel(model),
    signalsPanel(model),
    dispatchPanel(model),
    indexPanel(model),
  ] as Panel<never>[];
  const hosts = panels.map((panel, i) => {
    const canvas = { width: 0, height: 0, getContext: () => NULL_CONTEXT };
    const host = new PanelHost(panel, canvas as unknown as HTMLCanvasElement);
    const rect = rects[i] ?? { w: 330, h: 90 };
    host.resize(rect.w - 20, rect.h - 40, 1);
    return host;
  });
  const callouts = new CalloutTracker();
  const input: { -readonly [K in keyof StageFrame]: StageFrame[K] } = {
    t: 0,
    cursor: 0,
    width: stage.w,
    height: stage.h,
    ring: geometry,
    motion: NORMAL_MOTION,
    focus: NO_FOCUS,
  };
  const runStage = (t: number, motion: Motion, focus: FocusTargets) => {
    input.t = t;
    input.cursor = model.store.cursorAt(t);
    input.motion = motion;
    input.focus = focus;
    for (const layer of layers) layer.update(input);
    callouts.update(model, t, geometry, motion);
  };
  return {
    model,
    layers,
    burst: busiestSecond(model),
    frame(t, motion = NORMAL_MOTION, focus = NO_FOCUS) {
      runStage(t, motion, focus);
      for (const host of hosts) host.frame(t, input.cursor, motion, NO_HIGHLIGHT);
    },
    stage(t, motion = NORMAL_MOTION) {
      runStage(t, motion, NO_FOCUS);
    },
  };
}
