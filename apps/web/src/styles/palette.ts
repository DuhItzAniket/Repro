/**
 * The DESIGN.md palette for Canvas 2D drawing. It mirrors `tokens.css`; a test keeps the two in
 * step, because canvases cannot read CSS custom properties without a computed-style round trip
 * on every draw.
 */
export const COLOR = {
  bg: "#080808",
  panel: "#121212",
  border: "#232323",
  text: "#d6d6d6",
  dim: "#868686",
  faint: "#3a3a3a",
  hot: "#ffffff",
  flag: "#b48f9c",
  flagDeep: "#6e4e5a",
  ok: "#8fb4a8",
  violet: "#7d7390",
} as const;

/** CSS custom property each colour comes from. */
export const TOKEN_OF: Readonly<Record<keyof typeof COLOR, string>> = {
  bg: "--bg",
  panel: "--panel",
  border: "--panel-border",
  text: "--text",
  dim: "--text-dim",
  faint: "--text-faint",
  hot: "--hot",
  flag: "--flag",
  flagDeep: "--flag-deep",
  ok: "--ok",
  violet: "--violet",
};

export const MONO = `"JetBrains Mono Variable", "IBM Plex Mono", ui-monospace, monospace`;
