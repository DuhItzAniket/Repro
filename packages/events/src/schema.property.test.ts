import { join } from "node:path";
import fc from "fast-check";
import { describe, expect, it } from "vitest";
import { EVENT_KINDS } from "./index";
import { type EventCases, EXAMPLES_DIR, readJson, validator } from "./testing/ajv";

const validateEvent = validator("event.schema.json");
const validEvents = EVENT_KINDS.map(
  (kind) => readJson<EventCases>(join(EXAMPLES_DIR, "events", `${kind}.json`)).valid[0],
) as Record<string, unknown>[];
const anyValidEvent = fc.constantFrom(...validEvents);

/** Rebuild an object with its keys in a permuted order, recursively. */
function permuteKeys(value: unknown, seed: number): unknown {
  if (Array.isArray(value)) return value.map((item, i) => permuteKeys(item, seed + i));
  if (value === null || typeof value !== "object") return value;
  const entries = Object.entries(value as Record<string, unknown>);
  const order = entries
    .map((entry, i) => ({ entry, key: Math.sin(seed * 9973 + i * 31) }))
    .sort((a, b) => a.key - b.key);
  return Object.fromEntries(order.map(({ entry: [k, v] }) => [k, permuteKeys(v, seed + 1)]));
}

describe("event schema properties (fast-check)", () => {
  it("validity does not depend on property order", () => {
    fc.assert(
      fc.property(anyValidEvent, fc.integer(), (event, seed) => {
        expect(validateEvent(permuteKeys(event, seed))).toBe(true);
      }),
    );
  });

  it("an unregistered kind is always rejected", () => {
    const known = new Set<string>(EVENT_KINDS);
    const unknownKind = fc
      .tuple(fc.stringMatching(/^[a-z]{1,8}$/), fc.stringMatching(/^[a-z_]{1,10}$/))
      .map(([a, b]) => `${a}.${b}`)
      .filter((kind) => !known.has(kind));
    fc.assert(
      fc.property(anyValidEvent, unknownKind, (event, kind) => {
        expect(validateEvent({ ...event, kind })).toBe(false);
      }),
    );
  });

  it("seq below 1 or non-integer is always rejected", () => {
    const badSeq = fc.oneof(
      fc.integer({ max: 0 }),
      fc.double({ min: 1.0001, max: 1e6, noNaN: true }).filter((n) => !Number.isInteger(n)),
    );
    fc.assert(
      fc.property(anyValidEvent, badSeq, (event, seq) => {
        expect(validateEvent({ ...event, seq })).toBe(false);
      }),
    );
  });

  it("any extra envelope property is rejected (closed objects)", () => {
    const envelopeKeys = new Set(Object.keys(validEvents[0] ?? {}));
    const extraKey = fc
      .stringMatching(/^[a-z][a-z_]{0,15}$/)
      .filter((key) => !envelopeKeys.has(key) && key !== "parent");
    fc.assert(
      fc.property(anyValidEvent, extraKey, fc.jsonValue(), (event, key, value) => {
        expect(validateEvent({ ...event, [key]: value })).toBe(false);
      }),
    );
  });
});
