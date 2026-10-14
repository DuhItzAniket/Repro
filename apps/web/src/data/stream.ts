/**
 * The engine's event stream for one run (C08; ARCHITECTURE §11): replay, `caught_up`, then live.
 *
 * The cockpit's store is the judge of continuity. Each frame's events go to it in order; a
 * duplicate (replay overlapping live) is ignored there, and a gap makes the client drop the
 * connection and reconnect with `?from=` the last `seq` it holds, so the engine's store, which is
 * authoritative, sends the rest. The server does the same with close code 4000 ("resync") when
 * this client falls behind. A lost connection is retried with backoff until the run has ended;
 * a refusal (unknown run, bad request) is reported and not retried.
 */
import type { AppendSummary } from "../model/store";

/** The part of the browser's `WebSocket` the client uses (a fake one in tests). */
export interface WebSocketLike {
  onmessage: ((event: { readonly data: unknown }) => void) | null;
  onclose: ((event: { readonly code: number; readonly reason: string }) => void) | null;
  onopen: (() => void) | null;
  close(code?: number, reason?: string): void;
}

export interface StreamSink {
  /** Appends events in order and says how far the store took them. */
  ingest(events: readonly unknown[]): AppendSummary;
  /** The last `seq` the store holds (0 when empty). */
  held(): number;
  /** The replay part is over: everything stored up to `seq` has been sent. */
  caughtUp(seq: number): void;
  /** The run has finished (or a stored run was replayed in full): nothing more will come. */
  ended(): void;
  /** A line for the status bar, or null to clear it. */
  status(text: string | null): void;
}

export interface Timers {
  set(callback: () => void, ms: number): unknown;
  clear(handle: unknown): void;
}

/** Close codes the engine uses (repro.api.stream). */
export const CLOSE = {
  normal: 1000,
  policy: 1008,
  resync: 4000,
  badRequest: 4400,
  unknownRun: 4404,
} as const;
/** The client's own close when the store reports a gap (4000–4999 are for applications). */
export const GAP_CLOSE = 4001;
export const FIRST_RETRY_MS = 500;
export const MAX_RETRY_MS = 5000;

type Frame = { type: "events"; events: unknown[] } | { type: "caught_up"; seq: number };

function parseFrame(data: unknown): Frame | null {
  if (typeof data !== "string") return null;
  try {
    const frame: unknown = JSON.parse(data);
    if (typeof frame !== "object" || frame === null) return null;
    const { type } = frame as { type?: unknown };
    if (type === "events" && Array.isArray((frame as { events?: unknown }).events))
      return frame as Frame;
    if (type === "caught_up" && typeof (frame as { seq?: unknown }).seq === "number")
      return frame as Frame;
    return null;
  } catch {
    return null;
  }
}

/** The browser's `WebSocket`, behind the narrow interface the client uses. */
export function browserSocket(url: string): WebSocketLike {
  const ws = new WebSocket(url);
  const socket: WebSocketLike = {
    onmessage: null,
    onclose: null,
    onopen: null,
    close: (code, reason) => ws.close(code, reason),
  };
  ws.onmessage = (event) => socket.onmessage?.({ data: event.data });
  ws.onclose = (event) => socket.onclose?.({ code: event.code, reason: event.reason });
  ws.onopen = () => socket.onopen?.();
  return socket;
}

export class RunStream {
  private socket: WebSocketLike | null = null;
  private retry: unknown = null;
  private failures = 0;
  private done = false;

  constructor(
    private readonly url: (from: number) => string,
    private readonly sink: StreamSink,
    private readonly connect: (url: string) => WebSocketLike,
    private readonly timers: Timers = {
      set: (callback, ms) => setTimeout(callback, ms),
      clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    },
  ) {}

  /** Connects from the last event the store holds. */
  start(): void {
    if (this.done || this.socket !== null) return;
    const socket = this.connect(this.url(this.sink.held()));
    this.socket = socket;
    socket.onopen = () => {
      this.failures = 0;
      this.sink.status(null);
    };
    socket.onmessage = (event) => this.onFrame(socket, event.data);
    socket.onclose = (event) => this.onClose(socket, event.code, event.reason);
  }

  /** Disconnects for good. */
  stop(): void {
    this.done = true;
    if (this.retry !== null) this.timers.clear(this.retry);
    this.retry = null;
    this.drop();
  }

  /** Forgets the current socket (its late events are ignored) and closes it. */
  private drop(code?: number, reason?: string): void {
    const socket = this.socket;
    this.socket = null;
    if (socket === null) return;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onopen = null;
    socket.close(code, reason);
  }

  private onFrame(socket: WebSocketLike, data: unknown): void {
    if (socket !== this.socket) return;
    const frame = parseFrame(data);
    if (frame === null) {
      this.sink.status("the event stream sent a frame this cockpit cannot read");
      this.stop();
      return;
    }
    if (frame.type === "caught_up") {
      this.sink.caughtUp(frame.seq);
      return;
    }
    const summary = this.sink.ingest(frame.events);
    const stopped = summary.stopped;
    if (stopped === undefined) return;
    if (stopped.status === "gap") {
      // Missing events: start again from what the store holds; the engine sends the rest.
      this.drop(GAP_CLOSE, "gap");
      this.start();
      return;
    }
    this.sink.status(`event stream stopped: ${stopped.reason}`);
    this.stop();
  }

  private onClose(socket: WebSocketLike, code: number, reason: string): void {
    if (socket !== this.socket) return;
    this.socket = null;
    if (code === CLOSE.normal) {
      this.done = true;
      this.sink.ended();
      return;
    }
    if (code === CLOSE.resync) {
      this.start(); // the engine dropped this client for falling behind: catch up from the store
      return;
    }
    if (code === CLOSE.unknownRun || code === CLOSE.badRequest || code === CLOSE.policy) {
      const why =
        code === CLOSE.unknownRun ? "the engine has no such run" : reason || `refused (${code})`;
      this.sink.status(`event stream: ${why}`);
      this.done = true;
      return;
    }
    const delay = Math.min(FIRST_RETRY_MS * 2 ** this.failures, MAX_RETRY_MS);
    this.failures += 1;
    this.sink.status(`connection to the engine lost; retrying in ${Math.ceil(delay / 1000)} s`);
    this.retry = this.timers.set(() => {
      this.retry = null;
      this.start();
    }, delay);
  }
}
