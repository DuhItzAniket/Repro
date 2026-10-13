import type { Signal } from "@preact/signals";
import type { ComponentChildren } from "preact";
import { Header, rectStyle } from "./header";
import type { CockpitLayout, Rect } from "./layout";
import { PANELS, SIGNALS_PARTIAL_CAPTION } from "./panels";
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

export function App({ layout, view }: { layout: Signal<CockpitLayout>; view: ShellView }) {
  const l = layout.value;
  return (
    <div class="cockpit" data-mode={l.mode} style={{ height: `${l.contentHeight}px` }}>
      <Header rect={l.header} view={view} />
      <section
        class="stage"
        style={rectStyle(l.stage)}
        aria-label="Stage: dependency web, file ring and event streams"
      />
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
          />
        );
      })}
    </div>
  );
}
