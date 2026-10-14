/**
 * Gate C: "`repro run --repo <small OSS lib> --base A --head B` shows that repo's real import
 * graph and blast radius in the cockpit live, and `repro replay` reproduces the same UI state."
 *
 * The library is itsdangerous (pallets/itsdangerous, BSD-3-Clause), at its change "access sha1
 * lazily" (7f4dcf8, parent 93ae366): src/itsdangerous/signer.py and one test changed. Each
 * expected distance below was checked by hand against the import lines at 7f4dcf8.
 *
 * Environment: REPRO_GATE_REPO, a clone of the library holding both commits. Without it the
 * test is skipped locally and fails in CI.
 */
import type { ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "@playwright/test";
import { startRepro, stop, summaryWhenFinished } from "./support";

const REPO = process.env.REPRO_GATE_REPO ?? "";
const BASE = "93ae366874bbd4f69d90495c45b2cd336387496c";
const HEAD = "7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90";

const MODULES = [
  "conf", // docs/conf.py
  "itsdangerous",
  "itsdangerous._json",
  "itsdangerous.encoding",
  "itsdangerous.exc",
  "itsdangerous.serializer",
  "itsdangerous.signer",
  "itsdangerous.timed",
  "itsdangerous.url_safe",
  "test_itsdangerous",
  "test_itsdangerous.test_encoding",
  "test_itsdangerous.test_serializer",
  "test_itsdangerous.test_signer",
  "test_itsdangerous.test_timed",
  "test_itsdangerous.test_url_safe",
];
const AFFECTED = [
  // signer is imported by these, and test_serializer (changed) by test_timed and test_url_safe.
  { symbol_id: "itsdangerous.serializer:<module>#0", distance: 1 },
  { symbol_id: "itsdangerous.timed:<module>#0", distance: 1 },
  { symbol_id: "itsdangerous:<module>#0", distance: 1 },
  { symbol_id: "test_itsdangerous.test_signer:<module>#0", distance: 1 },
  { symbol_id: "test_itsdangerous.test_timed:<module>#0", distance: 1 },
  { symbol_id: "test_itsdangerous.test_url_safe:<module>#0", distance: 1 },
  // url_safe reaches signer only through serializer and timed.
  { symbol_id: "itsdangerous.url_safe:<module>#0", distance: 2 },
];

test("repro run shows the real graph and blast radius live, and repro replay reproduces it", async ({
  page,
}, testInfo) => {
  test.skip(REPO === "" && !process.env.CI, "REPRO_GATE_REPO is not set");
  expect(REPO, "REPRO_GATE_REPO must name a clone of pallets/itsdangerous").not.toBe("");
  const data = mkdtempSync(join(tmpdir(), "repro-gate-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    // Live: the run streams into the cockpit from the process that runs it. Gate C is the build
    // stage, so --analyse-only: none of the target's code runs (the run stage is Gate D's).
    const live = startRepro(
      ["run", "--repo", REPO, "--base", BASE, "--head", HEAD, "--analyse-only", "--port", "8781"],
      data,
    );
    started.push(live.child);
    const liveUrl = await live.url;
    await page.goto(`${liveUrl}&test`);
    const shown = await summaryWhenFinished(page);
    expect(shown.runId).toMatch(/^run_[0-9A-Z]{26}$/);
    expect(shown.kinds["snapshot.ready"]).toBe(2);
    expect(shown.modules).toEqual(MODULES); // the real import graph: every module
    expect(shown.kinds["graph.node"]).toBe(MODULES.length + 4); // and the 4 changed definitions
    expect(shown.kinds["graph.edge"]).toBe(36);
    expect(shown.kinds["symbol.changed"]).toBe(5);
    expect(shown.counters.files).toBe(MODULES.length);
    expect(shown.blast).toEqual({
      changed: [
        "itsdangerous.signer:_lazy_sha1#0",
        "itsdangerous.signer:HMACAlgorithm#0",
        "itsdangerous.signer:Signer#0",
        "test_itsdangerous.test_serializer:<module>#0",
        "test_itsdangerous.test_serializer:TestSerializer.test_iter_unsigners#0",
      ],
      affected: AFFECTED,
      module_level_changes: ["test_itsdangerous.test_serializer"],
    });
    const drawn = await page.evaluate(async (end) => {
      const hook = (
        window as unknown as {
          __reproTest: { renderAt(t: number): Promise<{ litPixels: number }> };
        }
      ).__reproTest;
      return hook.renderAt(end);
    }, shown.end);
    expect(drawn.litPixels).toBeGreaterThan(0); // the stage drew the graph
    await testInfo.attach("live.png", { body: await page.screenshot(), contentType: "image/png" });
    await stop(live.child);

    // Replay: a new process, no live bus; the stored run from the start.
    const replay = startRepro(["replay", shown.runId as string, "--port", "8782"], data);
    started.push(replay.child);
    const replayUrl = await replay.url;
    expect(replayUrl).toContain("&replay");
    await page.goto(`${replayUrl}&test`);
    const replayed = await summaryWhenFinished(page);
    await testInfo.attach("replay.png", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    await stop(replay.child);
    expect(replayed).toEqual(shown); // same events, same order, same state
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop)); // the store is in use until they exit
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});
