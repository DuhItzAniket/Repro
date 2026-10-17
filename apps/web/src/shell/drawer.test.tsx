// @vitest-environment jsdom
// The evidence drawer's empty tables: "None yet." while the run can add to them, "None." after.
import { signal } from "@preact/signals";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { DrawerView } from "../focus/evidence";
import { Drawer } from "./drawer";

const view = (final: boolean): DrawerView => ({
  title: "Reproduction Card · FLAGGED",
  subtitle: "the run found a problem",
  sections: [
    { title: "Claims", table: { caption: "Claims", columns: ["Claim", "Verdict"], rows: [] } },
  ],
  final,
});

let root: HTMLElement;
beforeEach(() => {
  root = document.createElement("div");
  document.body.append(root);
});
afterEach(() => {
  render(null, root);
  root.remove();
});

const emptyRow = (final: boolean): string | null | undefined => {
  const rect = { x: 0, y: 0, w: 400, h: 600 };
  act(() => render(<Drawer rect={rect} view={signal(view(final))} onFocus={() => {}} />, root));
  return root.querySelector(".rows tbody td")?.textContent;
};

describe("the evidence drawer", () => {
  it("says an empty table may still fill while the run goes on", () => {
    expect(emptyRow(false)).toBe("None yet.");
  });

  it("says an empty table is empty once nothing more can come", () => {
    expect(emptyRow(true)).toBe("None.");
  });
});
