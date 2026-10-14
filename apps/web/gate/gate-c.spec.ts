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
import { type ChildProcess, spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, type Page, test } from "@playwright/test";
import type { CockpitSummary } from "../src/test-hook";

const REPO = process.env.REPRO_GATE_REPO ?? "";
const BASE = "93ae366874bbd4f69d90495c45b2cd336387496c";
const HEAD = "7f4dcf83a07bb3d53f4e0e65ef1b43327b4cca90";
const ROOT = fileURLToPath(new URL("../../..", import.meta.url));

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

/** The workspace's Python (`uv sync`): run directly, so stopping it stops the engine itself. */
const PYTHON = join(
  ROOT,
  ".venv",
  ...(process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"]),
);

/** Starts a `repro` command and resolves with the cockpit URL it prints. */
function startRepro(args: string[], data: string): { child: ChildProcess; url: Promise<string> } {
  const child = spawn(
    PYTHON,
    ["-m", "repro", "--data-dir", data, "--log-format", "text", ...args],
    { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] },
  );
  let output = "";
  const url = new Promise<string>((done, fail) => {
    child.stderr?.on("data", (chunk: Buffer) => {
      output += chunk.toString();
      const match = /cockpit at (http:\/\/\S+)/.exec(output);
      if (match?.[1] !== undefined) done(match[1]);
    });
    child.on("exit", (code) =>
      fail(new Error(`repro exited (${code}) before serving:\n${output}`)),
    );
  });
  return { child, url };
}

/**
 * Stops a `repro` command. POSIX: SIGINT, its Ctrl+C. Windows: the whole process tree, since a
 * virtual environment's python.exe is a launcher that runs the interpreter as a child process.
 */
function stop(child: ChildProcess): Promise<void> {
  return new Promise((done) => {
    if (child.exitCode !== null || child.pid === undefined) return done();
    child.on("exit", () => done());
    if (process.platform === "win32") {
      spawn("taskkill", ["/pid", String(child.pid), "/t", "/f"], { stdio: "ignore" });
    } else {
      child.kill("SIGINT");
    }
  });
}

async function summaryWhenFinished(page: Page): Promise<CockpitSummary> {
  await page.waitForFunction(
    () => {
      const hook = (window as unknown as { __reproTest?: { summary(): CockpitSummary } })
        .__reproTest;
      const summary = hook?.summary();
      return summary?.finished === true && summary.mode === "replay";
    },
    undefined,
    { timeout: 60_000 },
  );
  return page.evaluate(() =>
    (window as unknown as { __reproTest: { summary(): CockpitSummary } }).__reproTest.summary(),
  );
}

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
    // Live: the run streams into the cockpit from the process that runs it.
    const live = startRepro(
      ["run", "--repo", REPO, "--base", BASE, "--head", HEAD, "--port", "8781"],
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
