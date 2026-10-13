import "@fontsource-variable/jetbrains-mono/wght.css";
import "./styles/tokens.css";
import "./styles/shell.css";
import { signal } from "@preact/signals";
import { render } from "preact";
import { FIXTURES, fixtureFromQuery, loadLog } from "./data/load";
import { PresentationClock } from "./model/clock";
import { CockpitModel } from "./model/cockpit";
import { behaviourPanel } from "./panels/behaviour";
import { type ExecutionSides, executionPanel } from "./panels/execution";
import { feedPanel } from "./panels/feed";
import { type Panel, PanelHost } from "./panels/panel";
import { workspacePanel } from "./panels/workspace";
import { App } from "./shell/app";
import { FrameLoop } from "./shell/frame";
import { computeLayout } from "./shell/layout";
import { createShellView } from "./shell/view";
import { StageHost } from "./stage/host";
import { type HudSnapshot, pollHud } from "./stage/hud";
import { AtlasService, defaultAtlasBuild } from "./stage/ring/atlas-service";
import { ringLayers } from "./stage/ring/layers";
import { type Callout, CalloutTracker } from "./stage/streams/callouts";
import { streakLayer } from "./stage/streams/layers";
import { webLayers } from "./stage/web/layers";
import { computeInline, LayoutService, workerCompute } from "./stage/web/layout-service";

const root = document.getElementById("app");
if (root === null) throw new Error("Repro: #app root element is missing from index.html");

const model = new CockpitModel();
const webLayout = new LayoutService(
  model.graph,
  typeof Worker === "undefined" ? computeInline : workerCompute(),
);
const clock = new PresentationClock(() => performance.now());
const view = createShellView();
const layout = signal(computeLayout(window.innerWidth, window.innerHeight));

const params = new URLSearchParams(window.location.search);
const hud = params.has("hud") ? signal<HudSnapshot | null>(null) : undefined;
const callouts = signal<readonly Callout[]>([]);
const executionSides = signal<ExecutionSides>("both");
render(
  <App
    layout={layout}
    view={view}
    callouts={callouts}
    executionSides={executionSides}
    {...(hud === undefined ? {} : { hud })}
  />,
  root,
);

/** The WebGL stage. The rest of the cockpit works without it if WebGL 2 is unavailable. */
function mountStage(): StageHost | null {
  const canvas = root?.querySelector<HTMLCanvasElement>(".stage-canvas");
  if (canvas === null || canvas === undefined) return null;
  try {
    const stage = new StageHost(canvas, { devicePixelRatio: window.devicePixelRatio });
    for (const layer of webLayers(model, webLayout)) stage.add(layer);
    for (const layer of ringLayers(model, new AtlasService(defaultAtlasBuild())).layers) {
      stage.add(layer);
    }
    stage.add(streakLayer(model));
    stage.resize(layout.value.stage.w, layout.value.stage.h, layout.value.ring);
    if (hud !== undefined) pollHud(stage, hud);
    return stage;
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    view.status.value = `stage disabled: WebGL 2 is unavailable (${reason})`;
    return null;
  }
}

const host = mountStage();

/** Canvas 2D panels (B08): each redraws only when its version changes. */
interface PanelDriver {
  frame(t: number, cursor: number): boolean;
  resize(w: number, h: number, dpr: number): void;
  invalidate(): void;
}
const panelMakers: Record<string, () => Panel<never>> = {
  feed: () => feedPanel(model) as Panel<never>,
  execution: () => executionPanel(model, executionSides) as Panel<never>,
  workspace: () => workspacePanel(model) as Panel<never>,
  behaviour: () => behaviourPanel(model) as Panel<never>,
};
const panels = new Map<Element, PanelDriver>();
const panelSizes = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const { width, height } = entry.contentRect;
    panels.get(entry.target)?.resize(width, height, window.devicePixelRatio);
  }
});
for (const canvas of root.querySelectorAll<HTMLCanvasElement>(".panel-canvas")) {
  const make = panelMakers[canvas.dataset.panel ?? ""];
  if (make === undefined) continue;
  panels.set(canvas, new PanelHost(make(), canvas));
  panelSizes.observe(canvas);
}
// The panels draw text in the web font; repaint once it has loaded.
void document.fonts.ready.then(() => {
  for (const panel of panels.values()) panel.invalidate();
});
const loop = new FrameLoop(model, clock, view);
loop.listen((t, cursor) => host?.frame(t, cursor));
loop.listen((t, cursor) => {
  for (const panel of panels.values()) panel.frame(t, cursor);
});
const calloutTracker = new CalloutTracker();
loop.listen((t) => {
  const next = calloutTracker.update(model, t, layout.value.ring);
  if (next !== null) callouts.value = next;
});
// Checked every frame rather than on "resize" alone: emulated viewports do not always fire it,
// and two property reads per frame cost nothing.
let viewport = [window.innerWidth, window.innerHeight];
loop.listen(() => {
  const { innerWidth: w, innerHeight: h } = window;
  if (w !== viewport[0] || h !== viewport[1]) {
    viewport = [w, h];
    layout.value = computeLayout(w, h);
    const { stage, ring } = layout.value;
    host?.resize(stage.w, stage.h, ring);
  }
});
loop.start();

const fixture = fixtureFromQuery(window.location.search);
view.status.value = `loading ${fixture} run…`;
loadLog(FIXTURES[fixture])
  .then(({ values, badLines }) => {
    const result = model.ingest(values);
    void webLayout.request();
    clock.setEnd(model.store.endTime);
    clock.play();
    const problems = [
      badLines > 0 ? `${badLines} unreadable lines` : null,
      result.stopped === undefined
        ? null
        : `stopped at event ${result.appended + 1}: ${result.stopped.status}`,
    ].filter((p) => p !== null);
    view.status.value = problems.length === 0 ? null : problems.join(" · ");
  })
  .catch((error: unknown) => {
    view.status.value = error instanceof Error ? error.message : String(error);
  });

// Development only: a handle for inspecting the running cockpit from the console.
if (import.meta.env.DEV) {
  (window as unknown as { __repro: unknown }).__repro = { model, clock, webLayout, host, layout };
}
