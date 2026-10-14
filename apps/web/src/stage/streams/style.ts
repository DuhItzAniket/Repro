/**
 * How each event looks outside the wheel (DESIGN.md "Lines outside the wheel"): whether it
 * streams at all, its tint and how far it travels. Pure functions of the event, so the same
 * event always looks the same way.
 */
import type { ReproEvent } from "@repro/events";

export type Rgb = readonly [number, number, number];

/** DESIGN.md palette (0–1). */
export const TINTS = {
  engine: [1, 1, 1] as Rgb, // --hot / white
  agent: [0x7d / 255, 0x73 / 255, 0x90 / 255] as Rgb, // --violet
  diff: [0xb4 / 255, 0x8f / 255, 0x9c / 255] as Rgb, // --flag
  fail: [0x6e / 255, 0x4e / 255, 0x5a / 255] as Rgb, // --flag-deep
  pass: [0x8f / 255, 0xb4 / 255, 0xa8 / 255] as Rgb, // --ok
} as const;

export type TintName = keyof typeof TINTS;

/**
 * Tint by state, in priority order (DESIGN.md: white = engine, --violet = agent,
 * --flag-deep/--flag = fail/diff, --ok = pass):
 * failures, then differences, then passing tests, then agent activity, then the engine.
 */
export function tintOf(event: ReproEvent): TintName {
  if (event.status === "fail") return "fail";
  if (event.kind.startsWith("diff.")) return "diff";
  if (event.kind === "test.finished" && event.payload.outcome === "passed") return "pass";
  if (event.agent !== null) return "agent";
  return "engine";
}

/**
 * Streams are pipeline activity: tests, traces, agents, differences, checks and verdicts.
 * The dependency graph has its own layer, and stage and run bookkeeping does not stream.
 */
export function streams(event: ReproEvent): boolean {
  switch (event.kind) {
    case "graph.node":
    case "graph.edge":
    case "stage.started":
    case "stage.finished":
    case "run.started":
    case "run.finished":
    case "log.line":
      return false;
    default:
      return true;
  }
}

/** Importance from 0 (routine) to 1 (a finding): drives length, life and width. */
export function importance(event: ReproEvent): number {
  if (event.kind.startsWith("diff.") || event.kind === "invariant.result") {
    return event.status === "ok" ? 0.6 : 1;
  }
  if (
    event.kind === "verdict.issued" ||
    event.kind === "verdict.rejected" ||
    event.kind === "card.published"
  ) {
    return 1;
  }
  if (event.kind === "missing.recorded") return 0.8;
  if (event.status === "fail") return 0.8;
  if (event.kind === "test.finished") return 0.35;
  if (event.kind === "trace.sample" || event.kind === "test.started") return 0.15;
  return 0.4;
}

/** Travel distance in px: longer for slower tests and for findings (DESIGN: length ∝ duration/importance). */
export function travel(event: ReproEvent): number {
  const base = 90 + 360 * importance(event);
  if (event.kind === "test.finished") {
    return Math.min(620, base + 22 * Math.log2(1 + event.payload.duration_ms));
  }
  return base;
}
