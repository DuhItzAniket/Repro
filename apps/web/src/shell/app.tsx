import type { Signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import type { DrawerView } from "../focus/evidence";
import type { Focus } from "../focus/focus";
import type { ExecutionSides } from "../panels/execution";
import type { PanelTarget } from "../panels/panel";
import { SideToggle } from "../panels/side-toggle";
import { type HudSnapshot, PerfHud } from "../stage/hud";
import type { Callout } from "../stage/streams/callouts";
import { Callouts } from "../stage/streams/callouts-view";
import { Drawer } from "./drawer";
import { Header, rectStyle } from "./header";
import type { CockpitLayout, Rect } from "./layout";
import { FeedLog, FilePicker, type LogEntry, PanelMirror } from "./mirror";
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

/** Focus, the evidence drawer and the accessible mirrors (B11). */
export interface FocusUi {
  readonly drawer: Signal<DrawerView | null>;
  /** Focusable rows per panel id, as last drawn. */
  readonly targets: Readonly<Record<string, Signal<readonly PanelTarget[]>>>;
  /** The key of the row the keyboard is on. */
  readonly keyboard: Signal<string>;
  readonly feed: Signal<readonly LogEntry[]>;
  /** Files on the ring, for the stage's file picker. */
  readonly files: Signal<readonly string[]>;
  /** The stage canvas's accessible description. */
  readonly stageLabel: Signal<string>;
  readonly onFocus: (focus: Focus | null) => void;
}

/** Panels whose rows are mirrored for the keyboard; a table when columns are given. */
const MIRRORS: Readonly<Record<string, { title: string; columns?: readonly string[] }>> = {
  routes: { title: "Change routes" },
  dispatch: { title: "Agents" },
  index: { title: "Change × check index", columns: ["Status", "Related checks"] },
};

/** A panel's keyboard mirror, if it has one. */
function Mirror({ id, focus }: { id: string; focus: FocusUi }) {
  const spec = MIRRORS[id];
  const targets = focus.targets[id];
  if (spec === undefined || targets === undefined) return null;
  return (
    <PanelMirror {...spec} targets={targets} keyboard={focus.keyboard} onFocus={focus.onFocus} />
  );
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
  /** Focus, drawer and accessible mirrors (B11). */
  focus?: FocusUi;
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

export function App({ layout, view, hud, callouts, executionSides, transport, focus }: AppProps) {
  const l = layout.value;
  return (
    <div class="cockpit" data-mode={l.mode} style={{ height: `${l.contentHeight}px` }}>
      <Header rect={l.header} view={view} />
      {/* Landmarks: the header (banner), main (stage, transport, panels), the drawer (aside). */}
      <main class="cockpit-main">
        <section
          class="stage"
          style={rectStyle(l.stage)}
          aria-label="Stage: dependency web, file ring and event streams"
        >
          <canvas
            class="stage-canvas"
            role="img"
            aria-label={
              focus?.stageLabel.value ?? "Stage: dependency web, file ring and event streams"
            }
          />
          {focus !== undefined && <FilePicker files={focus.files} onFocus={focus.onFocus} />}
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
              {panel.id === "feed" && focus !== undefined && <FeedLog entries={focus.feed} />}
              {focus !== undefined && <Mirror id={panel.id} focus={focus} />}
            </PanelFrame>
          );
        })}
      </main>
      {focus !== undefined && (
        <Drawer rect={l.drawer} view={focus.drawer} onFocus={focus.onFocus} />
      )}
    </div>
  );
}
