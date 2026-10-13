export const PRODUCT_NAME = "Repro";

/** Minimal shell until the cockpit layout lands in B03. */
export function mount(root: Pick<HTMLElement, "textContent">): void {
  root.textContent = PRODUCT_NAME;
}
