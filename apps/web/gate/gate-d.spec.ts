/**
 * Gate D: "A branch that breaks one test shows exactly that test flipping (P2F) in Execution,
 * Change routes and the index. A branch that deletes or weakens a test is flagged as test
 * tampering." (The gate's third criterion, the sandbox escape suite at the level the card
 * claims, is the engine's own test suite; the gate record cites its CI runs.)
 *
 * The repositories are Repro's fixtures (engine/tests/fixtures), built here with
 * `python -m fixtures`: `breaks-one` changes discount() so that test_discount, and only it,
 * fails; `test-tamper` breaks two tests, deletes one's assertion and skips the other. Each runs
 * through `repro run` in full: sandboxes (Docker when the machine has it), environments from the
 * package index, both sides' tests, the diff. The cockpit is read through its test hook, whose
 * panel summary is computed by the panels' own views.
 *
 * Since E04 each branch's changed functions are also compared call by call: every behaviour
 * difference is a `diff.behaviour` check, `warn` until review explains it (ADR-0015), so in a
 * run without review it ends flagged, beside the outcome and test-change checks.
 */
import type { ChildProcess } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, type Page, test } from "@playwright/test";
import type { CockpitSummary } from "../src/test-hook";
import { buildFixture, startRepro, stop, summaryWhenFinished, testMode } from "./support";

/** A full run: provisioning, and on a machine with Docker, Repro's sandbox image on first use. */
const RUN_MS = 900_000;

async function reproduce(
  page: Page,
  name: string,
  head: string,
  data: string,
  started: ChildProcess[],
  port: number,
): Promise<{ summary: CockpitSummary; base: string; head: string; repo: string }> {
  const repo = buildFixture(name, join(data, name));
  const headSha = repo.heads[head];
  if (headSha === undefined) throw new Error(`${name} has no branch ${head}`);
  const live = startRepro(
    ["run", "--repo", repo.path, "--base", repo.base, "--head", headSha, "--port", String(port)],
    join(data, `${name}-data`),
  );
  started.push(live.child);
  await page.goto(testMode(await live.url));
  const summary = await summaryWhenFinished(page, RUN_MS);
  await stop(live.child);
  return { summary, base: repo.base, head: headSha, repo: repo.path };
}

test.describe.configure({ mode: "serial" });

test("a branch that breaks one test shows exactly that test flipping", async ({
  page,
}, testInfo) => {
  test.setTimeout(RUN_MS * 2);
  const data = mkdtempSync(join(tmpdir(), "repro-gate-d-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const { summary } = await reproduce(
      page,
      "breaks-one",
      "change/discount-percent",
      data,
      started,
      8783,
    );
    await testInfo.attach("breaks-one.png", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    const flipped = "tests/test_prices.py::test_discount";
    const { execution, routes, index } = summary.panels;
    // Execution: it fails on HEAD, in every run there; on BASE (A and A′) nothing fails.
    expect(execution.head.failed).toEqual([flipped]);
    expect(execution.base.failed).toEqual([]);
    expect(execution.base_repeat.failed).toEqual([]);
    expect(execution.head.runs).toBe(4); // H and three reruns of the flip
    // Change routes: the one changed function, routed to that test, its two checks flagged:
    // the P2F, and discount() giving another result for the same input (E04).
    expect(routes).toEqual([
      {
        symbol: "shop.prices:discount#0",
        tests: 1,
        step: 3,
        checks: { passed: 0, flagged: 2, unassessed: 0, pending: 0 },
      },
    ]);
    // The index: those two checks, flagged; the header agrees.
    expect(index.results).toEqual(["flagged", "flagged"]);
    expect(index.rows.map((row) => row.status)).toContain("flagged");
    expect(summary.counters.checks).toBe(2);
    expect(summary.counters.flagged).toBe(2);
    expect(summary.kinds["diff.outcome"]).toBe(1);
    expect(summary.kinds["diff.behaviour"]).toBe(1);
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop));
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});

test("a branch that deletes or weakens a test is flagged as test tampering", async ({
  page,
}, testInfo) => {
  test.setTimeout(RUN_MS * 2);
  const data = mkdtempSync(join(tmpdir(), "repro-gate-d-"));
  const started: ChildProcess[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    const { summary } = await reproduce(
      page,
      "test-tamper",
      "perf/integer-division",
      data,
      started,
      8784,
    );
    await testInfo.attach("test-tamper.png", {
      body: await page.screenshot(),
      contentType: "image/png",
    });
    // Four test changes, each a flagged check: the deleted assertion, the added skip, and both
    // edited tests' base versions failing on head.
    expect(summary.kinds["diff.tests"]).toBe(4);
    // Four behaviour differences, unexplained without review (E04): divide() returns an int and
    // raises another ZeroDivisionError, and the edited tests make calls base made and head not.
    expect(summary.kinds["diff.behaviour"]).toBe(4);
    const { results } = summary.panels.index;
    const count = (result: string) => results.filter((r) => r === result).length;
    expect(count("flagged")).toBe(8);
    // The two edited tests' outcomes are not comparable (modified); the untouched one passes.
    expect(count("unassessed")).toBe(2);
    expect(count("passed")).toBe(1);
    expect(summary.counters.flagged).toBe(8);
    expect(summary.panels.index.rows.map((row) => row.status)).toContain("flagged");
    expect(errors).toEqual([]);
  } finally {
    await Promise.all(started.map(stop));
    rmSync(data, { recursive: true, force: true, maxRetries: 10, retryDelay: 200 });
  }
});
