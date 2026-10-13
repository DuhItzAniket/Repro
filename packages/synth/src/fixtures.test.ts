// The committed fixtures must equal what the generator produces. After an intended generator
// change, regenerate them with `pnpm fixtures` and review the diff.
import { describe, expect, it } from "vitest";
import { toJsonl } from "./jsonl";
import { DEMO, FIXTURE_SEED, STRESS } from "./profiles";
import { generateRun } from "./scenario";

const FIXTURES = "../../../apps/web/fixtures";

describe("committed fixtures are up to date", () => {
  it.each([
    ["demo-run.jsonl", DEMO],
    ["stress-run.jsonl", STRESS],
  ] as const)("%s", async (file, profile) => {
    await expect(toJsonl(generateRun(profile, FIXTURE_SEED).events)).toMatchFileSnapshot(
      `${FIXTURES}/${file}`,
    );
  });
});
