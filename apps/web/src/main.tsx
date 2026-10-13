import "@fontsource-variable/jetbrains-mono/wght.css";
import "./styles/tokens.css";
import "./styles/shell.css";
import { signal } from "@preact/signals";
import { render } from "preact";
import { FIXTURES, fixtureFromQuery, loadLog } from "./data/load";
import { type DrawerView, drawerView } from "./focus/evidence";
import { type Focus, type FocusTargets, focusKey, focusTargets, NO_FOCUS } from "./focus/focus";
import { PresentationClock } from "./model/clock";
import { CockpitModel } from "./model/cockpit";
import { type Motion, REDUCED_MOTION_QUERY } from "./motion/motion";
import { behaviourPanel } from "./panels/behaviour";
import { indexPanel } from "./panels/check-index";
import { dispatchPanel } from "./panels/dispatch";
import { type ExecutionSides, executionPanel } from "./panels/execution";
import { feedPanel } from "./panels/feed";
import { type Highlight, type Panel, PanelHost, type PanelTarget } from "./panels/panel";
import { routesPanel } from "./panels/routes";
import { signalsPanel } from "./panels/signals";
import { workspacePanel } from "./panels/workspace";
import { FeedAnnouncer } from "./shell/announcer";
import { App } from "./shell/app";
import { FrameLoop } from "./shell/frame";
import { computeLayout } from "./shell/layout";
import type { LogEntry } from "./shell/mirror";
import { createTransportState, formatTime, spaceToPause, syncTransport } from "./shell/transport";
import { createShellView } from "./shell/view";
import { focusLayer } from "./stage/focus-layer";
import { FlashGovernor } from "./stage/governor";
import { hitStage } from "./stage/hit";
import { StageHost } from "./stage/host";
import { type HudSnapshot, pollHud } from "./stage/hud";
import { AtlasService, defaultAtlasBuild } from "./stage/ring/atlas-service";
import { ringLayers } from "./stage/ring/layers";
import { type Callout, CalloutTracker } from "./stage/streams/callouts";
import { streakLayer } from "./stage/streams/layers";
import { webLayers } from "./stage/web/layers";
import { computeInline, LayoutService, workerCompute } from "./stage/web/layout-service";
import { installTestHook } from "./test-hook";

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
/** `?test`: the visual-regression mode (fixed DPR, `window.__reproTest`; B12). */
const testMode = params.has("test");
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

// Focus (B11): one focus for the stage, the panels and the evidence drawer.
const focus = signal<Focus | null>(null);
const keyboard = signal("");
const drawer = signal<DrawerView | null>(null);
const feedLog = signal<readonly LogEntry[]>([]);
let feedId = 0;
const ringFiles = signal<readonly string[]>([]);
const stageLabel = signal("Stage: dependency web, file ring and event streams");
const mirrorTargets = {
  routes: signal<readonly PanelTarget[]>([]),
  dispatch: signal<readonly PanelTarget[]>([]),
  index: signal<readonly PanelTarget[]>([]),
};
const setFocus = (next: Focus | null) => {
  focus.value = next;
};
/** What panels outline; rewritten in place when the focus or the keyboard moves. */
const highlight: { -readonly [K in keyof Highlight]: string } = { selected: "", keyboard: "" };
focus.subscribe((f) => {
  highlight.selected = focusKey(f);
});
keyboard.subscribe((key) => {
  highlight.keyboard = key;
});

window.addEventListener("keydown", (event) => {
  if (spaceToPause(event, clock)) syncClock();
  // Escape closes the drawer from anywhere (the drawer handles it first when it has focus).
  if (event.key === "Escape" && !event.defaultPrevented && focus.value !== null) setFocus(null);
});

render(
  <App
    layout={layout}
    view={view}
    callouts={callouts}
    executionSides={executionSides}
    transport={{ state: transportState, clock, reduced, onCommand: syncClock }}
    focus={{
      drawer,
      targets: mirrorTargets,
      keyboard,
      feed: feedLog,
      files: ringFiles,
      stageLabel,
      onFocus: setFocus,
    }}
    {...(hud === undefined ? {} : { hud })}
  />,
  root,
);

/** The ring's content and geometry, shared by the ring layers, the focus layer and hit tests. */
const { ring: ringModel, layers: ringStageLayers } = ringLayers(
  model,
  new AtlasService(defaultAtlasBuild()),
);

/** The WebGL stage. The rest of the cockpit works without it if WebGL 2 is unavailable. */
function mountStage(): StageHost | null {
  const canvas = root?.querySelector<HTMLCanvasElement>(".stage-canvas");
  if (canvas === null || canvas === undefined) return null;
  try {
    const stage = new StageHost(canvas, {
      devicePixelRatio: window.devicePixelRatio,
      ...(testMode ? { fixedDpr: 1 } : {}),
    });
    const governor = new FlashGovernor(model, webLayout);
    for (const layer of webLayers(model, webLayout, governor)) stage.add(layer);
    for (const layer of ringStageLayers) stage.add(layer);
    stage.add(streakLayer(model, governor));
    stage.add(focusLayer(model, webLayout, ringModel));
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
/** The latest frame's inputs, for clicks between frames. */
let frameMotion: Motion = { speed: 1, reduced: false };
let stageFocus: FocusTargets = NO_FOCUS;
root.querySelector(".stage-canvas")?.addEventListener("click", (event) => {
  const { offsetX, offsetY } = event as MouseEvent;
  const hit = hitStage(
    offsetX,
    offsetY,
    { t: clock.time(), ring: layout.value.ring, motion: frameMotion, focus: stageFocus },
    model,
    ringModel,
    webLayout,
  );
  if (hit !== null) setFocus(hit);
});

/** Canvas 2D panels (B08, B09): each redraws only when its version, the motion or the focus changes. */
interface PanelDriver {
  frame(t: number, cursor: number, motion: Motion, highlight: Highlight): boolean;
  resize(w: number, h: number, dpr: number): void;
  invalidate(): void;
  hit(x: number, y: number): PanelTarget | null;
  onTargets: ((targets: readonly PanelTarget[]) => void) | null;
}
const panelMakers: Record<string, () => Panel<never>> = {
  feed: () => feedPanel(model) as Panel<never>,
  execution: () => executionPanel(model, executionSides) as Panel<never>,
  workspace: () =>
    workspacePanel(model, () =>
      focus.value?.kind === "agent" ? focus.value.id : null,
    ) as Panel<never>,
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
  const panelHost = new PanelHost(make(), canvas);
  const mirror = mirrorTargets[canvas.dataset.panel as keyof typeof mirrorTargets] ?? null;
  if (mirror !== null) panelHost.onTargets = (targets) => (mirror.value = targets);
  canvas.addEventListener("click", (event) => {
    const hit = panelHost.hit(event.offsetX, event.offsetY);
    if (hit !== null) setFocus(hit.focus);
  });
  panels.set(canvas, panelHost);
  panelSizes.observe(canvas);
}
// The panels draw text in the web font; repaint once it has loaded.
void document.fonts.ready.then(() => {
  for (const panel of panels.values()) panel.invalidate();
});
const loop = new FrameLoop(model, clock, view, undefined, reduced);
// Focus targets for the stage: resolved when the focus or the cursor changes.
let resolvedFocus = "";
let resolvedCursor = -1;
loop.listen((_t, cursor, motion) => {
  frameMotion = motion;
  const key = highlight.selected;
  if (key !== resolvedFocus || (key !== "" && cursor !== resolvedCursor)) {
    resolvedFocus = key;
    resolvedCursor = cursor;
    stageFocus = focusTargets(focus.value, model.folder.stateAt(cursor), model.changes);
  }
});
loop.listen((t, cursor, motion) => host?.frame(t, cursor, motion, stageFocus));
loop.listen((t, cursor, motion) => {
  for (const panel of panels.values()) panel.frame(t, cursor, motion, highlight);
});
// The evidence drawer follows the focus, refreshed at most four times a second while playing.
let drawerFor = "";
let drawerCursor = -1;
let drawerAt = 0;
loop.listen((_t, cursor) => {
  const key = highlight.selected;
  if (key === "") {
    if (drawer.value !== null) drawer.value = null;
    drawerFor = "";
    return;
  }
  const now = performance.now();
  if (key === drawerFor && (cursor === drawerCursor || now - drawerAt < 250)) return;
  drawerFor = key;
  drawerCursor = cursor;
  drawerAt = now;
  drawer.value = drawerView(focus.value as Focus, model, cursor);
});
// Screen readers: throttled feed summaries, and a stage description at most once a second.
const announcer = new FeedAnnouncer(() => performance.now());
let labelAt = 0;
let ringVersion = -1;
loop.listen((t, cursor) => {
  const summary = announcer.next(model, cursor);
  if (summary !== null)
    feedLog.value = [...feedLog.value.slice(-19), { id: feedId++, text: summary }];
  if (ringModel.version !== ringVersion) {
    ringVersion = ringModel.version;
    ringFiles.value = ringModel.content.cards.map((card) => card.file);
  }
  const now = performance.now();
  if (now - labelAt < 1000) return;
  labelAt = now;
  const edges = model.kinds.count("graph.edge", cursor);
  const files = ringModel.content.cards.filter((card) => card.appear <= t).length;
  const streaks = host?.info.instances.streaks ?? 0;
  const focused = drawer.value === null ? "" : `, focused on ${drawer.value.title}`;
  const next = `Stage at ${formatTime(t)}: ${edges} dependency edges, ${files} files on the ring, ${streaks} events streaming${focused}.`;
  if (next !== stageLabel.value) stageLabel.value = next;
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
if (testMode) {
  installTestHook({
    model,
    clock,
    layout: webLayout,
    ring: ringModel,
    host,
    focus,
    reduced,
    invalidatePanels: () => {
      for (const panel of panels.values()) panel.invalidate();
    },
  });
}

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
  (window as unknown as { __repro: unknown }).__repro = {
    model,
    clock,
    webLayout,
    host,
    layout,
    focus,
  };
}
