/**
 * The animation-frame loop: presentation time from the clock, the fold cursor for that time,
 * and listeners called with both. The shell view is updated only when the cursor moves; the
 * stage (B04) will listen to every frame.
 */

import type { PresentationClock } from "../model/clock";
import type { CockpitModel } from "../model/cockpit";
import type { ShellView } from "./view";

export interface FrameScheduler {
  request(callback: () => void): number;
  cancel(handle: number): void;
}

export type FrameListener = (t: number, cursor: number) => void;

export const browserScheduler: FrameScheduler = {
  request: (callback) => requestAnimationFrame(callback),
  cancel: (handle) => cancelAnimationFrame(handle),
};

export class FrameLoop {
  private readonly listeners = new Set<FrameListener>();
  private handle = 0;
  private running = false;
  private lastCursor = -1;

  constructor(
    private readonly model: CockpitModel,
    private readonly clock: PresentationClock,
    private readonly view: ShellView,
    private readonly scheduler: FrameScheduler = browserScheduler,
  ) {}

  /** Adds a per-frame listener; returns a function that removes it. */
  listen(listener: FrameListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.handle = this.scheduler.request(this.frame);
  }

  stop(): void {
    this.running = false;
    this.scheduler.cancel(this.handle);
  }

  /** One frame. Public for tests; the scheduler calls it in the browser. */
  readonly frame = (): void => {
    if (!this.running) return;
    this.clock.setEnd(this.model.store.endTime);
    const t = this.clock.time();
    const cursor = this.model.store.cursorAt(t);
    if (cursor !== this.lastCursor) {
      this.lastCursor = cursor;
      this.view.update(this.model.folder.stateAt(cursor));
    }
    for (const listener of this.listeners) listener(t, cursor);
    this.handle = this.scheduler.request(this.frame);
  };
}
