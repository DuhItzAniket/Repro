import { describe, expect, it } from "vitest";
import { counts, type FleetRun, readFleet, tileState, tiles, title } from "./model";

function run(overrides: Partial<FleetRun> = {}): FleetRun {
  return {
    id: "run_01M55PS7ZK8PZ3707PSN769CDF",
    repo: "C:/data/repos/github.com/pallets/flask.git",
    repo_name: "pallets/flask",
    pr: { title: "Fix the parser", number: 7 },
    status: "running",
    card_status: null,
    last_seq: 10,
    created_at: "2026-10-18T00:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

describe("the fleet's tiles", () => {
  it("take the run's state, then its card's", () => {
    expect(tileState(run())).toBe("running");
    expect(tileState(run({ status: "completed", card_status: "FLAGGED" }))).toBe("flagged");
    expect(tileState(run({ status: "completed", card_status: "VERIFIED" }))).toBe("verified");
    expect(tileState(run({ status: "failed", card_status: "UNVERIFIABLE" }))).toBe("unverifiable");
    expect(tileState(run({ status: "failed", card_status: null }))).toBe("failed");
  });

  it("name the pull request, else the repository", () => {
    expect(title(run())).toBe("#7 Fix the parser");
    expect(title(run({ pr: null }))).toBe("flask.git");
  });

  it("pulse only when the run wrote events since the last poll", () => {
    const first = tiles([run()], new Map());
    expect(first.tiles[0]?.pulse).toBe(false); // nothing to compare with yet
    const same = tiles([run()], first.seen);
    expect(same.tiles[0]?.pulse).toBe(false);
    const moved = tiles([run({ last_seq: 12 })], same.seen);
    expect(moved.tiles[0]?.pulse).toBe(true);
    expect(moved.seen.get(run().id)).toBe(12);
  });

  it("are counted by state", () => {
    const made = tiles(
      [run(), run({ id: "b", status: "completed", card_status: "FLAGGED" })],
      new Map(),
    ).tiles;
    expect(counts(made)).toEqual([
      ["running", 1],
      ["flagged", 1],
      ["unverifiable", 0],
      ["verified", 0],
      ["failed", 0],
    ]);
  });

  it("drop what is not a run", () => {
    expect(readFleet([run(), { id: 3 }, null, "x"])).toHaveLength(1);
    expect(readFleet({ detail: "no" })).toEqual([]);
  });
});
