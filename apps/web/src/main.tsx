import "@fontsource-variable/jetbrains-mono/wght.css";
import "./styles/tokens.css";
import "./styles/shell.css";
import { signal } from "@preact/signals";
import { render } from "preact";
import { FIXTURES, fixtureFromQuery, loadLog } from "./data/load";
import { PresentationClock } from "./model/clock";
import { CockpitModel } from "./model/cockpit";
import { App } from "./shell/app";
import { FrameLoop } from "./shell/frame";
import { computeLayout } from "./shell/layout";
import { createShellView } from "./shell/view";

const root = document.getElementById("app");
if (root === null) throw new Error("Repro: #app root element is missing from index.html");

const model = new CockpitModel();
const clock = new PresentationClock(() => performance.now());
const view = createShellView();
const layout = signal(computeLayout(window.innerWidth, window.innerHeight));

render(<App layout={layout} view={view} />, root);
const loop = new FrameLoop(model, clock, view);
// Checked every frame rather than on "resize" alone: emulated viewports do not always fire it,
// and two property reads per frame cost nothing.
let viewport = [window.innerWidth, window.innerHeight];
loop.listen(() => {
  const { innerWidth: w, innerHeight: h } = window;
  if (w !== viewport[0] || h !== viewport[1]) {
    viewport = [w, h];
    layout.value = computeLayout(w, h);
  }
});
loop.start();

const fixture = fixtureFromQuery(window.location.search);
view.status.value = `loading ${fixture} run…`;
loadLog(FIXTURES[fixture])
  .then(({ values, badLines }) => {
    const result = model.ingest(values);
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
