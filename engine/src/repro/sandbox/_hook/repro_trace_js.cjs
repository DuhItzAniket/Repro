// Repro's JavaScript tracer runtime (K07; ADR-0017, phase 3): the encoder and the call wrapper.
//
// The encoder is repro_encode's, ported. A value becomes tagged bytes, hashed (SHA-256, cut to
// 128 bits: only JavaScript runs are compared with each other). No user code runs: a value is
// read through property descriptors (a getter is not called, it is written as one), never
// through toString, valueOf, toJSON or a proxy's traps. Strings have the project's root, the
// temporary directory and the home directory replaced, as base and head run from different
// directories. Deeper than MAX_DEPTH, past MAX_NODES values or back at an object already on
// the path (a cycle), the encoding is incomplete: the engine never takes it as equal to
// anything. Objects and Maps also get an order-insensitive digest, entries sorted.
//
// wrap(file, name, fn) returns a function that records each call of fn: the current test, the
// arguments' digest, and how it ended (a return, or a raise), the result's digest, the type. A
// promise is recorded when it settles. Each (test, function) records its first BUDGET calls,
// then one "truncated" record. Records are the Python tracer's (repro_trace.py), one JSON
// object a line, written to REPRO_JS_TRACE_OUT when a test ends (flush).
"use strict";
const { createHash } = require("node:crypto");
const { appendFileSync } = require("node:fs");
const { tmpdir, homedir } = require("node:os");
const { types } = require("node:util");

const MAX_DEPTH = 6;
const MAX_NODES = 5000;
const BUDGET = 200;
// Each (test, function)'s first calls carry previews too: what a difference shows without a
// reproducer run (Python's E07 samples, as REPRO_TRACE_SAMPLES).
const SAMPLES = Number.parseInt(process.env.REPRO_JS_TRACE_SAMPLES || "0", 10) || 0;
const PREVIEW = 512;
const out = process.env.REPRO_JS_TRACE_OUT;
const wanted = new Set(JSON.parse(process.env.REPRO_JS_PREVIEWS || "[]").map((w) => w.join("\0")));
const replacements = [
  [process.cwd(), "<ROOT>"],
  [tmpdir(), "<TMP>"],
  [homedir(), "<HOME>"],
]
  .filter(([from]) => from && from.length > 1)
  .sort((a, b) => b[0].length - a[0].length);

function normal(text) {
  let result = text;
  for (const [from, to] of replacements) result = result.split(from).join(to);
  return result.split("\\").join("/");
}

function own(object) {
  // Own string keys with their descriptors, through Reflect and Object: no trap runs (a proxy
  // is opaque before this is reached).
  const found = [];
  for (const key of Object.getOwnPropertyNames(object)) {
    const descriptor = Object.getOwnPropertyDescriptor(object, key);
    if (descriptor?.enumerable) found.push([key, descriptor]);
  }
  return found;
}

function typeName(value) {
  if (value === null) return "null";
  if (typeof value !== "object" && typeof value !== "function") return typeof value;
  if (types.isProxy(value)) return "Proxy";
  let proto;
  try {
    proto = Object.getPrototypeOf(value);
  } catch {
    return "object";
  }
  if (proto === null) return "Object";
  const ctor = Object.getOwnPropertyDescriptor(proto, "constructor");
  const name = typeof ctor?.value === "function" ? ctor.value.name : "";
  return name || "object";
}

class Encoder {
  constructor() {
    this.nodes = 0;
    this.complete = true;
    this.path = new Set();
  }

  // Returns [ordered, sorted] encodings as strings (sorted differs only for keyed containers).
  encode(value, depth) {
    this.nodes += 1;
    if (this.nodes > MAX_NODES || depth > MAX_DEPTH) {
      this.complete = false;
      return ["!cut", "!cut"];
    }
    const kind = typeof value;
    if (value === null) return ["N", "N"];
    if (kind === "undefined") return ["u", "u"];
    if (kind === "boolean") return [value ? "T" : "F", value ? "T" : "F"];
    if (kind === "number") {
      const text = Object.is(value, -0) ? "-0" : String(value);
      return [`n${text}`, `n${text}`];
    }
    if (kind === "bigint") return [`b${value}`, `b${value}`];
    if (kind === "string") {
      const text = JSON.stringify(normal(value));
      return [`s${text}`, `s${text}`];
    }
    if (kind === "symbol") {
      const text = `y${JSON.stringify(value.description ?? "")}`;
      return [text, text];
    }
    if (kind === "function") {
      const text = `f${JSON.stringify(value.name || "")}`;
      return [text, text];
    }
    if (types.isProxy(value)) return ["!proxy", "!proxy"];
    if (this.path.has(value)) {
      this.complete = false;
      return ["!cycle", "!cycle"];
    }
    this.path.add(value);
    try {
      return this.container(value, depth);
    } finally {
      this.path.delete(value);
    }
  }

  container(value, depth) {
    const name = typeName(value);
    if (types.isDate(value)) {
      const time = Date.prototype.getTime.call(value);
      return [`d${time}`, `d${time}`];
    }
    if (types.isRegExp(value)) {
      const text = `r${JSON.stringify(RegExp.prototype.toString.call(value))}`;
      return [text, text];
    }
    if (types.isPromise(value) || types.isGeneratorObject(value)) return [`!${name}`, `!${name}`];
    if (value instanceof WeakMap || value instanceof WeakSet) return [`!${name}`, `!${name}`];
    if (ArrayBuffer.isView(value) || types.isAnyArrayBuffer(value)) {
      const bytes = (
        ArrayBuffer.isView(value)
          ? Buffer.from(value.buffer, value.byteOffset, value.byteLength)
          : Buffer.from(value)
      ).toString("hex");
      return [`B${name}:${bytes}`, `B${name}:${bytes}`];
    }
    if (Array.isArray(value)) {
      const ordered = [];
      const sorted = [];
      for (let i = 0; i < value.length; i += 1) {
        const descriptor = Object.getOwnPropertyDescriptor(value, i);
        const [a, b] = descriptor
          ? "value" in descriptor
            ? this.encode(descriptor.value, depth + 1)
            : ["!get", "!get"]
          : ["!hole", "!hole"];
        ordered.push(a);
        sorted.push(b);
      }
      return [`[${ordered.join(",")}]`, `[${sorted.join(",")}]`];
    }
    if (types.isMap(value) || types.isSet(value)) {
      const entries = [];
      for (const item of types.isMap(value)
        ? Map.prototype.entries.call(value)
        : Set.prototype.values.call(value)) {
        entries.push(
          types.isMap(value)
            ? [this.encode(item[0], depth + 1), this.encode(item[1], depth + 1)]
            : [this.encode(item, depth + 1), ["", ""]],
        );
      }
      const pair = (e, i) => `${e[0][i]}=${e[1][i]}`;
      const ordered = entries.map((e) => pair(e, 0));
      const sorted = entries.map((e) => pair(e, 1)).sort();
      return [`${name}{${ordered.join(",")}}`, `${name}{${sorted.join(",")}}`];
    }
    if (types.isNativeError(value) || value instanceof Error) {
      const message = Object.getOwnPropertyDescriptor(value, "message");
      const text = JSON.stringify(
        normal(String(message && "value" in message ? message.value : "")),
      );
      return [`e${name}:${text}`, `e${name}:${text}`];
    }
    const ordered = [];
    const sorted = [];
    for (const [key, descriptor] of own(value)) {
      const [a, b] =
        "value" in descriptor ? this.encode(descriptor.value, depth + 1) : ["!get", "!get"];
      ordered.push(`${JSON.stringify(key)}:${a}`);
      sorted.push(`${JSON.stringify(key)}:${b}`);
    }
    sorted.sort();
    return [`o${name}{${ordered.join(",")}}`, `o${name}{${sorted.join(",")}}`];
  }
}

function hash(text) {
  return createHash("sha256").update(text).digest("hex").slice(0, 32);
}

function digests(value) {
  const encoder = new Encoder();
  let encoded;
  try {
    encoded = encoder.encode(value, 0);
  } catch {
    return { digest: hash("!error"), anyOrder: null, complete: false };
  }
  const [ordered, sorted] = encoded;
  return {
    digest: hash(ordered),
    anyOrder: sorted === ordered ? null : hash(sorted),
    complete: encoder.complete,
  };
}

function preview(value, depth = 0) {
  if (depth > 2) return "…";
  const kind = typeof value;
  if (value === null || kind === "undefined" || kind === "boolean" || kind === "number")
    return Object.is(value, -0) ? "-0" : String(value);
  if (kind === "bigint") return `${value}n`;
  if (kind === "string") return JSON.stringify(normal(value));
  if (kind === "symbol") return `Symbol(${value.description ?? ""})`;
  if (kind === "function") return `[function ${value.name || "anonymous"}]`;
  if (types.isProxy(value)) return "[Proxy]";
  if (Array.isArray(value)) {
    const items = [];
    for (let i = 0; i < Math.min(value.length, 10); i += 1) {
      const descriptor = Object.getOwnPropertyDescriptor(value, i);
      items.push(descriptor && "value" in descriptor ? preview(descriptor.value, depth + 1) : "?");
    }
    return `[${items.join(", ")}${value.length > 10 ? ", …" : ""}]`;
  }
  const name = typeName(value);
  if (types.isNativeError(value) || value instanceof Error) {
    const message = Object.getOwnPropertyDescriptor(value, "message");
    return `${name}(${JSON.stringify(message && "value" in message ? normal(String(message.value)) : "")})`;
  }
  if (types.isDate(value)) return `Date(${Date.prototype.getTime.call(value)})`;
  const fields = own(value)
    .slice(0, 10)
    .map(([key, d]) => `${key}: ${"value" in d ? preview(d.value, depth + 1) : "[getter]"}`);
  return `${name === "Object" ? "" : name}{${fields.join(", ")}}`;
}

function capped(text) {
  return text.length <= PREVIEW ? text : `${text.slice(0, PREVIEW - 1)}…`;
}

let current = null;
const counts = new Map();
let pending = [];

function setTest(test) {
  current = test;
}

function flush() {
  if (out && pending.length)
    appendFileSync(out, pending.map((r) => `${JSON.stringify(r)}\n`).join(""));
  pending = [];
}

function record(entry) {
  pending.push(entry);
}

function wrap(file, name, fn) {
  if (typeof fn !== "function" || fn.__reproWrapped) return fn;
  const target = [file, name, 1, 1];
  const wrapped = function (...args) {
    // Construction is not a call to trace: it goes to the function as it was.
    if (new.target) return Reflect.construct(fn, args, new.target === wrapped ? fn : new.target);
    const test = current;
    if (test === null) return fn.apply(this, args);
    const key = `${test}\0${file}\0${name}`;
    const index = counts.get(key) ?? 0;
    counts.set(key, index + 1);
    if (index > BUDGET) return fn.apply(this, args);
    if (index === BUDGET) {
      record({ kind: "truncated", nodeid: test, target, captured: BUDGET });
      return fn.apply(this, args);
    }
    const argsDigest = digests(args);
    const previewed =
      index < SAMPLES || wanted.has(`${test}\0${file}\0${name}\0${argsDigest.digest}`);
    const base = {
      kind: "call",
      nodeid: test,
      phase: "call",
      target,
      index,
      args: argsDigest.digest,
      args_complete: argsDigest.complete,
      yields: [],
      yields_complete: true,
    };
    if (previewed) base.args_preview = capped(`${name}(${args.map((a) => preview(a)).join(", ")})`);
    const ended = (outcome, value) => {
      const result = digests(value);
      const entry = {
        ...base,
        outcome,
        result: result.digest,
        result_complete: result.complete,
        type: typeName(value),
      };
      if (result.anyOrder) entry.result_any_order = result.anyOrder;
      if (previewed) entry.result_preview = capped(preview(value));
      record(entry);
    };
    let value;
    try {
      value = fn.apply(this, args);
    } catch (error) {
      ended("raise", error);
      throw error;
    }
    if (types.isPromise(value)) {
      return value.then(
        (settled) => {
          ended("return", settled);
          return settled;
        },
        (error) => {
          ended("raise", error);
          throw error;
        },
      );
    }
    ended("return", value);
    return value;
  };
  Object.defineProperty(wrapped, "__reproWrapped", { value: true });
  Object.defineProperty(wrapped, "name", { value: fn.name });
  Object.defineProperty(wrapped, "length", { value: fn.length });
  if (Object.getOwnPropertyDescriptor(fn, "prototype")?.writable !== false) {
    wrapped.prototype = fn.prototype;
  }
  return wrapped;
}

// A class's method or accessor, wrapped in place through its descriptor (``slot``: "value",
// "get" or "set").
function method(holder, key, slot, file, name) {
  const descriptor = Object.getOwnPropertyDescriptor(holder, key);
  if (!descriptor || typeof descriptor[slot] !== "function" || !descriptor.configurable) return;
  Object.defineProperty(holder, key, { ...descriptor, [slot]: wrap(file, name, descriptor[slot]) });
}

module.exports = { digests, flush, method, preview, setTest, wrap };
