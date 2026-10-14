/**
 * Replay transport (B10; DESIGN.md "Motion", ADR-0011): play/pause, ×0.5/×1/×4/×16, a scrubber,
 * jump to live, and a reduce-motion toggle. The clock is the only state; this component shows it
 * and sends commands. Space pauses and resumes everything from anywhere except an interactive
 * control, which handles Space itself (WCAG 2.2.2).
 */
import { type Signal, signal } from "@preact/signals";
import { type ClockMode, type PresentationClock, SPEEDS, type Speed } from "../model/clock";
import { rectStyle } from "./header";
import type { Rect } from "./layout";
import { SETTINGS_ID } from "./settings";

/** The scrubber's and readout's resolution in run time (ms). */
export const TIME_STEP = 100;

export interface TransportState {
  readonly t: number;
  readonly end: number;
  readonly speed: Speed;
  readonly paused: boolean;
  readonly mode: ClockMode;
}

export type TransportClock = Pick<
  PresentationClock,
  "status" | "toggle" | "setSpeed" | "seek" | "goLive"
>;

export function createTransportState(): Signal<TransportState> {
  return signal({ t: 0, end: 0, speed: 1, paused: true, mode: "replay" });
}

const step = (ms: number): number => Math.floor(ms / TIME_STEP) * TIME_STEP;

/**
 * Copies the clock's status into `state`, at TIME_STEP resolution, writing only on a change, so
 * the strip re-renders when what it shows changes, not on every frame.
 */
export function syncTransport(state: Signal<TransportState>, clock: TransportClock): void {
  const status = clock.status();
  const t = step(status.t);
  const end = step(status.end);
  const current = state.value;
  if (
    current.t !== t ||
    current.end !== end ||
    current.speed !== status.speed ||
    current.paused !== status.paused ||
    current.mode !== status.mode
  ) {
    state.value = { t, end, speed: status.speed, paused: status.paused, mode: status.mode };
  }
}

/** `m:ss.s` for a run time in ms. */
export function formatTime(ms: number): string {
  const tenths = Math.floor(Math.max(0, ms) / 100);
  const minutes = Math.floor(tenths / 600);
  const seconds = (tenths % 600) / 10;
  return `${minutes}:${seconds.toFixed(1).padStart(4, "0")}`;
}

const speedLabel = (speed: Speed): string => `×${speed}`;

const INTERACTIVE =
  "button, input, select, textarea, a[href], summary, [contenteditable], [role=button]";

/**
 * Global pause (Space). Returns whether it handled the event. Interactive controls keep Space
 * for themselves (a focused button is pressed by it), and held-down repeats are ignored.
 */
export function spaceToPause(
  event: KeyboardEvent,
  clock: Pick<PresentationClock, "toggle">,
): boolean {
  if (event.key !== " " || event.repeat || event.altKey || event.ctrlKey || event.metaKey)
    return false;
  const target = event.target;
  if (target instanceof Element && target.closest(INTERACTIVE) !== null) return false;
  event.preventDefault();
  clock.toggle();
  return true;
}

export interface TransportProps {
  readonly rect: Rect;
  readonly state: Signal<TransportState>;
  readonly clock: TransportClock;
  /** Reduced motion: follows `prefers-reduced-motion` until toggled here. */
  readonly reduced: Signal<boolean>;
  /** Called after any command, so the strip reflects it before the next frame. */
  readonly onCommand?: () => void;
  /** Whether the stage settings menu is open (B15); no Settings button without it. */
  readonly settings?: Signal<boolean>;
}

export function Transport({ rect, state, clock, reduced, onCommand, settings }: TransportProps) {
  const s = state.value;
  const live = s.mode === "live";
  const run = (command: () => void) => () => {
    command();
    onCommand?.();
  };
  return (
    <fieldset class="transport" style={rectStyle(rect)}>
      <legend class="visually-hidden">Replay controls</legend>
      <button type="button" class="toggle play" onClick={run(() => clock.toggle())}>
        {s.paused ? "Play" : "Pause"}
      </button>
      <fieldset class="speeds">
        <legend class="visually-hidden">Replay speed</legend>
        {SPEEDS.map((speed) => (
          <button
            key={speed}
            type="button"
            class="toggle"
            aria-pressed={!live && s.speed === speed}
            onClick={run(() => clock.setSpeed(speed))}
          >
            {speedLabel(speed)}
          </button>
        ))}
      </fieldset>
      <input
        class="scrubber"
        type="range"
        min={0}
        max={Math.max(TIME_STEP, s.end)}
        step={TIME_STEP}
        value={s.t}
        aria-label="Run time"
        aria-valuetext={`${formatTime(s.t)} of ${formatTime(s.end)}`}
        onInput={(event) => {
          clock.seek(Number((event.currentTarget as HTMLInputElement).value));
          onCommand?.();
        }}
      />
      <span class="time" aria-hidden="true">
        {`${formatTime(s.t)} / ${formatTime(s.end)}`}
      </span>
      <button type="button" class="toggle" aria-pressed={live} onClick={run(() => clock.goLive())}>
        Live
      </button>
      <button
        type="button"
        class="toggle"
        aria-pressed={reduced.value}
        onClick={() => {
          reduced.value = !reduced.value;
        }}
      >
        Reduce motion
      </button>
      {settings !== undefined && (
        <button
          type="button"
          class="toggle"
          aria-expanded={settings.value}
          aria-controls={SETTINGS_ID}
          onClick={() => {
            settings.value = !settings.value;
          }}
        >
          Settings
        </button>
      )}
    </fieldset>
  );
}
