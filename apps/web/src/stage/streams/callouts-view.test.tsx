// @vitest-environment jsdom
// B15: callout boxes stay inside the stage in every view.
import { signal } from "@preact/signals";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, describe, expect, it } from "vitest";
import type { Callout } from "./callouts";
import { CALLOUT_INSET, Callouts, calloutTransform } from "./callouts-view";

let root: HTMLElement | null = null;
afterEach(() => {
  if (root !== null) {
    render(null, root);
    root.remove();
  }
});

describe("callout boxes", () => {
  it("sit right of and above their anchor, clamped to the stage's edges", () => {
    const transform = calloutTransform(811.4, 300.6);
    // Left edge: the anchor plus 8 px, or as far right as keeps the box inside the stage.
    expect(transform).toContain(`min(819px, calc(100cqw - 100% - ${CALLOUT_INSET}px))`);
    // Top edge: the anchor less 10 px, kept inside the stage at the top and the bottom.
    expect(transform).toContain(
      `clamp(${CALLOUT_INSET}px, 291px, calc(100cqh - 100% - ${CALLOUT_INSET}px))`,
    );
  });

  it("renders each callout with that transform, inside a size container", () => {
    root = document.createElement("div");
    document.body.append(root);
    const items = signal<readonly Callout[]>([
      { key: "e1", label: "MISSING", value: "no covering test", tint: "fail", x: 811, y: 300 },
    ]);
    act(() => render(<Callouts items={items} />, root as HTMLElement));
    const box = root.querySelector<HTMLElement>(".callout");
    expect(box?.style.transform).toBe(calloutTransform(811, 300));
    expect(box?.textContent).toBe("MISSINGno covering test");
  });
});
