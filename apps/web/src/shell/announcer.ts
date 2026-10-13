/**
 * Summaries of the investigation feed for screen readers (DESIGN.md "Accessibility": a visually
 * hidden `role="log"` with throttled summaries, at most about one every 2 s). Each summary covers
 * every line since the previous one, so nothing is skipped, only batched. A paused clock adds no
 * lines, so it announces nothing (WCAG 2.2.2); scrubbing back resets without announcing.
 */
import type { CockpitModel } from "../model/cockpit";

/** Minimum wall-clock time between two announcements. */
export const ANNOUNCE_MS = 2000;

export class FeedAnnouncer {
  private announced = 0;
  private lastAt = Number.NEGATIVE_INFINITY;

  constructor(private readonly now: () => number) {}

  /** The next summary to announce for the feed as of `cursor`, or null (nothing new, or too soon). */
  next(model: CockpitModel, cursor: number): string | null {
    const count = model.kinds.count("log.line", cursor);
    if (count < this.announced) {
      this.announced = count; // scrubbed back: start again from here, quietly
      return null;
    }
    if (count === this.announced) return null;
    const now = this.now();
    if (now - this.lastAt < ANNOUNCE_MS) return null;
    const fresh = model.kinds.last("log.line", cursor, count - this.announced);
    let warnings = 0;
    for (const i of fresh) {
      const event = model.store.event(i);
      if (
        event?.kind === "log.line" &&
        event.payload.level !== "info" &&
        event.payload.level !== "debug"
      )
        warnings++;
    }
    const latest = model.store.event(fresh[fresh.length - 1] as number);
    const line =
      latest?.kind === "log.line" ? `${latest.payload.verb}: ${latest.payload.message}` : "";
    this.announced = count;
    this.lastAt = now;
    const batch = fresh.length === 1 ? line : `${fresh.length} new lines. Latest, ${line}`;
    return warnings === 0
      ? batch
      : `${batch} (${warnings} ${warnings === 1 ? "warning" : "warnings"})`;
  }
}
