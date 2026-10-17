/**
 * The guide's demo (H06, docs/guide/demo.md): one real run, recorded. Not a gate: it runs only
 * when REPRO_DEMO_OUT names where to write, and CI never sets it.
 *
 * Repro's `silent-change` fixture (engine/tests/fixtures) goes through `repro run` in full: a
 * change makes to_celsius() round to whole degrees, and no test checks it. The run is then
 * replayed with `repro replay`, and the stills are frames of the replay, at fixed fractions of
 * its time and with a focus set, so they come from the stored event log alone. The card is
 * `repro export --format md` of the same run.
 *
 *   REPRO_DEMO_OUT=docs/guide/demo pnpm --filter @repro/web exec playwright test \
 *     -c playwright.gate.config.ts demo.spec.ts
 */
import { type ChildProcess, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import type { RenderOptions, TestHook } from "../src/test-hook";
import {
  buildFixture,
  PYTHON,
  ROOT,
  startRepro,
  stop,
  summaryWhenFinished,
  testMode,
} from "./support";

const OUT = process.env.REPRO_DEMO_OUT;
/** A full run: provisioning, and on a machine with Docker, Repro's sandbox image on first use. */
const RUN_MS = 900_000;

async function still(page: Page, path: string, t: number, options: RenderOptions = {}) {
  const { litPixels } = await page.evaluate(
    ([at, opts]) => (window as unknown as { __reproTest: TestHook }).__reproTest.renderAt(at, opts),
    [t, options] as const,
  );
  expect(litPixels).toBeGreaterThan(10_000); // the stage is really drawing
  await page.screenshot({ path });
}

test("the demo: silent-change, run, replayed and exported", async ({ page }) => {
  test.skip(OUT === undefined, "REPRO_DEMO_OUT is not set");
  test.setTimeout(RUN_MS * 2);
  const out = resolve(ROOT, OUT ?? ".");
  mkdirSync(out, { recursive: true });
  const data = mkdtempSync(join(tmpdir(), "repro-demo-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const repo = buildFixture("silent-change", join(data, "silent-change"));
    const head = repo.heads["change/tidy-convert"] as string;
    const store = join(data, "store");
    const live = startRepro(
      ["run", "--repo", repo.path, "--base", repo.base, "--head", head, "--port", "8787"],
      store,
    );
    started.push(live.child);
    await page.goto(testMode(await live.url));
    const run = (await summaryWhenFinished(page, RUN_MS)).runId as string;
    await stop(live.child);

    const replay = startRepro(["replay", run, "--port", "8788"], store);
    started.push(replay.child);
    await page.goto(testMode(await replay.url));
    const summary = await summaryWhenFinished(page);
    const flagged = summary.panels.index.results.indexOf("flagged");
    expect(flagged).toBeGreaterThanOrEqual(0);
    await still(page, join(out, "running.png"), Math.round(summary.end * 0.8));
    await still(page, join(out, "finished.png"), summary.end);
    const evidence = { focus: { kind: "check", index: flagged } } as const;
    await still(page, join(out, "evidence.png"), summary.end, evidence);
    await still(page, join(out, "card.png"), summary.end, { focus: { kind: "card" } });
    await stop(replay.child);

    const exported = ["export", run, "--format", "md"];
    const card = spawnSync(PYTHON, ["-m", "repro", "--data-dir", store, ...exported], {
      cwd: ROOT,
      encoding: "utf8",
    });
    expect(card.status).toBe(0);
    writeFileSync(join(out, "card.md"), card.stdout, "utf8");
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop));
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});
