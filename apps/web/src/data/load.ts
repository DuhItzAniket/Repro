/**
 * Loads a recorded event log for the cockpit to replay. In Stage B the only sources are the
 * committed fixtures; Stage C adds the engine's WebSocket (replay-then-live).
 */
import { parseJsonl } from "../model/jsonl";

export const FIXTURES = {
  demo: new URL("../../fixtures/demo-run.jsonl", import.meta.url).href,
  stress: new URL("../../fixtures/stress-run.jsonl", import.meta.url).href,
} as const;

export type FixtureName = keyof typeof FIXTURES;

/** `?log=stress` selects the stress fixture; anything else gives the demo run. */
export function fixtureFromQuery(search: string): FixtureName {
  return new URLSearchParams(search).get("log") === "stress" ? "stress" : "demo";
}

export interface LoadedLog {
  readonly values: unknown[];
  /** Lines that were not JSON (reported, not fatal). */
  readonly badLines: number;
}

export async function loadLog(url: string, fetcher: typeof fetch = fetch): Promise<LoadedLog> {
  const response = await fetcher(url);
  if (!response.ok) throw new Error(`could not load ${url}: HTTP ${response.status}`);
  const { values, errors } = parseJsonl(await response.text());
  return { values, badLines: errors.length };
}
