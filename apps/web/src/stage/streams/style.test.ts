import type { ReproEvent } from "@repro/events";
import { describe, expect, it } from "vitest";
import { runEvents } from "../../model/test-support";
import { importance, LONGEST_LIFE, lifetime, streams, TINTS, tintOf, travel } from "./style";

const events = runEvents();
const find = (predicate: (e: ReproEvent) => boolean): ReproEvent => {
  const event = events.find(predicate);
  if (event === undefined) throw new Error("fixture lacks the event");
  return event;
};

describe("tint mapping (B07: follows DESIGN.md)", () => {
  it("maps state to the palette: white engine, violet agent, rose fail/diff, teal pass", () => {
    expect(tintOf(find((e) => e.kind === "sandbox.ready"))).toBe("engine");
    expect(tintOf(find((e) => e.kind === "agent.state" && e.status === "progress"))).toBe("agent");
    expect(tintOf(find((e) => e.kind === "test.finished" && e.payload.outcome === "passed"))).toBe(
      "pass",
    );
    expect(tintOf(find((e) => e.kind === "test.finished" && e.payload.outcome === "failed"))).toBe(
      "fail",
    );
    expect(tintOf(find((e) => e.kind === "diff.behaviour"))).toBe("diff");
  });

  it("puts failures before differences, and differences before agents", () => {
    expect(tintOf(find((e) => e.kind === "diff.outcome" && e.status === "fail"))).toBe("fail");
    expect(tintOf(find((e) => e.kind === "verdict.issued" && e.status === "fail"))).toBe("fail");
    expect(tintOf(find((e) => e.kind === "verdict.issued" && e.status === "ok"))).toBe("agent");
  });

  it("uses exactly the DESIGN.md colours", () => {
    const hex = (rgb: readonly number[]) =>
      `#${rgb
        .map((c) =>
          Math.round(c * 255)
            .toString(16)
            .padStart(2, "0"),
        )
        .join("")}`;
    expect(Object.fromEntries(Object.entries(TINTS).map(([k, v]) => [k, hex(v)]))).toEqual({
      engine: "#ffffff",
      agent: "#7d7390",
      diff: "#b48f9c",
      fail: "#6e4e5a",
      pass: "#8fb4a8",
    });
  });
});

describe("which events stream, and how", () => {
  it("leaves graph, stage, run and feed bookkeeping out of the streams", () => {
    for (const kind of ["graph.node", "graph.edge", "stage.started", "run.finished", "log.line"]) {
      expect(streams(find((e) => e.kind === kind))).toBe(false);
    }
    for (const kind of [
      "test.finished",
      "trace.sample",
      "agent.state",
      "diff.outcome",
      "verdict.issued",
    ]) {
      expect(streams(find((e) => e.kind === kind))).toBe(true);
    }
  });

  it("keeps lifetimes within 600–1400 ms and importance within 0–1", () => {
    for (const event of events) {
      expect(importance(event)).toBeGreaterThanOrEqual(0);
      expect(importance(event)).toBeLessThanOrEqual(1);
      expect(lifetime(event)).toBeGreaterThanOrEqual(600);
      expect(lifetime(event)).toBeLessThanOrEqual(LONGEST_LIFE);
    }
  });

  it("makes slower tests, and findings, travel further than quick tests", () => {
    const quick = find((e) => e.kind === "test.finished" && e.payload.duration_ms < 60);
    const slow = find((e) => e.kind === "test.finished" && e.payload.duration_ms > 800);
    expect(travel(slow)).toBeGreaterThan(travel(quick));
    expect(travel(find((e) => e.kind === "diff.behaviour"))).toBeGreaterThan(travel(quick));
  });
});
