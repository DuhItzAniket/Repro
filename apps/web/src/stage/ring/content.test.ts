import { STRESS } from "@repro/synth";
import { describe, expect, it } from "vitest";
import { CockpitModel } from "../../model/cockpit";
import { runEvents } from "../../model/test-support";
import { MAX_CARDS, NEVER, ringContent, targetFile } from "./content";

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
  it("gives every module file a card, in path order", () => {
    const files = demo.graph.ids.flatMap((_, i) =>
      demo.graph.nodeTypeName(i) === "module" ? [demo.graph.files[i]] : [],
    );
    expect(content.cards.map((c) => c.file)).toEqual([...files].sort());
  });

  it("builds each card only from what events say about the file", () => {
    const parse = content.cards.find((c) => c.file === "timekeeper/parse.py");
    expect(parse?.lines[0]).toBe("timekeeper/parse.py");
    expect(parse?.lines).toEqual(
      expect.arrayContaining(["import timekeeper._util", "def parse_date"]),
    );
    expect(parse?.meta).toEqual(["parse.py", expect.stringMatching(/^\d+ imp$/), "3 sym", "±2"]);
    expect(parse?.weight).toBe(1 + (parse?.lines.length ?? 0));
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
