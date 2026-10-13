import type { Signal } from "@preact/signals";
import type { Callout } from "./callouts";

/**
 * The callout boxes over the stage. Decorative for assistive technology: the same findings
 * reach screen readers through the feed and the card (B11), so this layer is aria-hidden.
 */
export function Callouts({ items }: { items: Signal<readonly Callout[]> }) {
  return (
    <div class="callouts" aria-hidden="true">
      {items.value.map((c) => (
        <div
          key={c.key}
          class="callout"
          data-tint={c.tint}
          style={{ transform: `translate(${Math.round(c.x) + 8}px, ${Math.round(c.y) - 10}px)` }}
        >
          <span class="callout-label">{c.label}</span>
          <span class="callout-value">{c.value}</span>
        </div>
      ))}
    </div>
  );
}
