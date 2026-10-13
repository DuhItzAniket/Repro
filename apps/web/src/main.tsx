import "@fontsource-variable/jetbrains-mono/wght.css";
import "./styles/tokens.css";
import "./styles/shell.css";
import { signal } from "@preact/signals";
import { render } from "preact";
import { FIXTURES, fixtureFromQuery, loadLog } from "./data/load";
import { PresentationClock } from "./model/clock";
import { CockpitModel } from "./model/cockpit";
import { type Motion, REDUCED_MOTION_QUERY } from "./motion/motion";
import { behaviourPanel } from "./panels/behaviour";
import { indexPanel } from "./panels/check-index";
import { dispatchPanel } from "./panels/dispatch";
import { type ExecutionSides, executionPanel } from "./panels/execution";
import { feedPanel } from "./panels/feed";
import { type Panel, PanelHost } from "./panels/panel";
import { routesPanel } from "./panels/routes";
import { signalsPanel } from "./panels/signals";
import { workspacePanel } from "./panels/workspace";
import { App } from "./shell/app";
import { FrameLoop } from "./shell/frame";
import { computeLayout } from "./shell/layout";
import { createTransportState, spaceToPause, syncTransport } from "./shell/transport";
import { createShellView } from "./shell/view";
import { FlashGovernor } from "./stage/governor";
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

// Reduced motion follows the system setting; the transport's toggle overrides it until the
// setting changes again (DESIGN.md "Motion").
const reducedQuery = window.matchMedia(REDUCED_MOTION_QUERY);
const reduced = signal(reducedQuery.matches);
reducedQuery.addEventListener("change", (event) => {
  reduced.value = event.matches;
});
const transportState = createTransportState();
const syncClock = () => syncTransport(transportState, clock);
window.addEventListener("keydown", (event) => {
  if (spaceToPause(event, clock)) syncClock();
});

render(
  <App
    layout={layout}
    view={view}
    callouts={callouts}
    executionSides={executionSides}
    transport={{ state: transportState, clock, reduced, onCommand: syncClock }}
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
    const governor = new FlashGovernor(model, webLayout);
    for (const layer of webLayers(model, webLayout, governor)) stage.add(layer);
    for (const layer of ringLayers(model, new AtlasService(defaultAtlasBuild())).layers) {
      stage.add(layer);
    }
    stage.add(streakLayer(model, governor));
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

/** Canvas 2D panels (B08, B09): each redraws only when its version or the motion changes. */
interface PanelDriver {
  frame(t: number, cursor: number, motion: Motion): boolean;
  resize(w: number, h: number, dpr: number): void;
  invalidate(): void;
}
const panelMakers: Record<string, () => Panel<never>> = {
  feed: () => feedPanel(model) as Panel<never>,
  execution: () => executionPanel(model, executionSides) as Panel<never>,
  workspace: () => workspacePanel(model) as Panel<never>,
  behaviour: () => behaviourPanel(model) as Panel<never>,
  routes: () => routesPanel(model) as Panel<never>,
  signals: () => signalsPanel(model) as Panel<never>,
  dispatch: () => dispatchPanel(model) as Panel<never>,
  index: () => indexPanel(model) as Panel<never>,
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
const loop = new FrameLoop(model, clock, view, undefined, reduced);
loop.listen((t, cursor, motion) => host?.frame(t, cursor, motion));
loop.listen((t, cursor, motion) => {
  for (const panel of panels.values()) panel.frame(t, cursor, motion);
});
const calloutTracker = new CalloutTracker();
loop.listen((t, _cursor, motion) => {
  const next = calloutTracker.update(model, t, layout.value.ring, motion);
  if (next !== null) callouts.value = next;
});
loop.listen(syncClock);
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
