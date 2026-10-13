import { describe, expect, it } from "vitest";
import { moduleOf, nameOf, testFile } from "./changes";
import { CockpitModel } from "./cockpit";
import { runEvents } from "./test-support";

const events = runEvents();
const model = new CockpitModel();
model.ingest(events);

/** Changed symbol → the short names of the tests routed to it. */
function routesIn(m: CockpitModel): Map<string, string[]> {
  const out = new Map<string, string[]>();
  m.changes.changed.forEach((change, c) => {
    const tests = m.changes.selections
      .filter((_, s) => m.changes.routesOf(s).includes(c))
      .map((s) => s.test.slice(s.test.indexOf("::") + 2));
    out.set(nameOf(change.symbol), tests);
  });
  return out;
}

describe("ChangeIndex", () => {
  it("indexes every changed symbol and selection", () => {
    expect(model.changes.changed.map((c) => nameOf(c.symbol))).toEqual([
      "parse_date",
      "_split_iso",
      "<module>",
      "format_duration",
      "expand_rrule",
      "_by_month",
      "_fold_offset",
    ]);
    expect(model.changes.selections).toHaveLength(17);
  });

  it("routes tests through the symbols they were selected for and their calls", () => {
    const routes = routesIn(model);
    expect(routes.get("format_duration")).toEqual([
      "test_format_duration_hours",
      "test_format_duration_minutes",
      "test_relative_hours",
    ]);
    // Selected for resolve_fold / get_zone, which call the unclaimed _fold_offset.
    expect(routes.get("_fold_offset")).toEqual(["test_spring_forward", "test_fold_resolution"]);
  });

  it("routes module-level changes to tests whose module imports the changed module", () => {
    // test_format_date_locale is selected by module_import and names no symbols.
    expect(routesIn(model).get("<module>")).toEqual(["test_format_date_locale"]);
  });

  it("gives the same routes however the log is ingested and queried (pure in the cursor)", () => {
    const chunked = new CockpitModel();
    for (let i = 0; i < events.length; i += 97) {
      chunked.ingest(events.slice(i, i + 97));
      // Querying mid-ingestion must not freeze routes built from a partial graph.
      chunked.changes.selections.forEach((_, s) => {
        chunked.changes.routesOf(s);
      });
    }
    expect(routesIn(chunked)).toEqual(routesIn(model));
  });

  it("parses symbol and test ids", () => {
    expect(moduleOf("pkg.mod:Class.method#0")).toBe("pkg.mod");
    expect(nameOf("pkg.mod:Class.method#0")).toBe("Class.method");
    expect(testFile("tests/test_x.py::test_y")).toBe("tests/test_x.py");
  });
});
