import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { CockpitModel, headerCounters } from "./cockpit";
import { parseJsonl } from "./jsonl";

const DEMO = new URL("../../fixtures/demo-run.jsonl", import.meta.url);

describe("parseJsonl", () => {
  it("loads the committed demo fixture end to end", () => {
    const { values, errors } = parseJsonl(readFileSync(DEMO, "utf8"));
    expect(errors).toEqual([]);
    const model = new CockpitModel();
    expect(model.ingest(values)).toEqual({ appended: values.length, duplicates: 0 });
    expect(headerCounters(model.folder.sync())).toEqual({
      claims: 4,
      agents: 12,
      files: 147,
      checks: 28,
      flagged: 4,
    });
  });

  it("accepts CRLF and reports bad lines without throwing", () => {
    const { values, errors } = parseJsonl('{"a":1}\r\n\nnot json\n[2]\n');
    expect(values).toEqual([{ a: 1 }, [2]]);
    expect(errors.map((e) => [e.line, e.message === "blank line"])).toEqual([
      [2, true],
      [3, false],
    ]);
  });
});
