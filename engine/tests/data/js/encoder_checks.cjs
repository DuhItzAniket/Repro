// The JS tracer runtime's guarantees (K07), run by test_jstrace.py: node encoder_checks.cjs <runtime> <out dir>.
const assert = require("node:assert/strict");
const { readFileSync, rmSync } = require("node:fs");
const path = require("node:path");

const out = path.join(process.argv[3], "trace.jsonl");
rmSync(out, { force: true });
process.env.REPRO_JS_TRACE_OUT = out;
const rt = require(process.argv[2]);

const same = (a, b) => rt.digests(a).digest === rt.digests(b).digest;
assert.ok(same({ a: 1, b: [2, 3] }, { a: 1, b: [2, 3] }), "the same value, the same digest");
assert.ok(!same(0, -0), "-0 is not 0");
assert.ok(!same(1, "1"), "a number is not its string");
assert.ok(!same({ a: 1, b: 2 }, { b: 2, a: 1 }), "order is kept");
assert.equal(
  rt.digests({ a: 1, b: 2 }).anyOrder ?? rt.digests({ a: 1, b: 2 }).digest,
  rt.digests({ b: 2, a: 1 }).anyOrder,
  "but the sorted digest ignores it",
);
const cyclic = { name: "a" };
cyclic.self = cyclic;
assert.equal(rt.digests(cyclic).complete, false, "a cycle is incomplete");
let called = false;
const getter = {
  get x() {
    called = true;
    return 1;
  },
};
rt.digests(getter);
rt.preview(getter);
assert.equal(called, false, "a getter is never called");
let trapped = false;
const proxy = new Proxy(
  {},
  {
    ownKeys() {
      trapped = true;
      return [];
    },
    get() {
      trapped = true;
    },
  },
);
rt.digests(proxy);
rt.preview(proxy);
assert.equal(trapped, false, "a proxy's traps never run");
assert.ok(!same(new Map([["a", 1]]), new Map([["a", 2]])), "maps by their entries");
assert.ok(!same(new Uint8Array([1, 2]), new Uint8Array([1, 3])), "typed arrays by their bytes");
const view = new Uint8Array(new Uint8Array([9, 1, 2]).buffer, 1, 2);
assert.ok(same(view, new Uint8Array([1, 2])), "a view by its own bytes");

class Box {
  constructor(v) {
    this.v = v;
  }
}
const Wrapped = rt.wrap("src/m.js", "Box", Box);
assert.ok(new Wrapped(1) instanceof Box, "construction passes through");
const add = rt.wrap("src/m.js", "add", (a, b) => a + b);
const fail = rt.wrap("src/m.js", "fail", () => {
  throw new TypeError("bad");
});
const later = rt.wrap("src/m.js", "later", async (x) => x * 2);
rt.setTest("test/m.test.js::m adds");
assert.equal(add(1, 2), 3);
assert.throws(() => fail(), TypeError);
(async () => {
  assert.equal(await later(4), 8);
  rt.flush();
  const records = readFileSync(out, "utf8")
    .trim()
    .split("\n")
    .map((l) => JSON.parse(l));
  assert.deepEqual(
    records.map((r) => [r.target[1], r.outcome, r.type]),
    [
      ["add", "return", "number"],
      ["fail", "raise", "TypeError"],
      ["later", "return", "number"],
    ],
  );
  assert.ok(
    records.every((r) => /^[0-9a-f]{32}$/.test(r.args) && r.nodeid === "test/m.test.js::m adds"),
  );
  console.log(`encoder and wrapper: all checks passed (${records.length} records)`);
})();
