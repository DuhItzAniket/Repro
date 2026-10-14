# B15 — Stage settings and the whole wheel

| | |
|---|---|
| **Stage** | B — Cockpit on fixtures |
| **Status** | in progress |
| **Depends on** | B14 |
| **Branch / PR** | `phase/B15-stage-settings` · [#27](https://github.com/DuhItzAniket/Repro/pull/27) |
| **Started / finished** | 2026-10-14 / — |

## Objective
A viewer can tune the stage's look (the thickness and brightness of each kind of line) and see
the whole wheel, not only the reference's arc, with the run's nodes spread over the whole disc.

## Why this phase exists
The owner's seventh review of B14 asked for three things beyond reference parity: sliders in a
settings menu, so users of the finished product can adjust the look themselves; the nodes spread
further, to see how the simulation reads; and a way to see the other parts of the wheel, or all
of it. They extend Stage B before its gate closes.

## Scope
- **Look** (`stage/look.ts`): per part (strands, bullets, mesh, nodes, lines outside), a width
  and a brightness multiple, each within a range; a zoom from the arc (0) to the whole wheel (1).
  `clampLook` is the only way a look enters the app, from a slider or from storage.
- **Applied by the shader**: each segment layer names its part; the host sets two uniforms per
  layer (`uWidth`, `uAlpha`). The layers write the same instances whatever the look, so
  render-model pins do not depend on it and sliders cost no re-upload.
- **Flash safety by range** (ADR-0011 B15 note): the strands and lines outside are MAX-blended
  at `DIM_MAX` and not counted, so their brightness can only go down (×0.2–×1), and the host
  never raises a MAX layer's alpha. The counted parts (bullets, mesh flares) may be brighter or
  wider: the governor counts their area at the chosen width (`strandArea`, `pinArea`, arc
  widths), and re-decides from the start when a width changes.
- **View** (`stage/camera.ts`): `viewRing` gives the ring for a zoom: the layout's arc at 0, the
  whole wheel centred and fitted with room for the lines outside at 1, and a smooth zoom between
  (geometric radius, linear centre). It replaces the frame's ring, so every layer, the governor,
  the hit tests and the callouts follow it. The mesh dims by `meshDensity` (√ of the radius
  ratio) as the same arcs crowd a smaller disc. The card atlas is mipmapped, so card text does
  not shimmer when drawn small.
- **Nodes over the whole disc** (`placeNode`): angle by rank in the simulation's order (the order
  the modules are spaced by, so a node sits near its module), distance from the centre by role
  (tests 0.18–0.78 of the rim, symbols 0.45–0.98), area-uniform within the band. Layout hash
  `repro-layout/5`.
- **Settings menu** (`shell/settings.tsx`): a Settings button in the transport opens a disclosure
  over the stage's lower right: View (Arc, Whole wheel, a zoom slider), a labelled thickness and
  brightness slider per part with its description, and Reset. Escape inside it closes it and
  returns focus to the button.
- **Persistence**: the look is kept per viewer in `localStorage` (`repro.look/1`), read through
  `clampLook`, removed at the default; missing or throwing storage falls back to the default.
  Test mode never reads it, so screenshots use the default unless a test sets a look.

## Out of scope
- Panning to a chosen part of the wheel: the ring turns every part past the arc in 24 s, and the
  whole-wheel view shows all of it at once. Revisit if users ask (no phase yet).
- Per-tint colour settings, and settings for the ring's cards, ticks and markers.
- Syncing a look across devices (it is a per-viewer, per-browser preference).

## Design notes
- A view is a ring geometry, not a camera transform on top of the stage: the static layers write
  only what is on the stage, and the governor decides which bunches may fire by where their
  sections are on the stage. Both must see the view the viewer sees.
- Brightness for the dim lines could have gone above `DIM_MAX` if the governor counted them when
  it did. That would make a slider change which bunches are drawn, so it was not done: their
  ceiling stays the flash-safe one.
- Whole-disc placement makes strands longer in the arc view: the nearest nodes that reach a
  function may be off the stage. The flash cap counts each bullet's whole path, so fewer bunches
  fit there (13 of 120 on the demo at ×1, against 20 after B14) and more in the whole wheel (71
  of 399). Spreading the nodes and seeing all of them were the owner's two requests; the arc
  view's sparser nodes are their cost, flagged for the owner.

## Acceptance criteria
- [x] AC1: every slider changes only the look, never which events draw: render-model pins at the
      default look are unaffected by it (the layers do not read it), and the governor's
      decisions change only with the widths it counts.
- [x] AC2: settings survive a reload, a reset restores the defaults, and malformed or blocked
      storage falls back to the defaults.
- [x] AC3: the dim lines' brightness stays at or under the flash ceiling at every setting, and the
      governor's bound holds in every view and at the widest widths.
- [x] AC4: the whole-wheel view shows every card and every node, with bunches and lines outside
      on sections all round the wheel.
- [x] AC5: the controls are keyboard-operable and labelled (axe: no serious or critical
      violations with the menu open).
- [ ] AC6: all tests and gates pass, in CI too; visual baselines regenerated and checked by eye.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `layers.test.ts` "writes the same instances whatever the viewer's brightness and uncounted widths"; `motion.test.ts` "counts wider bullets and arcs as more area, and re-decides when the widths change" |
| AC2 | `look.test.ts` "keeps a viewer's look across loads", "clamps what it reads", "falls back to the default when storage is missing or throws"; `settings.test.tsx` "resets to the defaults" |
| AC3 | `look.test.ts` "never lets the uncounted dim lines brighten past their flash-safe ceiling"; `motion.test.ts` "holds the cap in every view and at every width the viewer can choose"; the host clamps MAX layers' alpha (code review) |
| AC4 | `camera.test.ts`; `layers.test.ts` "draws the run's nodes on the stage as small circles: some in the arc, all in the whole wheel"; `force.test.ts` placement tests; visual `cockpit-whole-24500.png` |
| AC5 | `settings.test.tsx` (labels, descriptions, Escape returns focus); `transport.test.tsx` (aria-expanded, aria-controls); `a11y.test.tsx` axe with the menu open; visual `cockpit-settings-24500.png` |
| AC6 | CI on Ubuntu and Windows; `visual` job |

---
*Filled in at the end of the phase:*

## What shipped
- See Scope. Web tests 243 → 264 (look 7, camera 4, settings 5, transport 2, governor 2, the
  look leaving render models unchanged 1).

## Evidence
- Local: `pnpm lint`, `pnpm typecheck`, `pnpm test` (Vitest 264 web), `pnpm perf` (ratios p50
  0.018, p95 0.21 against the baseline's 0.0496 and 0.2749), size 195.9 kB of 300 kB, stage
  allocation 3.4 kB per frame at the stress burst (budget 40 kB).
- Bunches the cap admits (unit-test fixtures, 1440×900):

  | View | demo ×1 | demo ×16 | stress ×1 | stress ×16 |
  |---|---|---|---|---|
  | Arc (default) | 13 of 120 | 4 of 133 | 4 of 58 | 0 of 51 |
  | Halfway | 34 of 218 | 5 of 141 | 10 of 130 | 4 of 111 |
  | Whole wheel | 71 of 399 | 15 of 399 | 35 of 259 | 9 of 259 |

- Nodes on the stage in the demo: 6 of 47 in the arc view, 47 of 47 in the whole wheel.
- CI run and visual baselines: pending.

## Deviations from spec
- The roadmap's "every slider changes only the look" holds for which events draw at a given
  width; wider counted elements are bigger flashes, so the governor may admit fewer bunches at
  wider bullet or mesh widths. That is the flash bound working, not a change of what the run
  shows.

## Known gaps
- In the arc view, few of the run's nodes are on the stage now (6 of 47 in the demo), and at
  ×16 on the stress run no bunch fits the flash cap there. Owner decision: keep whole-disc
  placement, or bias placement towards the default view.

## Dependencies added
None.

## Research notes
`docs/paper/LOG.md`, 2026-10-14 · B15.
