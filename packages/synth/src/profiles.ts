import type { Profile } from "./scenario";

/**
 * The reference run the cockpit is built and visually tested against (B01): 1 PR, 4 claims,
 * 12 agents, 147 files, 28 checks, 4 flagged, about 2–4k events.
 */
export const DEMO: Profile = {
  name: "demo",
  files: 147,
  edges: 1500,
  fillerSymbols: 15,
  fillerTests: 0,
  fillerTestMs: [1, 4],
  graphNodesMs: 2600,
  graphEdgesMs: 3400,
  testOverheadMs: [35, 90],
  testGapMs: [2, 6],
  collectMs: 1100,
};

/**
 * The performance fixture (B04–B07): the same story in a large repository. 10,000 graph edges,
 * and 600 selected tests in three sandboxes give a burst of over 2,000 execution events within
 * one second.
 */
export const STRESS: Profile = {
  name: "stress",
  files: 2000,
  edges: 10_000,
  fillerSymbols: 60,
  fillerTests: 583,
  fillerTestMs: [1, 1],
  graphNodesMs: 3000,
  graphEdgesMs: 5000,
  testOverheadMs: [0, 0],
  testGapMs: [0, 0],
  collectMs: 900,
};

export const PROFILES: Readonly<Record<string, Profile>> = { demo: DEMO, stress: STRESS };

/** Seed of the committed fixtures (`apps/web/fixtures/*-run.jsonl`). */
export const FIXTURE_SEED = 1;
