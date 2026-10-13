/**
 * The cockpit's focus (DESIGN.md "Panels": clicking any row, cell or node focuses it). One focus
 * at a time, set by a click or the keyboard. It highlights its files and symbols on the stage,
 * pins its file on the ring, outlines its row or cell in the panels, and opens the evidence
 * drawer. Focus is UI state, not an event: the stage stays a pure function of (events, t,
 * motion, focus).
 */
import { type ChangeIndex, testFile } from "../model/changes";
import type { CockpitState } from "../model/cockpit";

export type Focus =
  | { readonly kind: "claim"; readonly id: string }
  | { readonly kind: "file"; readonly file: string }
  | { readonly kind: "symbol"; readonly symbol: string; readonly file: string }
  /** A check by its index in the checks projection's list (append-only, so stable). */
  | { readonly kind: "check"; readonly index: number }
  | { readonly kind: "agent"; readonly id: string };

/** A stable string for a focus: equal foci have equal keys. */
export function focusKey(focus: Focus | null): string {
  if (focus === null) return "";
  switch (focus.kind) {
    case "claim":
      return `claim:${focus.id}`;
    case "file":
      return `file:${focus.file}`;
    case "symbol":
      return `symbol:${focus.symbol}`;
    case "check":
      return `check:${focus.index}`;
    case "agent":
      return `agent:${focus.id}`;
  }
}

/**
 * What the stage highlights for a focus: files (ring cards, module nodes) and symbols. The ring
 * pins the first of these files that has a card, in the order the focus names them.
 */
export interface FocusTargets {
  readonly key: string;
  readonly files: ReadonlySet<string>;
  readonly symbols: ReadonlySet<string>;
}

export const NO_FOCUS: FocusTargets = {
  key: "",
  files: new Set(),
  symbols: new Set(),
};

/** The files and symbols a focus points at, as of `state` (folded at the frame's cursor). */
export function focusTargets(
  focus: Focus | null,
  state: CockpitState,
  changes: ChangeIndex,
): FocusTargets {
  if (focus === null) return NO_FOCUS;
  const files = new Set<string>();
  const symbols = new Set<string>();
  const add = (target: { file?: string; symbol?: string; test?: string } | null | undefined) => {
    if (target?.file !== undefined) files.add(target.file);
    if (target?.symbol !== undefined) symbols.add(target.symbol);
    if (target?.test !== undefined) files.add(testFile(target.test));
  };
  switch (focus.kind) {
    case "claim": {
      const claim = state.claims.list[state.claims.byId.get(focus.id) ?? -1];
      for (const target of claim?.targets ?? []) add(target);
      break;
    }
    case "file":
      files.add(focus.file);
      for (const change of changes.changed)
        if (change.file === focus.file) symbols.add(change.symbol);
      break;
    case "symbol":
      files.add(focus.file);
      symbols.add(focus.symbol);
      break;
    case "check":
      add(state.checks.list[focus.index]?.target);
      break;
    case "agent":
      break;
  }
  return { key: focusKey(focus), files, symbols };
}
