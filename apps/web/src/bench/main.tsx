import { FlashGovernor } from "../stage/governor";
import "@fontsource-variable/jetbrains-mono/wght.css";
import "../styles/tokens.css";
import "../styles/shell.css";
import { signal } from "@preact/signals";
import { render } from "preact";
import { FIXTURES, fixtureFromQuery, loadLog } from "../data/load";
import { CockpitModel } from "../model/cockpit";
import { computeLayout } from "../shell/layout";
import { type HudSnapshot, PerfHud, snapshot } from "../stage/hud";
import { AtlasService, defaultAtlasBuild } from "../stage/ring/atlas-service";
import { ringLayers } from "../stage/ring/layers";
import { webLayers } from "../stage/web/layers";
import { computeInline, LayoutService, workerCompute } from "../stage/web/layout-service";
import { proxyLayers } from "./proxies";
import { type BenchReport, type BenchResult, busiestSecond, runCase } from "./run";

declare global {
  interface Window {
    __REPRO_BENCH__?: BenchReport | { error: string };
  }
}

const params = new URLSearchParams(window.location.search);
const seconds = Number(params.get("seconds") ?? "8");
const ratios = (params.get("dpr") ?? "1,1.5,2").split(",").map(Number);
/** `real` (default): every stage layer; `proxy`: the B04 proxies only. */
const layerSet = params.get("layers") === "proxy" ? "proxy" : "real";

const hud = signal<HudSnapshot | null>(null);
const status = signal("loading the stress run…");
const report = signal<BenchReport | null>(null);

function Page() {
  return (
    <div class="bench">
      <canvas id="bench-canvas" class="bench-canvas" />
      <PerfHud hud={hud} />
      <pre class="bench-report">
        {report.value === null ? status.value : JSON.stringify(report.value, null, 2)}
      </pre>
    </div>
  );
}

async function main(): Promise<void> {
  const root = document.getElementById("app");
  if (root === null) throw new Error("#app missing");
  render(<Page />, root);
  const model = new CockpitModel();
  const fixture = params.has("log") ? fixtureFromQuery(window.location.search) : "stress";
  const { values } = await loadLog(FIXTURES[fixture]);
  model.ingest(values);
  const webLayout = new LayoutService(
    model.graph,
    typeof Worker === "undefined" ? computeInline : workerCompute(),
  );
  status.value = "laying out the dependency web…";
  const layoutStart = performance.now();
  await webLayout.request();
  const layoutMs = performance.now() - layoutStart;
  // Full load: the flash governor's cap is lifted, so the bench measures every element the
  // layers can draw (every bunch of strands), not the safer subset the app shows.
  const layers = () => {
    if (layerSet === "proxy") return proxyLayers(model);
    const ring = ringLayers(model, new AtlasService(defaultAtlasBuild()));
    const governor = new FlashGovernor(model, webLayout, Number.POSITIVE_INFINITY, ring.ring);
    return [...webLayers(model, webLayout, governor, ring.ring), ...ring.layers];
  };
  const start = busiestSecond(model) - 400;
  const { stage, ring } = computeLayout(window.innerWidth, window.innerHeight);
  const results: BenchResult[] = [];
  let gpu = "";
  let lastHud = 0;
  for (const dpr of ratios) {
    status.value = `measuring at dpr ${dpr} for ${seconds} s…`;
    // A fresh canvas (and WebGL context) per case, so no state carries over between ratios.
    const old = document.getElementById("bench-canvas") as HTMLCanvasElement;
    const canvas = document.createElement("canvas");
    canvas.id = "bench-canvas";
    canvas.className = "bench-canvas";
    old.replaceWith(canvas);
    const run = await runCase(
      canvas,
      model,
      layers,
      { width: stage.w, height: stage.h, ring },
      start,
      { dpr, seconds },
      (host) => {
        const now = performance.now();
        if (now - lastHud > 250) {
          lastHud = now;
          hud.value = snapshot(host.info, host.stats.summarise());
        }
      },
    );
    results.push(run.result);
    gpu = run.gpu;
  }
  const done: BenchReport = {
    gpu,
    userAgent: navigator.userAgent,
    devicePixelRatio: window.devicePixelRatio,
    burstAtMs: start + 400,
    layers: layerSet,
    layoutMs: Math.round(layoutMs),
    results,
  };
  window.__REPRO_BENCH__ = done;
  report.value = done;
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  window.__REPRO_BENCH__ = { error: message };
  status.value = `failed: ${message}`;
});
