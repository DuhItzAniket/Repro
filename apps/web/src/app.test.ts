import { describe, expect, it } from "vitest";
import { mount, PRODUCT_NAME } from "./app";

describe("mount", () => {
  it("renders the product name into the root element", () => {
    const root = { textContent: "" };
    mount(root);
    expect(root.textContent).toBe(PRODUCT_NAME);
  });
});
