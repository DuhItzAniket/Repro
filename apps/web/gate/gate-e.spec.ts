/**
 * Gate E: "a change that alters a function's output without failing any test is detected,
 * shown as a stable behaviour diff with a reproducer, and is not confused with noise in the A/A′
 * control."
 *
 * Two of Repro's fixtures (engine/tests/fixtures), built with `python -m fixtures` and run
 * through `repro run` in full: `silent-change` makes to_celsius() round to whole degrees, which
 * no test checks; `noisy` rewrites functions whose results carry the time, a random draw and a
 * set's order, without changing what they do. The cockpit is read through its test hook: the
 * behaviour field and Signals from their own views, fed by the run's `trace.sample` events, and
 * the `diff.behaviour` checks the engine sent.
 */
import type { ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import type { CockpitSummary } from "../src/test-hook";
import { buildFixture, startRepro, stop, summaryWhenFinished } from "./support";

/** A full run: provisioning, and on a machine with Docker, Repro's sandbox image on first use. */
const RUN_MS = 900_000;

async function reproduce(
  page: Page,
  name: string,
  head: string,
  data: string,
  started: ChildProcess[],
  port: number,
): Promise<CockpitSummary> {
  const repo = buildFixture(name, join(data, name));
  const headSha = repo.heads[head];
  if (headSha === undefined) throw new Error(`${name} has no branch ${head}`);
  const live = startRepro(
    ["run", "--repo", repo.path, "--base", repo.base, "--head", headSha, "--port", String(port)],
    join(data, `${name}-data`),
  );
  started.push(live.child);
  await page.goto(`${await live.url}&test`);
  const summary = await summaryWhenFinished(page, RUN_MS);
  await stop(live.child);
  return summary;
}

test.describe.configure({ mode: "serial" });

test("an output change no test checks is a stable behaviour diff with its reproducer", async ({
  page,
}, testInfo) => {
  test.setTimeout(RUN_MS * 2);
  const data = mkdtempSync(join(tmpdir(), "repro-gate-e-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const summary = await reproduce(
      page,
      "silent-change",
      "change/tidy-convert",
      data,
      started,
      8785,
    );
    await testInfo.attach("silent-change.png", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    const symbol = "units.convert:to_celsius#0";
    const describe = "tests/test_convert.py::test_describe_mentions_celsius";
    const freezing = "tests/test_convert.py::test_freezing";
    // No test fails, on any side.
    const { execution } = summary.panels;
    expect(execution.base.failed).toEqual([]);
    expect(execution.base_repeat.failed).toEqual([]);
    expect(execution.head.failed).toEqual([]);
    // Detected: one stable behaviour diff per test, with what each side gave.
    const diffs = [...summary.behaviourDiffs].sort((a, b) => a.test.localeCompare(b.test));
    expect(diffs).toEqual([
      {
        symbol,
        test: describe,
        change: "result_changed",
        stability: "stable",
        base: "37.8",
        head: "38",
      },
      {
        symbol,
        test: freezing,
        change: "result_changed",
        stability: "stable",
        base: "0.0",
        head: "0",
      },
    ]);
    // Shown: the behaviour field's cells for to_celsius differ, lit by the run's samples.
    expect(summary.kinds["trace.sample"] ?? 0).toBeGreaterThan(0);
    const cells = summary.panels.behaviour.filter((cell) => cell.symbol === symbol);
    expect(cells.map((cell) => [cell.test, cell.status]).sort()).toEqual([
      [describe, "differs"],
      [freezing, "differs"],
    ]);
    const drift = summary.panels.signals.find((series) => series.label === "DRIFT");
    expect(drift?.points ?? 0).toBeGreaterThan(0);
    expect(drift?.latest).toBe("1.00"); // every comparable base/head pair of samples differs
    // Without review, an unexplained difference ends flagged (ADR-0015); the outcomes passed.
    const { results } = summary.panels.index;
    expect(results.filter((r) => r === "flagged").length).toBe(2);
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop));
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("noise in the A/A′ control is unstable, never a behaviour diff", async ({
  page,
}, testInfo) => {
  test.setTimeout(RUN_MS * 2);
  const data = mkdtempSync(join(tmpdir(), "repro-gate-e-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const summary = await reproduce(page, "noisy", "change/tidy", data, started, 8786);
    await testInfo.attach("noisy.png", { body: await page.screenshot(), contentType: "image/png" });
    expect(summary.panels.execution.head.failed).toEqual([]);
    // Not confused with noise: no behaviour diff at all.
    expect(summary.behaviourDiffs).toEqual([]);
    const status = (name: string) =>
      summary.panels.behaviour.find((cell) => cell.symbol === `noise.values:${name}#0`)?.status;
    // The time, a random draw and a set's order differ between A and A′: unstable.
    expect(status("stamp")).toBe("unstable");
    expect(status("roll")).toBe("unstable");
    expect(status("fruit")).toBe("unstable");
    // The function without noise is the same on every side.
    expect(status("total")).toBe("same");
    expect(summary.panels.behaviour.some((cell) => cell.status === "differs")).toBe(false);
    // Signals' drift leaves the unstable pairs out: what it compares is the same.
    const drift = summary.panels.signals.find((series) => series.label === "DRIFT");
    expect(drift?.latest).toBe("0.00");
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop));
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});
