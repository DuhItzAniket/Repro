import type { HeaderCounters } from "../model/cockpit";
import type { Rect } from "./layout";
import type { ShellView, StageSegment } from "./view";

const COUNTERS: readonly { key: keyof HeaderCounters; label: string }[] = [
  { key: "claims", label: "Claims" },
  { key: "agents", label: "Agents" },
  { key: "files", label: "Files" },
  { key: "checks", label: "Checks" },
  { key: "flagged", label: "Flagged" },
];

export const rectStyle = (rect: Rect): Record<string, string> => ({
  left: `${rect.x}px`,
  top: `${rect.y}px`,
  width: `${rect.w}px`,
  height: `${rect.h}px`,
});

export function ProgressBar({ stages }: { stages: readonly StageSegment[] }) {
  return (
    <ol class="progress" aria-label="Pipeline stages">
      {stages.map((stage) => (
        <li
          key={stage.name}
          class="segment"
          data-state={stage.state}
          data-outcome={stage.outcome ?? undefined}
          title={`${stage.name}: ${stage.state}`}
        >
          <span class="visually-hidden">{`${stage.name}: ${stage.state}`}</span>
        </li>
      ))}
    </ol>
  );
}

export function Header({
  rect,
  view,
  onCard,
}: {
  rect: Rect;
  view: ShellView;
  /** Opens the Reproduction Card (F05); the button shows once the run has a card status. */
  onCard?: () => void;
}) {
  const counters = view.counters.value;
  const run = view.run.value;
  const status = view.status.value;
  return (
    <header class="header" style={rectStyle(rect)}>
      <div class="brand">
        <div class="brand-line">
          <h1 class="title">Repro</h1>
          {run.cardStatus !== null && onCard !== undefined && (
            <button
              type="button"
              class="card-status"
              data-status={run.cardStatus}
              aria-label={`card ${run.cardStatus}: open the Reproduction Card`}
              onClick={onCard}
            >
              {`card ${run.cardStatus}`}
            </button>
          )}
        </div>
        <p class="subtitle">
          agent changes → reproduced evidence
          {run.repo !== null && (
            <span class="run">{` · ${run.repo}${run.pr === null ? "" : ` ${run.pr}`}`}</span>
          )}
          {status !== null && <span class="status-line">{` · ${status}`}</span>}
        </p>
      </div>
      <dl class="counters">
        {COUNTERS.map(({ key, label }) => (
          <div
            key={key}
            class="counter"
            data-alert={key === "flagged" && counters.flagged > 0 ? "true" : undefined}
          >
            <dt>{label}</dt>
            <dd>{counters[key]}</dd>
          </div>
        ))}
      </dl>
      <ProgressBar stages={view.stages.value} />
    </header>
  );
}
