# @repro/web — the cockpit

A live, replayable projection of one run's event stream (ARCHITECTURE §13, DESIGN.md).

| Path | What it holds |
|---|---|
| `src/model/` | The UI's data layer: `EventStore`, indexes, projections, snapshot folding and the presentation clock. Pure TypeScript, no DOM, tested in Node |
| `src/model/projections/` | Pure reducers: `run` (meta, stages), `summary` (counters), `checks` (ADR-0015), `claims`, `agents` |
| `src/shell/` | Preact shell: `computeLayout` (all geometry), header and progress bar, panel frames, the signals bridge (`view.ts`) and the frame loop |
| `src/stage/` | WebGL stage: `StageHost` (the only three.js user), the `StageLayer` contract, instance buffers and render-model hashing, the segment primitive and its GLSL, adaptive DPR, frame statistics, the perf HUD (`?hud`) |
| `src/stage/web/` | The dependency web: layout input and hash, the d3-force layout and its worker, `LayoutService`, and the edge, marker and bundle layers |
| `src/stage/ring/` | The ring: card content from events, closed-form rotation and snaps, the atlas (packing, drawing, worker, service), and the card and tick layers |
| `src/stage/streams/` | Event streams (streak style, lanes, layer) and the callout overlay |
| `src/panels/` | Canvas 2D panels: the `Panel` contract and `PanelHost` (draws only when the version changes), a recording context for golden tests, and the feed, execution, workspace and behaviour panels |
| `src/bench/` | The stress benchmark (`/bench.html`, dev server) and its proxy layers; results in `docs/perf/` |
| `src/styles/` | DESIGN.md tokens and shell styles |
| `src/data/` | Loading a recorded log (the fixtures in Stage B; `?log=stress` picks the stress run) |
| `fixtures/` | Generated reference and stress event logs (`pnpm fixtures`) |

## The model in one paragraph

Events are appended to the `EventStore` in `seq` order (duplicates ignored, gaps stop
ingestion). A `Folder` folds the combined cockpit projection over the store and keeps a snapshot
every 256 events, so `stateAt(cursor)` costs at most one snapshot clone plus 256 events (about
0.25 ms on the 18.5k-event stress log). The `PresentationClock` turns wall time into
presentation time `t` (replay ×0.5/×1/×4/×16, live, global pause), and `store.cursorAt(t)`
turns `t` into a fold cursor. Views read selectors such as `headerCounters` and `indexFooter`.
They never fold events themselves.

```ts
import { CockpitModel, headerCounters } from "./src/model/cockpit";

const model = new CockpitModel();
model.ingest(events); // parsed JSON objects
const { state } = model.stateAtTime(12_000); // 12 s into the run
headerCounters(state); // { claims, agents, files, checks, flagged }
```

## Commands

```
pnpm --filter @repro/web dev        # Vite dev server
pnpm --filter @repro/web test       # Vitest (model unit and property tests)
pnpm --filter @repro/web typecheck
```
