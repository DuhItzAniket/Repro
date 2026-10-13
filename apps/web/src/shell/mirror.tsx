/**
 * The accessible parallel DOM (DESIGN.md "Accessibility"): the canvases are not readable by
 * assistive technology, so their meaning is mirrored here.
 * - `FeedLog`: a visually hidden `role="log"` with throttled summaries of the investigation feed.
 * - `PanelMirror`: a panel's focusable rows as buttons (a table for the change×check index).
 *   The buttons are visually hidden; when one has keyboard focus, its panel outlines the row
 *   on the canvas, so sighted keyboard users see where they are.
 * - `FilePicker`: a select that focuses any file on the ring, hidden until it has focus.
 */
import type { Signal } from "@preact/signals";
import type { Focus } from "../focus/focus";
import type { PanelTarget } from "../panels/panel";

/** One announcement; `id` only grows, so trimming old entries never rewrites newer ones. */
export interface LogEntry {
  readonly id: number;
  readonly text: string;
}

export function FeedLog({ entries }: { entries: Signal<readonly LogEntry[]> }) {
  return (
    <div class="visually-hidden" role="log" aria-label="Investigation feed updates">
      {entries.value.map((entry) => (
        <p key={entry.id}>{entry.text}</p>
      ))}
    </div>
  );
}

export interface PanelMirrorProps {
  readonly title: string;
  readonly targets: Signal<readonly PanelTarget[]>;
  /** Column headers after the first when the mirror is a table. */
  readonly columns?: readonly string[];
  /** The key of the target the keyboard is on (its panel outlines it). */
  readonly keyboard: Signal<string>;
  readonly onFocus: (focus: Focus) => void;
}

function TargetButton({
  target,
  keyboard,
  onFocus,
}: {
  target: PanelTarget;
  keyboard: Signal<string>;
  onFocus: (focus: Focus) => void;
}) {
  return (
    <button
      type="button"
      class="mirror-button"
      onFocus={() => {
        keyboard.value = target.key;
      }}
      onBlur={() => {
        if (keyboard.value === target.key) keyboard.value = "";
      }}
      onClick={() => onFocus(target.focus)}
    >
      {target.label}
    </button>
  );
}

export function PanelMirror({ title, targets, columns, keyboard, onFocus }: PanelMirrorProps) {
  const listed = targets.value.filter((t) => t.listed);
  if (columns !== undefined) {
    return (
      <table class="visually-hidden">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Name</th>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {listed.map((t) => (
            <tr key={t.key}>
              <th scope="row">
                <TargetButton target={t} keyboard={keyboard} onFocus={onFocus} />
              </th>
              {(t.cells ?? []).map((cell, c) => (
                <td key={columns[c] ?? c}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return (
    <ul class="visually-hidden" aria-label={title}>
      {listed.map((t) => (
        <li key={t.key}>
          <TargetButton target={t} keyboard={keyboard} onFocus={onFocus} />
        </li>
      ))}
    </ul>
  );
}

export function FilePicker({
  files,
  onFocus,
}: {
  files: Signal<readonly string[]>;
  onFocus: (focus: Focus) => void;
}) {
  return (
    <label class="file-picker">
      <span>Focus a file</span>
      <select
        onChange={(event) => {
          const file = (event.currentTarget as HTMLSelectElement).value;
          if (file !== "") onFocus({ kind: "file", file });
        }}
      >
        <option value="">Choose…</option>
        {files.value.map((file) => (
          <option key={file} value={file}>
            {file}
          </option>
        ))}
      </select>
    </label>
  );
}
