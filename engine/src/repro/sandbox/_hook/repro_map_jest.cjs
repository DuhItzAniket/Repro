// Repro's test -> function map for Jest (K06; ADR-0017, phase 2).
//
// Repro copies this file into the snapshot and passes it after the project's own
// setupFilesAfterEnv (read with --showConfig). It works as the Vitest one does
// (repro_map_vitest.mjs): V8's precise coverage through the inspector, taken before and after
// each test; what the first take holds is what importing the test file ran. It writes one JSON
// object a line to REPRO_JS_MAP, functions as [path relative to the project, name], and never
// fails a test.
//
// With REPRO_JS_TRACE_OUT (K07), it also traces the functions REPRO_JS_TRACE_PLAN names: each
// planned module is mocked by its own exports, the named ones wrapped by the tracer runtime
// (repro_trace_js.cjs), class methods in place. Jest runs modules in its own registry, so the
// calls traced are the ones through a module's exports: a call from inside the module is not.
const { appendFileSync } = require("node:fs");
const inspector = require("node:inspector");
const { isAbsolute, relative, resolve, sep } = require("node:path");
const { fileURLToPath } = require("node:url");

const out = process.env.REPRO_JS_MAP;
const root = process.cwd();
const session = new inspector.Session();
let started = false;
let loaded = null;
let mockTracer = null;

function write(record) {
  if (out) appendFileSync(out, `${JSON.stringify(record)}\n`);
}

// A module's exports with the planned functions wrapped (names "x" or V8's "get x" for
// accessors); a module that is a function itself is wrapped as one.
function mockTraced(actual, file, wanted) {
  const wrap = (name, fn) => mockTracer.wrap(file, name, fn);
  const methods = (cls) => {
    for (const holder of [cls, cls.prototype]) {
      if (!holder) continue;
      for (const key of Object.getOwnPropertyNames(holder)) {
        const descriptor = Object.getOwnPropertyDescriptor(holder, key);
        for (const slot of ["value", "get", "set"]) {
          const name = slot === "value" ? key : `${slot} ${key}`;
          if (key !== "constructor" && wanted.has(name) && typeof descriptor[slot] === "function") {
            mockTracer.method(holder, key, slot, file, name);
          }
        }
      }
    }
  };
  if (typeof actual === "function") {
    methods(actual);
    return wanted.has(actual.name) ? Object.assign(wrap(actual.name, actual), actual) : actual;
  }
  if (actual === null || typeof actual !== "object") return actual;
  const result = { ...actual };
  if (actual.__esModule) Object.defineProperty(result, "__esModule", { value: true });
  for (const [key, value] of Object.entries(result)) {
    if (typeof value !== "function") continue;
    methods(value);
    if (wanted.has(key) || wanted.has(value.name))
      result[key] = wrap(wanted.has(key) ? key : value.name, value);
  }
  return result;
}

if (process.env.REPRO_JS_TRACE_OUT) {
  try {
    mockTracer = require("./repro_trace_js.cjs");
    const plan = JSON.parse(process.env.REPRO_JS_TRACE_PLAN || "{}");
    for (const [mockFile, names] of Object.entries(plan)) {
      const mockAbsolute = resolve(root, mockFile);
      const mockWanted = new Set(names);
      jest.mock(mockAbsolute, () =>
        mockTraced(jest.requireActual(mockAbsolute), mockFile, mockWanted),
      );
    }
  } catch (error) {
    write({ error: `the tracer did not load: ${error}` });
  }
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
  const state = expect.getState();
  mockTracer?.setTest(`${where(state.testPath)}::${state.currentTestName}`);
  if (!started) return;
  const ran = await take();
  if (loaded === null) {
    loaded = [...new Set(ran.map(([file]) => file))];
    write({ file: where(expect.getState().testPath), loaded });
  }
});

afterEach(async () => {
  mockTracer?.setTest(null);
  mockTracer?.flush();
  if (!started) return;
  try {
    const { currentTestName, testPath } = expect.getState();
    write({ file: where(testPath), test: currentTestName, ran: await take() });
  } catch (error) {
    write({ error: `coverage was not taken: ${error}` });
  }
});
