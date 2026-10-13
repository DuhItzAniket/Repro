/** The eight panels (DESIGN.md "Panels"), in grid order: two rows of four. */

export interface PanelSpec {
  readonly id: string;
  readonly title: string;
  /** Static footer caption, if the panel has one. Dynamic footers are set by the app. */
  readonly footer: string | null;
}

export const PANELS: readonly PanelSpec[] = [
  { id: "feed", title: "Investigation feed", footer: null },
  { id: "execution", title: "Execution", footer: null },
  { id: "workspace", title: "Agent workspace", footer: null },
  { id: "behaviour", title: "Behaviour diff field", footer: "same input / different output" },
  { id: "routes", title: "Change routes", footer: "diff → symbols → tests → checks" },
  { id: "signals", title: "Signals", footer: null },
  { id: "dispatch", title: "Agents / dispatch", footer: "independent jobs / shared event bus" },
  { id: "index", title: "Change × check index", footer: null },
];

/** Shown under Signals until the run completes (DESIGN.md panel 6). */
export const SIGNALS_PARTIAL_CAPTION = "illustrative until run completes";
