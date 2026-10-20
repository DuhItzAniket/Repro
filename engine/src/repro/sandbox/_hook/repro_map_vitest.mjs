// Repro's test -> function map for Vitest (K06; ADR-0017, phase 2).
//
// Repro copies this file into the snapshot and appends it to the project's own setup files (a
// wrapper config, `repro.vitest.config.mts`). It starts V8's precise coverage in the test's
// isolate through the inspector, then for each test takes it twice: before (resetting the
// counters) and after. The functions with a count above zero are what the test ran. What the
// first take holds, before the file's first test, is what importing the test file ran: its
// source files' top-level code.
//
// It writes one JSON object a line to REPRO_JS_MAP: {"file", "loaded"} once per test file, and
// {"file", "test", "ran"} per test, each function as [path relative to the project, name]. Files
// under node_modules and outside the project are left out. It reads only coverage, never the
// project's values, and a failure is written as {"error"} without failing a test.
import { appendFileSync } from "node:fs";
import { Session } from "node:inspector/promises";
import { isAbsolute, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach } from "vitest";

const out = process.env.REPRO_JS_MAP;
const root = process.cwd();
const session = new Session();
let started = false;
let loaded = null;

function write(record) {
  if (out) appendFileSync(out, `${JSON.stringify(record)}\n`);
}

function where(url) {
  let path = url;
  if (url.startsWith("file:")) path = fileURLToPath(url);
  if (!isAbsolute(path)) return null;
  const inside = relative(root, path);
  if (!inside || inside.startsWith("..") || isAbsolute(inside)) return null;
  if (inside.split(sep).includes("node_modules")) return null;
  return inside.split(sep).join("/");
}

async function take() {
  const { result } = await session.post("Profiler.takePreciseCoverage");
  const seen = new Map();
  for (const script of result) {
    const file = where(script.url);
    if (file === null) continue;
    for (const fn of script.functions) {
      if ((fn.ranges[0]?.count ?? 0) > 0)
        seen.set(`${file}\0${fn.functionName}`, [file, fn.functionName]);
    }
  }
  return [...seen.values()];
}

function fullName(task) {
  const names = [task.name];
  for (let suite = task.suite; suite && suite !== task.file; suite = suite.suite) {
    names.unshift(suite.name);
  }
  return names.join(" ");
}

try {
  session.connect();
  await session.post("Profiler.enable");
  await session.post("Profiler.startPreciseCoverage", { callCount: true, detailed: false });
  started = true;
} catch (error) {
  write({ error: `coverage did not start: ${error}` });
}

beforeEach(async (context) => {
  if (!started) return;
  const ran = await take();
  if (loaded === null) {
    loaded = ran.map(([file]) => file);
    write({ file: where(context.task.file.filepath), loaded: [...new Set(loaded)] });
  }
});

afterEach(async (context) => {
  if (!started) return;
  try {
    const ran = await take();
    write({ file: where(context.task.file.filepath), test: fullName(context.task), ran });
  } catch (error) {
    write({ error: `coverage was not taken: ${error}` });
  }
});
