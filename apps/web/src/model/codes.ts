/**
 * Small integer codes for the EventStore's typed-array columns. A code indexes into the tables
 * below, so a column of 100k events costs bytes, not strings.
 */
import { EVENT_KINDS, type EventKind, type Stage, type Status } from "@repro/events";

export const STAGES = [
  "read",
  "build",
  "run",
  "diff",
  "check",
  "review",
  "card",
] as const satisfies readonly Stage[];
export const STATUSES = [
  "start",
  "progress",
  "ok",
  "warn",
  "fail",
] as const satisfies readonly Status[];

/** Kind code of an event the cockpit cannot interpret (unknown kind or payload version). */
export const UNKNOWN_KIND = 255;
/** Highest payload version this build understands, per kind. All kinds are at pv 1 in schema v1. */
export const SUPPORTED_PV = 1;
/** Envelope schema version this build understands (ADR-0003). */
export const SUPPORTED_ENVELOPE = 1;

const KIND_CODES = new Map<string, number>(EVENT_KINDS.map((kind, code) => [kind, code]));
const STAGE_CODES = new Map<string, number>(STAGES.map((stage, code) => [stage, code]));
const STATUS_CODES = new Map<string, number>(STATUSES.map((status, code) => [status, code]));

export function kindCode(kind: string, pv: number): number {
  const code = KIND_CODES.get(kind);
  return code === undefined || pv > SUPPORTED_PV ? UNKNOWN_KIND : code;
}

export function kindName(code: number): EventKind | null {
  return code === UNKNOWN_KIND ? null : (EVENT_KINDS[code] ?? null);
}

export function stageCode(stage: string): number {
  return STAGE_CODES.get(stage) ?? -1;
}

export function statusCode(status: string): number {
  return STATUS_CODES.get(status) ?? -1;
}
