// Repro's test -> function map for Jest (K06; ADR-0017, phase 2).
//
// Repro copies this file into the snapshot and passes it after the project's own
// setupFilesAfterEnv (read with --showConfig). It works as the Vitest one does
// (repro_map_vitest.mjs): V8's precise coverage through the inspector, taken before and after
// each test; what the first take holds is what importing the test file ran. It writes one JSON
// object a line to REPRO_JS_MAP, functions as [path relative to the project, name], and never
// fails a test.
const { appendFileSync } = require("node:fs");
const inspector = require("node:inspector");
const { isAbsolute, relative, sep } = require("node:path");
const { fileURLToPath } = require("node:url");

const out = process.env.REPRO_JS_MAP;
const root = process.cwd();
const session = new inspector.Session();
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

function post(method, params) {
  return new Promise((resolve, reject) => {
    session.post(method, params || {}, (error, result) =>
      error ? reject(error) : resolve(result),
    );
  });
}

async function take() {
  const { result } = await post("Profiler.takePreciseCoverage");
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

// An in-thread session answers at once: coverage runs before the test file is imported.
try {
  session.connect();
  session.post("Profiler.enable");
  session.post("Profiler.startPreciseCoverage", { callCount: true, detailed: false }, (error) => {
    if (error) write({ error: `coverage did not start: ${error}` });
    else started = true;
  });
} catch (error) {
  write({ error: `coverage did not start: ${error}` });
}

beforeEach(async () => {
  if (!started) return;
  const ran = await take();
  if (loaded === null) {
    loaded = [...new Set(ran.map(([file]) => file))];
    write({ file: where(expect.getState().testPath), loaded });
  }
});

afterEach(async () => {
  if (!started) return;
  try {
    const { currentTestName, testPath } = expect.getState();
    write({ file: where(testPath), test: currentTestName, ran: await take() });
  } catch (error) {
    write({ error: `coverage was not taken: ${error}` });
  }
});
