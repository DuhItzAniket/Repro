// @vitest-environment jsdom
// B15: the stage settings menu.
import { signal } from "@preact/signals";
import { render } from "preact";
import { act } from "preact/test-utils";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_LOOK, LOOK_PARTS, LOOK_SPECS, type Look } from "../stage/look";
import { multiple, SETTINGS_ID, Settings, zoomText } from "./settings";

let root: HTMLElement;
beforeEach(() => {
  root = document.createElement("div");
  document.body.append(root);
});
afterEach(() => {
  render(null, root);
  root.remove();
});

function mount(look = signal<Look>(DEFAULT_LOOK)) {
  const open = signal(true);
  const opener = document.createElement("button");
  opener.setAttribute("aria-controls", SETTINGS_ID);
  root.append(opener);
  const host = document.createElement("div");
  root.append(host);
  act(() => render(<Settings open={open} look={look} />, host));
  const slider = (id: string) => {
    const found = root.querySelector<HTMLInputElement>(`#${SETTINGS_ID}-${id}`);
    if (found === null) throw new Error(`no slider ${id}`);
    return found;
  };
  const button = (label: string) => {
    const found = [...root.querySelectorAll<HTMLButtonElement>("button")].find(
      (b) => b.textContent === label,
    );
    if (found === undefined) throw new Error(`no ${label} button`);
    return found;
  };
  const slide = (id: string, value: number) =>
    act(() => {
      const input = slider(id);
      input.value = String(value);
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  return { look, open, opener, slider, button, slide };
}

describe("stage settings", () => {
  it("labels a thickness and a brightness slider for every part, within its range", () => {
    const { slider } = mount();
    for (const part of LOOK_PARTS) {
      for (const key of ["width", "brightness"] as const) {
        const input = slider(`${part}-${key}`);
        const range = LOOK_SPECS[part][key];
        expect(Number(input.min)).toBe(range.min);
        expect(Number(input.max)).toBe(range.max);
        expect(input.getAttribute("aria-valuetext")).toBe("1×");
        // A visible label and the part's description name it.
        expect(root.querySelector(`label[for="${input.id}"]`)?.textContent).toBeTruthy();
        const about = input.getAttribute("aria-describedby") ?? "";
        expect(document.getElementById(about)?.textContent).toBe(LOOK_SPECS[part].description);
      }
    }
  });

  it("changes the look as a slider moves, clamped to its range", () => {
    const { look, slide, slider } = mount();
    slide("mesh-width", 2);
    expect(look.value.parts.mesh.width).toBe(2);
    expect(slider("mesh-width").getAttribute("aria-valuetext")).toBe(multiple(2));
    slide("strands-brightness", 0.4);
    expect(look.value.parts.strands.brightness).toBe(0.4);
    expect(look.value.parts.lines).toEqual(DEFAULT_LOOK.parts.lines);
  });

  it("switches between the arc and the whole wheel, and zooms in between", () => {
    const { look, button, slide, slider } = mount();
    expect(button("Arc").getAttribute("aria-pressed")).toBe("true");
    act(() => button("Whole wheel").click());
    expect(look.value.zoom).toBe(1);
    expect(button("Whole wheel").getAttribute("aria-pressed")).toBe("true");
    expect(slider("zoom").getAttribute("aria-valuetext")).toBe(zoomText(1));
    slide("zoom", 0.25);
    expect(look.value.zoom).toBe(0.25);
    expect(button("Arc").getAttribute("aria-pressed")).toBe("false");
    expect(button("Whole wheel").getAttribute("aria-pressed")).toBe("false");
  });

  it("resets to the defaults, and the reset is disabled when there is nothing to reset", () => {
    const { look, button, slide } = mount();
    expect(button("Reset to defaults").disabled).toBe(true);
    slide("nodes-brightness", 1.5);
    expect(button("Reset to defaults").disabled).toBe(false);
    act(() => button("Reset to defaults").click());
    expect(look.value).toBe(DEFAULT_LOOK);
  });

  it("closes on Escape and gives focus back to its button", () => {
    const { open, opener, slider } = mount();
    const input = slider("bullets-width");
    input.focus();
    act(() => {
      input.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(open.value).toBe(false);
    expect(document.activeElement).toBe(opener);
    expect(root.querySelector(`#${SETTINGS_ID}`)?.hasAttribute("hidden")).toBe(true);
  });
});
