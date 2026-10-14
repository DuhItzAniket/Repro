import type { Signal } from "@preact/signals";
import type { Callout } from "./callouts";

/** Space kept between a callout box and the stage's edges, px. */
export const CALLOUT_INSET = 4;

/**
 * Where a callout box sits: just right of and above its anchor, but never past the stage's
 * edges. The box's own size is only known to the browser, so the clamp is CSS: `100cqw` and
 * `100cqh` are the stage (the `.callouts` container), `100%` the box. Zoomed out (B15) the anchors
 * sit near the stage's right edge, and a box would otherwise be cut off there.
 */
export function calloutTransform(x: number, y: number): string {
  const left = `min(${Math.round(x) + 8}px, calc(100cqw - 100% - ${CALLOUT_INSET}px))`;
  const top = `clamp(${CALLOUT_INSET}px, ${Math.round(y) - 10}px, calc(100cqh - 100% - ${CALLOUT_INSET}px))`;
  return `translate(${left}, ${top})`;
}

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
          style={{ transform: calloutTransform(c.x, c.y) }}
        >
          <span class="callout-label">{c.label}</span>
          <span class="callout-value">{c.value}</span>
        </div>
      ))}
    </div>
  );
}
