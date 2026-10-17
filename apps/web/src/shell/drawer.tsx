/**
 * The evidence drawer (DESIGN.md "Panels"): the only "normal UI" surface, plain and readable.
 * Facts and tables are semantic tables; rows that point at another claim, check, file or symbol
 * are buttons that focus it. Escape closes the drawer and returns focus to where it was opened.
 */
import type { Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import type { DrawerSection, DrawerView } from "../focus/evidence";
import type { Focus } from "../focus/focus";
import { rectStyle } from "./header";
import type { Rect } from "./layout";

export interface DrawerProps {
  readonly rect: Rect;
  readonly view: Signal<DrawerView | null>;
  readonly onFocus: (focus: Focus | null) => void;
}

function Section({
  section,
  final,
  onFocus,
}: {
  section: DrawerSection;
  final: boolean;
  onFocus: DrawerProps["onFocus"];
}) {
  return (
    <section class="drawer-section">
      <h3>{section.title}</h3>
      {section.paragraphs?.map((p, i) => (
        <p key={i}>{p}</p>
      ))}
      {section.facts !== undefined && section.facts.length > 0 && (
        <table class="facts">
          <tbody>
            {section.facts.map((fact) => (
              <tr key={fact.label}>
                <th scope="row">{fact.label}</th>
                <td>{fact.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {section.table !== undefined && (
        <table class="rows">
          <caption class="visually-hidden">{section.table.caption}</caption>
          <thead>
            <tr>
              {section.table.columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {section.table.rows.length === 0 && (
              <tr>
                <td colSpan={section.table.columns.length}>{final ? "None." : "None yet."}</td>
              </tr>
            )}
            {section.table.rows.map((row, r) => (
              <tr key={r}>
                {row.cells.map((cell, c) =>
                  c === 0 && row.focus !== undefined ? (
                    <th key={c} scope="row">
                      <button type="button" class="link" onClick={() => onFocus(row.focus ?? null)}>
                        {cell}
                      </button>
                    </th>
                  ) : (
                    <td key={c}>{cell}</td>
                  ),
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function Drawer({ rect, view, onFocus }: DrawerProps) {
  const v = view.value;
  const title = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);
  const open = v !== null;
  const heading = v?.title ?? "";
  useEffect(() => {
    if (!open) return;
    // Remember where focus came from, then move it into the drawer.
    if (opener.current === null) opener.current = document.activeElement;
    title.current?.focus();
  }, [open, heading]);
  useEffect(() => {
    if (open) return;
    const back = opener.current;
    opener.current = null;
    if (back instanceof HTMLElement && back.isConnected) back.focus();
  }, [open]);
  if (v === null) return null;
  return (
    <aside
      class="drawer"
      aria-labelledby="drawer-title"
      style={rectStyle(rect)}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.preventDefault();
          onFocus(null);
        }
      }}
    >
      <header class="drawer-header">
        <h2 id="drawer-title" tabIndex={-1} ref={title}>
          {v.title}
        </h2>
        <button type="button" class="toggle" onClick={() => onFocus(null)}>
          Close
        </button>
      </header>
      <p class="drawer-subtitle">{v.subtitle}</p>
      {v.sections.map((section) => (
        <Section key={section.title} section={section} final={v.final} onFocus={onFocus} />
      ))}
    </aside>
  );
}
