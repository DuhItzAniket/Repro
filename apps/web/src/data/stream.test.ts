import { describe, expect, it } from "vitest";
import { EventStore } from "../model/store";
import { runEvents } from "../model/test-support";
import {
  CLOSE,
  FIRST_RETRY_MS,
  GAP_CLOSE,
  MAX_RETRY_MS,
  RunStream,
  type StreamSink,
  type WebSocketLike,
} from "./stream";

/** A socket the test drives by hand. */
class FakeSocket implements WebSocketLike {
  onmessage: WebSocketLike["onmessage"] = null;
  onclose: WebSocketLike["onclose"] = null;
  onopen: WebSocketLike["onopen"] = null;
  closedWith: { code?: number; reason?: string } | null = null;
  constructor(readonly url: string) {}
  close(code?: number, reason?: string): void {
    this.closedWith = {
      ...(code === undefined ? {} : { code }),
      ...(reason === undefined ? {} : { reason }),
    };
  }
  open(): void {
    this.onopen?.();
  }
  send(frame: object): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  events(events: readonly unknown[]): void {
    this.send({ type: "events", events });
  }
  end(code: number, reason = ""): void {
    this.onclose?.({ code, reason });
  }
}

function harness() {
  const store = new EventStore();
  const sockets: FakeSocket[] = [];
  const timers: { callback: () => void; ms: number }[] = [];
  const log: string[] = [];
  const sink: StreamSink = {
    ingest: (events) => store.appendAll(events),
    held: () => store.length,
    caughtUp: (seq) => log.push(`caught up ${seq}`),
    ended: () => log.push("ended"),
    status: (text) => log.push(`status ${text}`),
  };
  const stream = new RunStream(
    (from) => `ws://engine/runs/r/events?from=${from}`,
    sink,
    (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    {
      set: (callback, ms) => timers.push({ callback, ms }),
      clear: () => undefined,
    },
  );
  const last = () => sockets[sockets.length - 1] as FakeSocket;
  return { store, sockets, timers, log, stream, last };
}

const EVENTS = runEvents().slice(0, 40);

describe("RunStream", () => {
  it("replays, catches up, follows live and ends", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().events(EVENTS.slice(0, 20));
    h.last().send({ type: "caught_up", seq: 20 });
    h.last().events(EVENTS.slice(18, 30)); // overlaps the replay: duplicates are ignored
    h.last().end(CLOSE.normal, "finished");
    expect(h.store.length).toBe(30);
    expect(h.log).toEqual(["status null", "caught up 20", "ended"]);
    expect(h.sockets.map((s) => s.url)).toEqual(["ws://engine/runs/r/events?from=0"]);
  });

  it("reconnects from what the store holds when a frame skips events", () => {
    const h = harness();
    h.stream.start();
    h.last().events(EVENTS.slice(0, 10));
    h.last().events(EVENTS.slice(12, 20)); // seq 11 and 12 never arrived
    expect(h.sockets[0]?.closedWith).toEqual({ code: GAP_CLOSE, reason: "gap" });
    expect(h.last().url).toBe("ws://engine/runs/r/events?from=10");
    h.last().events(EVENTS.slice(10, 20));
    expect(h.store.length).toBe(20);
  });

  it("resyncs at once when the engine drops it for falling behind", () => {
    const h = harness();
    h.stream.start();
    h.last().events(EVENTS.slice(0, 5));
    h.last().end(CLOSE.resync, "resync");
    expect(h.sockets).toHaveLength(2);
    expect(h.last().url).toBe("ws://engine/runs/r/events?from=5");
    expect(h.timers).toHaveLength(0);
  });

  it("retries a lost connection with growing delays, then resets after a good connection", () => {
    const h = harness();
    h.stream.start();
    for (let i = 0; i < 6; i++) {
      h.last().end(1006);
      const timer = h.timers[h.timers.length - 1];
      timer?.callback();
    }
    expect(h.timers.map((t) => t.ms)).toEqual([
      FIRST_RETRY_MS,
      FIRST_RETRY_MS * 2,
      FIRST_RETRY_MS * 4,
      FIRST_RETRY_MS * 8,
      MAX_RETRY_MS,
      MAX_RETRY_MS,
    ]);
    h.last().open();
    h.last().end(1006);
    expect(h.timers[h.timers.length - 1]?.ms).toBe(FIRST_RETRY_MS);
  });

  it.each([
    [CLOSE.unknownRun, "", "status event stream: the engine has no such run"],
    [CLOSE.badRequest, "bad ?from=", "status event stream: bad ?from="],
    [CLOSE.policy, "", "status event stream: refused (1008)"],
  ])("reports a refusal (%i) and does not retry", (code, reason, line) => {
    const h = harness();
    h.stream.start();
    h.last().end(code, reason);
    expect(h.log).toEqual([line]);
    expect(h.timers).toHaveLength(0);
    h.stream.start();
    expect(h.sockets).toHaveLength(1);
  });

  it("stops on an event the store rejects, and on a frame it cannot read", () => {
    const h = harness();
    h.stream.start();
    h.last().events([{ ...EVENTS[0], v: 99 }]);
    expect(h.log).toEqual(["status event stream stopped: unsupported envelope version 99"]);
    expect(h.last().closedWith).toEqual({});

    const g = harness();
    g.stream.start();
    g.last().onmessage?.({ data: "not json" });
    expect(g.log).toEqual(["status the event stream sent a frame this cockpit cannot read"]);
  });

  it("ignores a stopped socket's late events", () => {
    const h = harness();
    h.stream.start();
    const first = h.last();
    h.stream.stop();
    first.events(EVENTS.slice(0, 3));
    expect(h.store.length).toBe(0);
  });
});
