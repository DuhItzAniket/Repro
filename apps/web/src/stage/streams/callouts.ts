/**
 * Callouts (DESIGN.md "Tooltips / callouts"): small bordered boxes with a label and one value,
 * anchored beyond the ring on a notable event's lane, at most two at once, each shown for
 * 2.5 s. Pure selection: the callouts at `t` depend only on the events before `t`.
 */

import type { ReproEvent } from "@repro/events";
import { hash32 } from "@repro/synth";
import type { CockpitModel } from "../../model/cockpit";
import { type Motion, NORMAL_MOTION } from "../../motion/motion";
import type { Ring } from "../../shell/layout";
import { outerRadius } from "../geometry";
import { targetFile } from "../ring/content";
import { type TintName, tintOf } from "./style";

/** Callouts sit on fixed lanes across ±24° of the ring's right side, one lane per file. */
export const LANE_SPREAD = (24 * Math.PI) / 180;
const UNIT = 4294967296;

/** Lane angle for an event: its file's lane plus a small per-event jitter. */
export function laneAngle(event: ReproEvent): number {
  const file = targetFile(event.target);
  const lane = hash32(file ?? event.kind) / UNIT; // 0–1
  const jitter = (hash32(event.id) / UNIT - 0.5) * 0.17;
  return (lane * 2 - 1) * LANE_SPREAD + jitter;
}

export const CALLOUT_MS = 2500;
export const MAX_CALLOUTS = 2;
const MIN_GAP_PX = 26;

export interface Callout {
  /** The event's id (stable across frames). */
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly tint: TintName;
  /** Anchor in stage pixels. */
  readonly x: number;
  readonly y: number;
}

const words = (text: string) => text.replaceAll("_", " ");
const symbolName = (id: string) =>
  id
    .slice(id.indexOf(":") + 1, id.lastIndexOf("#"))
    .split(".")
    .at(-1) ?? id;
const testName = (id: string) => id.slice(id.indexOf("::") + 2) || id;

/** Whether an event gets a callout (the same test as `calloutText`, without allocating). */
export function notable(event: ReproEvent): boolean {
  switch (event.kind) {
    case "verdict.issued":
    case "verdict.rejected":
    case "diff.behaviour":
    case "diff.tests":
    case "diff.deps":
    case "missing.recorded":
    case "card.published":
      return true;
    case "diff.outcome":
      return event.payload.class === "P2F" || event.payload.class === "F2P";
    case "diff.perf":
      return event.payload.verdict !== "not_assessable";
    case "invariant.result":
      return event.payload.result === "fail";
    default:
      return false;
  }
}

/** Label and value for an event worth a callout, or null. */
export function calloutText(event: ReproEvent): { label: string; value: string } | null {
  switch (event.kind) {
    case "verdict.issued": {
      const v = event.payload.verdict;
      return { label: `${v.claim_id} ${v.verdict}`, value: `${v.cited_evidence.length} evidence` };
    }
    case "verdict.rejected":
      return { label: `${event.payload.claim_id} rejected`, value: words(event.payload.reason) };
    case "diff.behaviour":
      return { label: "behaviour", value: symbolName(event.payload.symbol_id) };
    case "diff.outcome":
      return event.payload.class === "P2F" || event.payload.class === "F2P"
        ? { label: event.payload.class, value: testName(event.target?.test ?? "") }
        : null;
    case "diff.tests":
      return { label: "test change", value: words(event.payload.change) };
    case "diff.deps":
      return { label: "dependency", value: `${event.payload.package} ${event.payload.change}` };
    case "diff.perf":
      return event.payload.verdict === "not_assessable"
        ? null
        : { label: "perf", value: `×${event.payload.ratio.toFixed(2)}` };
    case "invariant.result":
      return event.payload.result === "fail"
        ? { label: words(event.payload.invariant), value: "fail" }
        : null;
    case "missing.recorded":
      return { label: "missing", value: words(event.payload.missing.reason) };
    case "card.published":
      return { label: "card", value: event.payload.status };
    default:
      return null;
  }
}

/**
 * The callouts visible at `t`, newest first (at most two). A callout shows for CALLOUT_MS of
 * wall-clock time (ADR-0011), so at ×16 it covers 16 times as much run time.
 */
export function selectCallouts(
  model: CockpitModel,
  t: number,
  ring: Ring,
  motion: Motion = NORMAL_MOTION,
): Callout[] {
  const { store } = model;
  const out: Callout[] = [];
  const end = store.cursorAt(t);
  const start = store.firstAtOrAfter(t - CALLOUT_MS * motion.speed);
  for (let i = end - 1; i >= start && out.length < MAX_CALLOUTS; i--) {
    const event = store.event(i);
    if (event === null) continue;
    const text = calloutText(event);
    if (text === null) continue;
    const angle = laneAngle(event);
    const radius = outerRadius(ring) + 54;
    let y = ring.cy + Math.sin(angle) * radius;
    const previous = out[0];
    if (previous !== undefined && Math.abs(previous.y - y) < MIN_GAP_PX) {
      y = previous.y + (y >= previous.y ? MIN_GAP_PX : -MIN_GAP_PX);
    }
    out.push({
      key: event.id,
      ...text,
      tint: tintOf(event),
      x: ring.cx + Math.cos(angle) * radius,
      y,
    });
  }
  return out;
}

/** Recomputes callouts each frame but reports a new list only when the visible set changes. */
export class CalloutTracker {
  private first = -1;
  private second = -1;
  private cx = Number.NaN;
  private cy = Number.NaN;
  private r = Number.NaN;

  /** The new callouts, or null when nothing changed (no allocation in that case). */
  update(
    model: CockpitModel,
    t: number,
    ring: Ring,
    motion: Motion = NORMAL_MOTION,
  ): Callout[] | null {
    const { store } = model;
    let first = -1;
    let second = -1;
    const end = store.cursorAt(t);
    const start = store.firstAtOrAfter(t - CALLOUT_MS * motion.speed);
    for (let i = end - 1; i >= start && second < 0; i--) {
      const event = store.event(i);
      if (event === null || !notable(event)) continue;
      if (first < 0) first = i;
      else second = i;
    }
    const same = first === this.first && second === this.second;
    if (same && ring.cx === this.cx && ring.cy === this.cy && ring.r === this.r) return null;
    this.first = first;
    this.second = second;
    this.cx = ring.cx;
    this.cy = ring.cy;
    this.r = ring.r;
    return selectCallouts(model, t, ring, motion);
  }
}
