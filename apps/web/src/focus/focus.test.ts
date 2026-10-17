import { describe, expect, it } from "vitest";
import { CockpitModel } from "../model/cockpit";
import { runEvents } from "../model/test-support";
import { ANNOUNCE_MS, FeedAnnouncer } from "../shell/announcer";
import { drawerView } from "./evidence";
import { type Focus, focusKey, focusTargets } from "./focus";

const model = new CockpitModel();
model.ingest(runEvents());
const END = model.store.length;
const state = model.folder.stateAt(END);

describe("focus", () => {
  it("gives equal foci equal keys and different foci different keys", () => {
    const foci: Focus[] = [
      { kind: "claim", id: "C1" },
      { kind: "file", file: "timekeeper/parse.py" },
      { kind: "symbol", symbol: "timekeeper.parse:parse_date#0", file: "timekeeper/parse.py" },
      { kind: "check", index: 3 },
      { kind: "agent", id: "a08" },
    ];
    const keys = foci.map(focusKey);
    expect(new Set(keys).size).toBe(foci.length);
    expect(focusKey({ kind: "check", index: 3 })).toBe(keys[3]);
    expect(focusKey(null)).toBe("");
  });

  it("resolves what each focus highlights on the stage", () => {
    const claim = focusTargets({ kind: "claim", id: "C3" }, state, model.changes);
    expect([...claim.files]).toEqual(["timekeeper/fmt.py"]);
    expect([...claim.symbols]).toEqual(["timekeeper.fmt:format_duration#0"]);
    // A file focus covers every change in the file.
    const file = focusTargets({ kind: "file", file: "timekeeper/parse.py" }, state, model.changes);
    expect([...file.symbols].sort()).toEqual([
      "timekeeper.parse:_split_iso#0",
      "timekeeper.parse:parse_date#0",
    ]);
    // A check that names only a test highlights the test's file.
    const outcome = state.checks.list.findIndex((c) => c.kind === "diff.outcome");
    const check = focusTargets({ kind: "check", index: outcome }, state, model.changes);
    expect([...check.files]).toEqual(["tests/test_calendars.py"]);
    expect(focusTargets(null, state, model.changes).key).toBe("");
  });
});

describe("evidence drawer content", () => {
  it("quotes a claim's verdict and lists the checks it rests on", () => {
    const view = drawerView({ kind: "claim", id: "C3" }, model, END);
    expect(view.title).toBe("C3 · refactor");
    const verdict = view.sections.find((s) => s.title === "Verdict");
    expect(verdict?.facts?.find((f) => f.label === "Verdict")?.value).toBe("contradicted");
    expect(verdict?.facts?.find((f) => f.label === "Agreement")?.value).toBe("2 of 2 runs agree");
    expect(verdict?.paragraphs?.some((p) => p.startsWith("“"))).toBe(true); // a quote
    const checks = view.sections.find((s) => s.title === "Related checks")?.table;
    expect(checks?.rows.some((r) => r.cells[2] === "flagged" && r.focus?.kind === "check")).toBe(
      true,
    );
  });

  it("shows a behaviour check's evidence, its trace samples and the claim citing it", () => {
    const index = state.checks.list.findIndex(
      (c) => c.kind === "diff.behaviour" && c.target?.symbol?.includes("format_duration"),
    );
    const view = drawerView({ kind: "check", index }, model, END);
    expect(view.title).toBe(`Check #${index + 1} · diff.behaviour`);
    expect(view.sections.some((s) => s.title.startsWith("Evidence ev_"))).toBe(true);
    const samples = view.sections.find((s) => s.title === "Trace samples")?.table;
    expect(new Set(samples?.rows.map((r) => r.cells[1]))).toEqual(
      new Set(["base", "base_repeat", "head"]),
    );
    const citing = view.sections.find((s) => s.title === "Cited by")?.table;
    expect(citing?.rows.map((r) => r.cells[0])).toEqual(["C3"]);
  });

  it("lists a file's changes, routed tests and checks", () => {
    const view = drawerView({ kind: "file", file: "timekeeper/tz/fold.py" }, model, END);
    expect(view.sections[0]?.table?.rows.map((r) => r.cells[0])).toEqual(["_fold_offset"]);
    expect(view.sections[1]?.paragraphs).toEqual([
      "tests/test_dst.py::test_spring_forward",
      "tests/test_tz.py::test_fold_resolution",
    ]);
    expect(view.sections[2]?.table?.rows.length).toBe(2);
  });

  it("shows an agent's state and recent tool calls", () => {
    const view = drawerView({ kind: "agent", id: "a08" }, model, END);
    expect(view.title).toBe("a08 · review");
    expect(view.sections[0]?.facts?.find((f) => f.label === "Verdicts")?.value).toContain(
      "1 contradicted",
    );
  });

  it("only shows what has happened by the cursor", () => {
    expect(drawerView({ kind: "claim", id: "C3" }, model, 0).subtitle).toBe("not extracted yet");
  });

  it("is final once the run has finished, and the card once it is published", () => {
    const [finished] = model.kinds.last("run.finished", END, 1);
    const [published] = model.kinds.last("card.published", END, 1);
    if (finished === undefined || published === undefined) throw new Error("no end in the log");
    expect(published).toBeLessThan(finished); // the card is published, then the run finishes
    const claim: Focus = { kind: "claim", id: "C3" };
    expect(drawerView(claim, model, published + 1).final).toBe(false);
    expect(drawerView(claim, model, finished + 1).final).toBe(true);
    expect(drawerView({ kind: "card" }, model, published).final).toBe(false);
    expect(drawerView({ kind: "card" }, model, published + 1).final).toBe(true);
  });
});

describe("feed announcements (role=log, throttled)", () => {
  it("batches lines into at most one summary every 2 s and stays quiet while paused", () => {
    let now = 0;
    const announcer = new FeedAnnouncer(() => now);
    const logs = model.kinds.last("log.line", END, 1000);
    const at = (n: number) => (logs[n - 1] as number) + 1; // cursor just after the nth line
    expect(announcer.next(model, at(1))).not.toBeNull();
    now += 500;
    expect(announcer.next(model, at(5))).toBeNull(); // too soon
    now += ANNOUNCE_MS;
    const batch = announcer.next(model, at(5));
    expect(batch).toMatch(/^4 new lines\. Latest, /);
    now += ANNOUNCE_MS;
    expect(announcer.next(model, at(5))).toBeNull(); // paused: nothing new
    expect(announcer.next(model, at(2))).toBeNull(); // scrubbed back: quiet reset
    now += ANNOUNCE_MS;
    expect(announcer.next(model, at(3))).not.toBeNull();
  });

  it("counts warnings and errors in a batch", () => {
    let now = 0;
    const announcer = new FeedAnnouncer(() => now);
    const all = model.kinds.last("log.line", END, 1000);
    const warnings = all.filter((i) => {
      const event = model.store.event(i);
      return (
        event?.kind === "log.line" &&
        event.payload.level !== "info" &&
        event.payload.level !== "debug"
      );
    }).length;
    now = 10_000;
    const summary = announcer.next(model, END);
    expect(summary).toContain(`(${warnings} warning`);
  });
});
