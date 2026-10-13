import type { Signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import type { ExecutionSides } from "../panels/execution";
import { SideToggle } from "../panels/side-toggle";
import { type HudSnapshot, PerfHud } from "../stage/hud";
import type { Callout } from "../stage/streams/callouts";
import { Callouts } from "../stage/streams/callouts-view";
import { Header, rectStyle } from "./header";
import type { CockpitLayout, Rect } from "./layout";
import { PANELS, SIGNALS_PARTIAL_CAPTION } from "./panels";
import { Transport, type TransportProps } from "./transport";
import type { ShellView } from "./view";

export function PanelFrame(props: {
  id: string;
  title: string;
  rect: Rect;
  footer: string | null;
  children?: ComponentChildren;
}) {
  const titleId = `panel-${props.id}-title`;
  return (
    <section
      class="panel"
      data-panel={props.id}
      style={rectStyle(props.rect)}
      aria-labelledby={titleId}
    >
      <h2 class="panel-title" id={titleId}>
        {props.title}
      </h2>
      <div class="panel-body">{props.children}</div>
      {props.footer !== null && props.footer !== "" && <p class="panel-footer">{props.footer}</p>}
    </section>
  );
}

function footerFor(id: string, fixed: string | null, view: ShellView): string | null {
  if (id === "index") return view.indexFooter.value;
  if (id === "signals") return view.finished.value ? null : SIGNALS_PARTIAL_CAPTION;
  return fixed;
}

export interface AppProps {
  layout: Signal<CockpitLayout>;
  view: ShellView;
  /** Perf HUD snapshots (only with `?hud`). */
  hud?: Signal<HudSnapshot | null>;
  /** Callout boxes over the stage (B07). */
  callouts?: Signal<readonly Callout[]>;
  /** Which execution lanes are shown (B08). */
  executionSides?: Signal<ExecutionSides>;
  /** The replay transport (B10); its rectangle comes from the layout. */
  transport?: Omit<TransportProps, "rect">;
}

/** Panels drawn on a Canvas 2D (B08, B09): all eight. */
export const CANVAS_PANELS: ReadonlySet<string> = new Set([
  "feed",
  "execution",
  "workspace",
  "behaviour",
  "routes",
  "signals",
  "dispatch",
  "index",
]);

export function App({ layout, view, hud, callouts, executionSides, transport }: AppProps) {
  const l = layout.value;
  return (
    <div class="cockpit" data-mode={l.mode} style={{ height: `${l.contentHeight}px` }}>
      <Header rect={l.header} view={view} />
      <section
        class="stage"
        style={rectStyle(l.stage)}
        aria-label="Stage: dependency web, file ring and event streams"
      >
        <canvas class="stage-canvas" />
        {callouts !== undefined && <Callouts items={callouts} />}
        {hud !== undefined && <PerfHud hud={hud} />}
      </section>
      {transport !== undefined && <Transport rect={l.transport} {...transport} />}
      {PANELS.map((panel, i) => {
        const rect = l.panels[i];
        if (rect === undefined) return null;
        return (
          <PanelFrame
            key={panel.id}
            id={panel.id}
            title={panel.title}
            rect={rect}
            footer={footerFor(panel.id, panel.footer, view)}
          >
            {CANVAS_PANELS.has(panel.id) && (
              <canvas
                class="panel-canvas"
                data-panel={panel.id}
                role="img"
                aria-label={`${panel.title} (visual)`}
              />
            )}
            {panel.id === "execution" && executionSides !== undefined && (
              <SideToggle sides={executionSides} />
            )}
          </PanelFrame>
        );
      })}
    </div>
  );
}
