import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { cardUnits, DOT_COLS } from "./atlas";
import {
  cardHeader,
  MAX_CARDS,
  NEVER,
  ringContent,
  scriptImport,
  scriptSymbol,
  targetFile,
} from "./content";

function modelOf(events: readonly unknown[]): CockpitModel {
  const model = new CockpitModel();
  model.ingest(events);
  return model;
}

const demo = modelOf(runEvents());
const content = ringContent(demo);

describe("targetFile", () => {
  it("takes the file, or the file part of a pytest node id", () => {
    expect(targetFile({ file: "a/b.py", test: "x::y" })).toBe("a/b.py");
    expect(targetFile({ test: "tests/test_x.py::test_y" })).toBe("tests/test_x.py");
    expect(targetFile({ test: "tests/test_x.py" })).toBe("tests/test_x.py");
    expect(targetFile({})).toBeUndefined();
    expect(targetFile(null)).toBeUndefined();
  });
});

describe("ringContent", () => {
  it("gives at most MAX_CARDS module files a card, in path order", () => {
    const files = demo.graph.ids.flatMap((_, i) =>
      demo.graph.nodeTypeName(i) === "module" ? [demo.graph.files[i] as string] : [],
    );
    const shown = content.cards.map((c) => c.file);
    expect(shown).toHaveLength(Math.min(files.length, MAX_CARDS));
    expect(shown).toEqual([...shown].sort());
    for (const file of shown) expect(files).toContain(file);
  });

  it("builds each card only from what events say about the file", () => {
    const parse = content.cards.find((c) => c.file === "timekeeper/parse.py");
    expect(parse?.header).toBe("// timekeeper / parse");
    // Its symbols with their line numbers, changed ones flagged, then its imports.
    expect(parse?.rows).toEqual(
      expect.arrayContaining([
        { num: "42", text: "def parse_date()", flag: true },
        { num: "", text: "from timekeeper import _util", flag: false },
      ]),
    );
    expect(parse?.rows.findIndex((r) => r.num === "")).toBe(3); // symbols first
    expect(parse?.meta).toEqual([
      expect.stringMatching(/^\d+ imp$/),
      expect.stringMatching(/^\d+ in$/),
      "3 sym",
      "±2",
    ]);
    // The neighbour fingerprint: lit buckets of the modules it imports or is imported by.
    expect(parse?.dotRows).toBe(4);
    expect(parse?.dots.length).toBeGreaterThan(3);
    for (const d of parse?.dots ?? []) expect(d).toBeLessThan(DOT_COLS * 4);
    expect(parse?.units).toBe(parse === undefined ? 0 : cardUnits(parse));
  });

  it("heads each card with its package and module, like the reference's", () => {
    expect(cardHeader("timekeeper.tz.fold")).toBe("// tz / fold");
    expect(cardHeader("timekeeper")).toBe("// timekeeper");
  });

  it("writes a JavaScript file's card as JavaScript (K08)", () => {
    expect(cardHeader("src/util/dates.ts", true)).toBe("// util / dates.ts");
    expect(cardHeader("index.js", true)).toBe("// index.js");
    expect(scriptImport("src/a.ts", "src/b.ts")).toBe('import "./b.ts"');
    expect(scriptImport("src/lib/a.ts", "src/b.ts")).toBe('import "../b.ts"');
    expect(scriptImport("test/a.test.ts", "src/lib/b.ts")).toBe('import "../src/lib/b.ts"');
    expect(scriptImport("a.js", "lib/b.js")).toBe('import "./lib/b.js"');
    expect(scriptSymbol("add")).toBe("function add()");
    expect(scriptSymbol("get-size")).toBe("get size()");
  });

  it("stamps appear, blast-radius and change times from the log", () => {
    const time = (kind: string) => {
      const i = demo.kinds.lastIndex(kind as "blast.computed", demo.store.length);
      return demo.store.time[i] as number;
    };
    const parse = content.cards.find((c) => c.file === "timekeeper/parse.py");
    const untouched = content.cards.find((c) => c.blastAt === NEVER);
    expect(parse?.blastAt).toBe(time("blast.computed"));
    expect(parse?.changedAt).toBeLessThan(NEVER);
    expect(untouched?.changedAt).toBe(NEVER);
    for (const card of content.cards) expect(card.appear).toBeLessThan(card.blastAt);
  });

  it("lists focus events in time order, each pointing at a card", () => {
    expect(content.focus.length).toBeGreaterThan(10);
    for (let i = 1; i < content.focus.length; i++) {
      expect(content.focus[i]?.time).toBeGreaterThanOrEqual(content.focus[i - 1]?.time ?? 0);
    }
    for (const { card } of content.focus) expect(content.cards[card]).toBeDefined();
  });

  it("keeps the files the run is about when it has to choose", () => {
    const stress = modelOf(runEvents(STRESS));
    const big = ringContent(stress);
    expect(big.cards).toHaveLength(MAX_CARDS);
    const chosen = new Set(big.cards.map((c) => c.file));
    for (const file of [
      "timekeeper/parse.py",
      "timekeeper/fmt.py",
      "timekeeper/recur.py",
      "timekeeper/tz/fold.py",
    ]) {
      expect(chosen.has(file)).toBe(true);
    }
  });

  it("changes its key when any card's text changes, and only then", () => {
    expect(ringContent(demo).key).toBe(content.key);
    const partial = modelOf(runEvents().slice(0, 900));
    expect(ringContent(partial).key).not.toBe(content.key);
  });
});
