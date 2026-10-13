import { join } from "node:path";
import { describe, expect, expectTypeOf, it } from "vitest";
import {
  EVENT_KINDS,
  type EventKind,
  KIND_STAGES,
  type OutcomeClass,
  type ReproEvent,
  type Stage,
  type TestOutcome,
} from "./index";
import {
  type EventCases,
  EXAMPLES_DIR,
  type ModelCases,
  readJson,
  SCHEMA_DIR,
  validator,
} from "./testing/ajv";

const validateEvent = validator("event.schema.json");

describe("JSON Schema validation in TypeScript (Ajv, draft 2020-12)", () => {
  it.each([...EVENT_KINDS])("%s: valid examples pass, invalid examples fail", (kind) => {
    const cases = readJson<EventCases>(join(EXAMPLES_DIR, "events", `${kind}.json`));
    for (const event of cases.valid) {
      expect(validateEvent(event), JSON.stringify(validateEvent.errors)).toBe(true);
    }
    for (const { reason, event } of cases.invalid) {
      expect(validateEvent(event), reason).toBe(false);
    }
  });

  it("envelope examples", () => {
    const cases = readJson<EventCases>(join(EXAMPLES_DIR, "envelope.json"));
    for (const event of cases.valid) expect(validateEvent(event)).toBe(true);
    for (const { reason, event } of cases.invalid) expect(validateEvent(event), reason).toBe(false);
  });

  it.each(["card", "claim", "evidence", "missing", "verdict"])("model %s", (name) => {
    const validate = validator(`models/${name}.schema.json`);
    const cases = readJson<ModelCases>(join(EXAMPLES_DIR, "models", `${name}.json`));
    for (const value of cases.valid) {
      expect(validate(value), JSON.stringify(validate.errors)).toBe(true);
    }
    for (const { reason, value } of cases.invalid) expect(validate(value), reason).toBe(false);
  });
});

describe("generated registry constants", () => {
  it("lists every kind in the schema registry, in order", () => {
    const registry = readJson<{ oneOf: { properties: { kind: { const: string } } }[] }>(
      join(SCHEMA_DIR, "event.schema.json"),
    );
    expect([...EVENT_KINDS]).toEqual(registry.oneOf.map((b) => b.properties.kind.const));
    expect(Object.keys(KIND_STAGES)).toEqual([...EVENT_KINDS]);
  });
});

describe("generated types (checked by `pnpm typecheck`)", () => {
  it("narrows ReproEvent by kind", () => {
    type Finished = Extract<ReproEvent, { kind: "test.finished" }>;
    expectTypeOf<Finished["payload"]["outcome"]>().toEqualTypeOf<TestOutcome>();
    expectTypeOf<Finished["stage"]>().toEqualTypeOf<"run">();
    type Outcome = Extract<ReproEvent, { kind: "diff.outcome" }>;
    expectTypeOf<Outcome["payload"]["class"]>().toEqualTypeOf<OutcomeClass>();
    expectTypeOf<Extract<ReproEvent, { kind: "log.line" }>["stage"]>().toEqualTypeOf<Stage>();
    expectTypeOf<ReproEvent["kind"]>().toEqualTypeOf<EventKind>();
  });

  it("supports exhaustive switches over kinds", () => {
    const stageOf = (event: ReproEvent): Stage => {
      switch (event.kind) {
        case "test.finished":
          return event.stage;
        default:
          return event.stage;
      }
    };
    const example = readJson<EventCases>(join(EXAMPLES_DIR, "events", "test.finished.json"))
      .valid[0] as ReproEvent;
    expect(stageOf(example)).toBe("run");
  });
});
