/**
 * Where the cockpit's events come from, chosen by the page's query (C08):
 *
 * - `?run=<run id>`: the engine's event stream, following the run live;
 * - `?run=<run id>&replay`: the same stream, replayed from the start;
 * - `?log=demo` or `?log=stress`: a committed fixture; `?log=/<path>`: an event log served by
 *   this origin (`repro replay file.jsonl` serves one at `/replay.jsonl`);
 * - nothing: the engine's newest run if this page is served by the engine, else the demo
 *   fixture (the dev server). Test mode (`?test`) never asks the engine: screenshots stay fixed.
 */
import { type FixtureName, fixtureFromQuery } from "./load";

export type Source =
  | { readonly kind: "fixture"; readonly name: FixtureName }
  | { readonly kind: "log"; readonly url: string }
  | { readonly kind: "run"; readonly runId: string; readonly replay: boolean }
  | { readonly kind: "latest" };

/** The engine's run IDs: `run_` and a ULID (Crockford base 32). */
export const RUN_ID = /^run_[0-9A-HJKMNP-TV-Z]{26}$/;

export function sourceFromQuery(search: string): Source {
  const params = new URLSearchParams(search);
  const run = params.get("run");
  if (run !== null && RUN_ID.test(run))
    return { kind: "run", runId: run, replay: params.has("replay") };
  const log = params.get("log");
  // Same-origin paths only: a link cannot make the cockpit fetch from elsewhere.
  if (log?.startsWith("/") && !log.startsWith("//")) return { kind: "log", url: log };
  if (log !== null || params.has("test"))
    return { kind: "fixture", name: fixtureFromQuery(search) };
  return { kind: "latest" };
}

/** The newest run the engine serving this page has, or null (no engine, no runs). */
export async function latestRun(fetcher: typeof fetch = fetch): Promise<string | null> {
  try {
    const response = await fetcher("/runs?limit=1", { headers: { Accept: "application/json" } });
    if (!response.ok) return null;
    const runs: unknown = await response.json();
    const first = Array.isArray(runs) ? (runs[0] as { id?: unknown } | undefined) : undefined;
    return typeof first?.id === "string" && RUN_ID.test(first.id) ? first.id : null;
  } catch {
    return null; // not JSON (a dev server's index page) or no server
  }
}

/** The event stream's URL on this page's origin, from `seq` `from` on. */
export function streamUrl(
  location: Pick<Location, "protocol" | "host">,
  runId: string,
  from: number,
): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/runs/${runId}/events?from=${from}`;
}
