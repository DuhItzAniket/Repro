/**
 * The fleet view's model (K02): many runs at once, one tile each, from the engine's `/fleet`.
 *
 * A tile's state is the run's: running until it ends, then its card's status. A run that ended
 * without a card is "failed". A tile pulses when its run has written events since the last
 * poll: motion maps to events (DESIGN.md "Motion"), never to time alone.
 */

export type TileState = "running" | "verified" | "flagged" | "unverifiable" | "failed";

export interface FleetRun {
  readonly id: string;
  readonly repo: string;
  readonly repo_name: string | null;
  readonly pr: { readonly title?: string; readonly number?: number } | null;
  readonly status: string;
  readonly card_status: string | null;
  readonly last_seq: number;
  readonly created_at: string;
  readonly finished_at: string | null;
}

export interface Tile {
  readonly id: string;
  readonly state: TileState;
  readonly title: string;
  readonly where: string;
  readonly events: number;
  readonly pulse: boolean;
}

const CARD: Record<string, TileState> = {
  VERIFIED: "verified",
  FLAGGED: "flagged",
  UNVERIFIABLE: "unverifiable",
};

export function tileState(run: FleetRun): TileState {
  const status = run.card_status;
  const carded = status !== null && Object.hasOwn(CARD, status) ? CARD[status] : undefined;
  if (carded !== undefined) return carded;
  return run.status === "running" ? "running" : "failed";
}

/** What the tile says: the pull request's title and number, else the run's commits. */
export function title(run: FleetRun): string {
  if (run.pr?.title) return run.pr.number ? `#${run.pr.number} ${run.pr.title}` : run.pr.title;
  return `${run.repo.split(/[\\/]/).pop() ?? run.repo}`;
}

/**
 * The tiles for `runs`, given each run's event count at the previous poll (`seen`): a run with
 * more events than before pulses. The returned map is the next poll's `seen`.
 */
export function tiles(
  runs: readonly FleetRun[],
  seen: ReadonlyMap<string, number>,
): { tiles: Tile[]; seen: Map<string, number> } {
  const next = new Map<string, number>();
  const made = runs.map((run) => {
    next.set(run.id, run.last_seq);
    const before = seen.get(run.id);
    return {
      id: run.id,
      state: tileState(run),
      title: title(run),
      where: run.repo_name ?? run.repo,
      events: run.last_seq,
      pulse: before !== undefined && run.last_seq > before,
    };
  });
  return { tiles: made, seen: next };
}

/** How many tiles are in each state, in the order the header shows them. */
export function counts(made: readonly Tile[]): [TileState, number][] {
  const order: TileState[] = ["running", "flagged", "unverifiable", "verified", "failed"];
  return order.map((state) => [state, made.filter((tile) => tile.state === state).length]);
}

/** A response from `/fleet`, checked: what is not a run is dropped. */
export function readFleet(data: unknown): FleetRun[] {
  if (!Array.isArray(data)) return [];
  return data.filter(
    (run): run is FleetRun =>
      typeof run === "object" &&
      run !== null &&
      typeof (run as FleetRun).id === "string" &&
      typeof (run as FleetRun).status === "string" &&
      typeof (run as FleetRun).last_seq === "number",
  );
}
