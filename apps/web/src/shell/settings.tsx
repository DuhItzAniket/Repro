/**
 * The stage settings menu (B15): sliders for each part's thickness and brightness, and how much
 * of the wheel the stage shows. A disclosure, not a dialog: the Settings button in the transport
 * opens it over the stage's lower right and focus stays where it is; Escape inside it closes it
 * and returns focus to the button. Every change goes through `clampLook`, so a slider can never
 * set a value outside its flash-safe range.
 */
import type { Signal } from "@preact/signals";
import { useEffect, useRef } from "preact/hooks";
import {
  clampLook,
  DEFAULT_LOOK,
  LOOK_PARTS,
  LOOK_SPECS,
  type Look,
  type LookPart,
  type PartLook,
  type Range,
  sameLook,
  withPart,
  ZOOM_RANGE,
} from "../stage/look";

export const SETTINGS_ID = "stage-settings";

/** A multiple as the slider reads it: "1×", "0.75×". */
export const multiple = (value: number): string => `${Number(value.toFixed(2))}×`;

/** The zoom as the slider reads it. */
export const zoomText = (zoom: number): string =>
  zoom <= 0 ? "arc" : zoom >= 1 ? "whole wheel" : `${Math.round(zoom * 100)}% of the way out`;

interface SliderProps {
  readonly id: string;
  readonly label: string;
  readonly range: Range;
  readonly value: number;
  /** What a screen reader announces. */
  readonly text: string;
  /** What the slider shows beside it, if shorter than `text`. */
  readonly shown?: string;
  readonly describedBy?: string;
  readonly onInput: (value: number) => void;
}

function Slider({ id, label, range, value, text, shown, describedBy, onInput }: SliderProps) {
  return (
    <div class="setting">
      <label for={id}>{label}</label>
      <input
        id={id}
        class="slider"
        type="range"
        min={range.min}
        max={range.max}
        step={range.step}
        value={value}
        aria-valuetext={text}
        {...(describedBy === undefined ? {} : { "aria-describedby": describedBy })}
        onInput={(event) => onInput(Number((event.currentTarget as HTMLInputElement).value))}
      />
      <output for={id} aria-hidden="true">
        {shown ?? text}
      </output>
    </div>
  );
}

const KEYS: readonly { key: keyof PartLook; label: string }[] = [
  { key: "width", label: "Thickness" },
  { key: "brightness", label: "Brightness" },
];

function PartSettings({ part, look }: { part: LookPart; look: Signal<Look> }) {
  const spec = LOOK_SPECS[part];
  const values = look.value.parts[part];
  const describedBy = `${SETTINGS_ID}-${part}-about`;
  return (
    <fieldset class="setting-group">
      <legend>{spec.label}</legend>
      <p id={describedBy} class="setting-about">
        {spec.description}
      </p>
      {KEYS.map(({ key, label }) => (
        <Slider
          key={key}
          id={`${SETTINGS_ID}-${part}-${key}`}
          label={label}
          range={spec[key]}
          value={values[key]}
          text={multiple(values[key])}
          describedBy={describedBy}
          onInput={(value) => {
            look.value = withPart(look.value, part, key, value);
          }}
        />
      ))}
    </fieldset>
  );
}

export interface SettingsProps {
  readonly open: Signal<boolean>;
  readonly look: Signal<Look>;
}

export function Settings({ open, look }: SettingsProps) {
  const panel = useRef<HTMLElement>(null);
  // Escape inside the menu closes it and gives focus back to its button.
  useEffect(() => {
    const element = panel.current;
    if (element === null) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      open.value = false;
      document.querySelector<HTMLElement>(`[aria-controls="${SETTINGS_ID}"]`)?.focus();
    };
    element.addEventListener("keydown", onKey);
    return () => element.removeEventListener("keydown", onKey);
  });
  const zoom = look.value.zoom;
  return (
    <section
      ref={panel}
      id={SETTINGS_ID}
      class="settings"
      aria-label="Stage settings"
      hidden={!open.value}
    >
      <div class="settings-header">
        <h2>Settings</h2>
        <button
          type="button"
          class="toggle"
          onClick={() => {
            open.value = false;
          }}
        >
          Close
        </button>
      </div>
      <fieldset class="setting-group">
        <legend>View</legend>
        <div class="setting-presets">
          <button
            type="button"
            class="toggle"
            aria-pressed={zoom === ZOOM_RANGE.min}
            onClick={() => {
              look.value = clampLook({ ...look.value, zoom: ZOOM_RANGE.min });
            }}
          >
            Arc
          </button>
          <button
            type="button"
            class="toggle"
            aria-pressed={zoom === ZOOM_RANGE.max}
            onClick={() => {
              look.value = clampLook({ ...look.value, zoom: ZOOM_RANGE.max });
            }}
          >
            Whole wheel
          </button>
        </div>
        <Slider
          id={`${SETTINGS_ID}-zoom`}
          label="Zoom out"
          range={ZOOM_RANGE}
          value={zoom}
          text={zoomText(zoom)}
          shown={`${Math.round(zoom * 100)}%`}
          onInput={(value) => {
            look.value = clampLook({ ...look.value, zoom: value });
          }}
        />
      </fieldset>
      {LOOK_PARTS.map((part) => (
        <PartSettings key={part} part={part} look={look} />
      ))}
      <p class="setting-about">
        Strands and lines outside the wheel stay below the flash threshold: their brightness only
        goes down from the default.
      </p>
      <button
        type="button"
        class="toggle"
        disabled={sameLook(look.value, DEFAULT_LOOK)}
        onClick={() => {
          look.value = DEFAULT_LOOK;
        }}
      >
        Reset to defaults
      </button>
    </section>
  );
}
