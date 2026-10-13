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
 */
import type { Signal } from "@preact/signals";
import type { Focus } from "./focus/focus";
import type { PresentationClock } from "./model/clock";
import type { CockpitModel } from "./model/cockpit";
import type { StageHost } from "./stage/host";
import type { RingModel } from "./stage/ring/layers";
import type { LayoutService } from "./stage/web/layout-service";

export interface RenderOptions {
  readonly focus?: Focus | null;
  readonly reduced?: boolean;
}

export interface TestHook {
  /** Shows the frame at `t` (ms of run time) and resolves when it is drawn. */
  renderAt(t: number, options?: RenderOptions): Promise<{ readonly litPixels: number }>;
}

export interface TestHookDeps {
  readonly model: CockpitModel;
  readonly clock: PresentationClock;
  readonly layout: LayoutService;
  readonly ring: RingModel;
  readonly host: StageHost | null;
  readonly focus: Signal<Focus | null>;
  readonly reduced: Signal<boolean>;
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
      clock.pause();
      clock.seek(t);
      deps.invalidatePanels();
      // One frame to update and draw everything at t, one more for the DOM to settle.
      await nextFrame();
      await nextFrame();
      await nextFrame();
      return { litPixels: host?.probeLitPixels() ?? 0 };
    },
  };
  (window as unknown as { __reproTest: TestHook }).__reproTest = hook;
}
