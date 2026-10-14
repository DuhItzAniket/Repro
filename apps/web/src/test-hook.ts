/**
 * The visual-regression hook (B12; ADR-0009). With `?test` in the URL the app installs
 * `window.__reproTest`. `renderAt(t)` resolves once the frame at `t` is on screen and everything
 * that affects its pixels has settled:
 * - the log is loaded;
 * - the web layout and the ring's text atlas are ready (workers);
 * - the web fonts are loaded and the panels redrawn with them;
 * - the clock is paused at `t`.
 *
 * The stage also runs at a fixed device-pixel ratio in this mode (no adaptive DPR), so
 * screenshots do not depend on how fast the machine renders.
 *
 * `summary()` (C08) describes what the cockpit holds, for the Gate C test: a live run and its
 * replay must hold the same events in the same order, and so show the same state.
 */
import type { Signal } from "@preact/signals";
import type { Focus } from "./focus/focus";
import type { ClockMode, PresentationClock } from "./model/clock";
import { type CockpitModel, type HeaderCounters, headerCounters } from "./model/cockpit";
import type { StageHost } from "./stage/host";
import { clampLook, DEFAULT_LOOK, type Look } from "./stage/look";
import type { RingModel } from "./stage/ring/layers";
import type { LayoutService } from "./stage/web/layout-service";

export interface RenderOptions {
  readonly focus?: Focus | null;
  readonly reduced?: boolean;
  /** The viewer's look (B15), clamped like a stored one; the default when omitted. */
  readonly look?: unknown;
  /** Whether the stage settings menu is open (B15). */
  readonly settings?: boolean;
}

export interface CockpitSummary {
  readonly runId: string | null;
  readonly events: number;
  /** FNV-1a (32-bit, hex) over the event IDs in store order. */
  readonly idsDigest: string;
  readonly kinds: Readonly<Record<string, number>>;
  /** The header's counters at the end of the data. */
  readonly counters: HeaderCounters;
  /** The last `blast.computed` payload, if any. */
  readonly blast: unknown;
  /** IDs of the graph's module nodes, sorted. */
  readonly modules: readonly string[];
  readonly finished: boolean;
  readonly mode: ClockMode;
  /** Presentation time of the last event (ms). */
  readonly end: number;
}

export interface TestHook {
  /** Shows the frame at `t` (ms of run time) and resolves when it is drawn. */
  renderAt(t: number, options?: RenderOptions): Promise<{ readonly litPixels: number }>;
  /** What the cockpit holds now. */
  summary(): CockpitSummary;
}

function fnv1a(text: string, hash: number): number {
  let h = hash;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h;
}

export function summarise(model: CockpitModel, mode: ClockMode): CockpitSummary {
  const { store } = model;
  const kinds: Record<string, number> = {};
  let digest = 0x811c9dc5;
  let blast: unknown = null;
  const modules: string[] = [];
  for (let i = 0; i < store.length; i++) {
    const event = store.event(i);
    if (event === null) continue;
    kinds[event.kind] = (kinds[event.kind] ?? 0) + 1;
    digest = fnv1a(`${event.id}\n`, digest);
    if (event.kind === "blast.computed") blast = event.payload;
    if (event.kind === "graph.node" && event.payload.node.type === "module")
      modules.push(event.payload.node.id);
  }
  return {
    runId: store.runId,
    events: store.length,
    idsDigest: digest.toString(16).padStart(8, "0"),
    kinds,
    counters: headerCounters(model.stateAtTime(store.endTime).state),
    blast,
    modules: modules.sort(),
    finished: (kinds["run.finished"] ?? 0) > 0,
    mode,
    end: store.endTime,
  };
}

export interface TestHookDeps {
  readonly model: CockpitModel;
  readonly clock: PresentationClock;
  readonly layout: LayoutService;
  readonly ring: RingModel;
  readonly host: StageHost | null;
  readonly focus: Signal<Focus | null>;
  readonly reduced: Signal<boolean>;
  readonly look: Signal<Look>;
  readonly settings: Signal<boolean>;
  /** Forces every panel to redraw (after fonts load). */
  readonly invalidatePanels: () => void;
}

const nextFrame = () => new Promise<number>((resolve) => requestAnimationFrame(resolve));

async function until(ready: () => boolean, what: string, timeoutMs = 60_000): Promise<void> {
  const start = performance.now();
  while (!ready()) {
    if (performance.now() - start > timeoutMs)
      throw new Error(`renderAt: timed out waiting for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

export function installTestHook(deps: TestHookDeps): void {
  const hook: TestHook = {
    async renderAt(t, options = {}) {
      const { model, clock, layout, ring, host } = deps;
      await until(() => model.store.length > 0 && clock.end > 0, "the log");
      await until(() => layout.positions !== null, "the web layout");
      ring.sync();
      await until(
        () => ring.content.cards.length === 0 || ring.atlas.bitmap !== null,
        "the ring atlas",
      );
      await document.fonts.load('400 10px "JetBrains Mono Variable"');
      await document.fonts.load('700 10px "JetBrains Mono Variable"');
      await document.fonts.ready;
      deps.focus.value = options.focus ?? null;
      deps.reduced.value = options.reduced ?? false;
      deps.look.value = options.look === undefined ? DEFAULT_LOOK : clampLook(options.look);
      deps.settings.value = options.settings ?? false;
      clock.pause();
      clock.seek(t);
      deps.invalidatePanels();
      // One frame to update and draw everything at t, one more for the DOM to settle.
      await nextFrame();
      await nextFrame();
      await nextFrame();
      return { litPixels: host?.probeLitPixels() ?? 0 };
    },
    summary: () => summarise(deps.model, deps.clock.mode),
  };
  (window as unknown as { __reproTest: TestHook }).__reproTest = hook;
}
