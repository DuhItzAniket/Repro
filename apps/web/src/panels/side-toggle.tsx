import type { Signal } from "@preact/signals";
import type { ExecutionSides } from "./execution";

const OPTIONS: readonly { value: ExecutionSides; label: string }[] = [
  { value: "base", label: "Base" },
  { value: "head", label: "Head" },
  { value: "both", label: "Both" },
];

/** BASE · HEAD · BOTH under the execution lanes (DESIGN.md panel 2). */
export function SideToggle({ sides }: { sides: Signal<ExecutionSides> }) {
  return (
    <fieldset class="toggles">
      <legend class="visually-hidden">Execution lanes</legend>
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          class="toggle"
          aria-pressed={sides.value === option.value}
          onClick={() => {
            sides.value = option.value;
          }}
        >
          {option.label}
        </button>
      ))}
    </fieldset>
  );
}
