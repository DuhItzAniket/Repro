import type { ReproEvent } from "@repro/events";

/**
 * One compact JSON object per line, LF line endings, trailing newline. Key order is the order
 * the generator builds objects in, which is fixed, so the output is byte-stable.
 */
export function toJsonl(events: readonly ReproEvent[]): string {
  let out = "";
  for (const event of events) out += `${JSON.stringify(event)}\n`;
  return out;
}
