import { MONO } from "../styles/palette";

/** Monospace advance as a share of the font size (JetBrains Mono: 600/1000 em). */
export const ADVANCE = 0.6;

export const font = (size: number, weight = 400): string => `${weight} ${size}px ${MONO}`;

/** Truncates `text` to `chars` characters with an ellipsis. */
export function clip(text: string, chars: number): string {
  if (chars <= 0) return "";
  return text.length <= chars ? text : `${text.slice(0, Math.max(0, chars - 1))}…`;
}

/** How many monospace characters of `size` px fit in `width` px. */
export const charsIn = (width: number, size: number): number =>
  Math.floor(width / (size * ADVANCE));

export const easeOutCubic = (x: number): number => 1 - (1 - Math.min(1, Math.max(0, x))) ** 3;
