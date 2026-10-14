/**
 * What the gate specs share: the workspace's Python, starting and stopping `repro`, and waiting
 * for the cockpit to hold a finished run.
 */
import { type ChildProcess, spawn, spawnSync } from "node:child_process";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import type { Page } from "@playwright/test";
import type { CockpitSummary } from "../src/test-hook";

export const ROOT = fileURLToPath(new URL("../../..", import.meta.url));

/** The workspace's Python (`uv sync`): run directly, so stopping it stops the engine itself. */
export const PYTHON = join(
  ROOT,
  ".venv",
  ...(process.platform === "win32" ? ["Scripts", "python.exe"] : ["bin", "python"]),
);

/** Starts a `repro` command and resolves with the cockpit URL it prints. */
export function startRepro(
  args: string[],
  data: string,
): { child: ChildProcess; url: Promise<string> } {
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
export function stop(child: ChildProcess): Promise<void> {
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

/**
 * Waits until the cockpit at `page` holds a finished run, its clock settled at the end (a live
 * run's clock settles into replay mode there too), and returns its summary.
 */
export async function summaryWhenFinished(page: Page, timeout = 60_000): Promise<CockpitSummary> {
  await page.waitForFunction(
    () => {
      const hook = (window as unknown as { __reproTest?: { summary(): CockpitSummary } })
        .__reproTest;
      const summary = hook?.summary();
      return summary?.finished === true && summary.mode === "replay";
    },
    undefined,
    { timeout },
  );
  return page.evaluate(() =>
    (window as unknown as { __reproTest: { summary(): CockpitSummary } }).__reproTest.summary(),
  );
}

export interface FixtureRepo {
  readonly path: string;
  readonly base: string;
  readonly heads: Readonly<Record<string, string>>;
}

/** Builds one of Repro's fixture repositories (engine/tests/fixtures) at `dest`. */
export function buildFixture(name: string, dest: string): FixtureRepo {
  const done = spawnSync(PYTHON, ["-m", "fixtures", name, dest], {
    cwd: join(ROOT, "engine", "tests"),
    encoding: "utf8",
  });
  if (done.status !== 0) throw new Error(`building ${name} failed:\n${done.stderr}`);
  return JSON.parse(done.stdout) as FixtureRepo;
}
