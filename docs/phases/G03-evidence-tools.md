# G03 — Read-only evidence tools

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | done |
| **Depends on** | G01, F04 |
| **Branch / PR** | `phase/G03-evidence-tools` · [#62](https://github.com/DuhItzAniket/Repro/pull/62) |
| **Started / finished** | 2026-10-16 / 2026-10-16 |

## Objective
Give agents what they may read, and nothing else: the run's citable evidence and the change's
files, through four read-only tools with size caps, a rendering that is the same in every run
and on every machine, checked paths, and every piece of the target's text delimited as data.

## Scope
- **Tools** (`repro.agents.tools.EvidenceTools`): `list_evidence` (optionally about a file,
  symbol or test), `get_evidence` (one item in full), `read_snippet` (up to 80 lines of a file
  on base or head), `get_diff` (a file's diff, up to 160 lines). Every input checked in the
  handler, every output capped, refusals worded for the model to correct.
- **Rendering** (`repro.agents.evidence.EvidenceView`): from the run's own log; items in
  content order; per type, only the fields that describe the finding; the engine's
  bookkeeping (`environment`, `policy`) not shown; relevance to a file, symbol or test (a
  symbol's file from `symbol.changed`, a test's from its ID).
- **Sources** (`repro.agents.sources.RepoSources`): files and diffs read from the commits' git
  objects through the hardened `Git`, never from the snapshots; paths checked before git sees
  them; regular files only, up to 1 MB.
- **Untrusted content** (`repro.agents.untrusted`): the target's text in
  `<untrusted_content kind=…>` blocks it cannot close; made portable (LF, `~` for the home
  directory, `/` in pytest's file locations).
- **The `injection` fixture**: honest-fix with instructions to the reviewers planted in the PR
  text, a code comment and a test's assertion message (TEST_STRATEGY §3).
- Cassettes (G02) are also written with the home directory as `~`.

## Out of scope
- The prompts that use the tools (G04–G08); the verdict half of the acceptance criterion,
  which needs reviewers (G05).

## Design notes
- **Rendering is the text quotes are checked against** (G05), so it must be a function of the
  evidence alone. Two things in real logs broke that and are handled here: evidence IDs follow
  creation time, which varies with how jobs interleave (items are ordered by type, targets and
  summary instead); and pytest prints locations with the platform's separator
  (`tests\test_dates.py:13` on Windows). Timings, process IDs, digests and artifacts vary
  between runs of the same change and are not shown; a performance ratio is shown to one
  decimal. A run whose rendered evidence differs is a different call to a cassette.
- **Git objects, not snapshots.** The target's tests ran in the snapshots and could rewrite
  them; a commit cannot change. `ls-tree` gives the entry's mode, so a symlink or submodule is
  refused rather than followed, and `--no-ext-diff --no-textconv` keep the repository's diff
  drivers from running.
- **Delimiting changes only the delimiters.** Escaping all markup would turn `a < b` in code
  into `a &lt; b`; only `<untrusted_` and `</untrusted_` are written as `&lt;…`, which is
  enough for no text to end its block.
- **Names, not A/B.** ARCHITECTURE §10.4 asked for sides labelled A/B with a legend. The
  evidence summaries are the engine's own words, written with base and head, and the claims
  speak of the change; the tools keep `base` and `head`, and position bias is controlled by
  the order-swap pass (G08).

## Acceptance criteria
- [x] AC1 (roadmap): prompt-injection fixtures in PR text and code comments do not change tool
  behaviour. (Their effect on verdicts is checked in G05, once there are verdicts.)
- [x] AC2: `list_evidence`, `get_evidence`, `read_snippet`, `get_diff` with size caps,
  rendering and path normalisation; untrusted-content delimiting.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_planted_instructions_do_not_change_what_a_tool_does[…]` (injection vs honest-fix: identical outside the blocks, one closing tag per block, the same output twice), `test_planted_evidence_text_stays_in_its_block`, `test_no_text_leaves_its_block` (property), `test_a_diff_is_git_s_own_and_runs_nothing` (with its control); the injection fixture end to end gives honest-fix's card |
| AC2 | `test_agents_tools.py`, `test_agents_evidence.py`, `test_agents_sources.py`, `test_agents_untrusted.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.tools` (`EvidenceTools`, `ToolInputError`), `repro.agents.evidence`
  (`EvidenceView`, `Item`), `repro.agents.sources` (`RepoSources`, `checked_path`,
  `SourceError`), `repro.agents.untrusted` (`block`, `neutralise`, `portable`, `without_home`).
- The `injection` fixture (spec, expectations, golden card; end to end in `test_run_stage`).
- Cassettes written with `~` for the home directory.
- Tests: `test_agents_tools.py` (25), `test_agents_sources.py` (37), `test_agents_evidence.py`
  (11), `test_agents_untrusted.py` (14), one more in `test_agents_cassette.py`.

## Evidence
- On real run logs (honest-fix, silent-change): the four tools give what the tests expect;
  a pytest message's `tests\test_dates.py:13` renders as `tests/test_dates.py:13`.
- The injection fixture's tool outputs equal honest-fix's outside the untrusted blocks (line
  counts aside: its head file has one more line), and its card equals honest-fix's but for the
  commit SHAs.
- A diff driver planted in the repository's own attributes runs on a plain `git diff` (the
  control) and not through `get_diff`.
- Full suite (Windows, Docker stopped): 1649 passed, 13 skipped.
- CI run: linked in the PR (#62).

## Deviations from spec
- ARCHITECTURE §10.4: evidence is rendered in content order, not ID order (IDs follow creation
  time, which varies), and sides are named `base` and `head` rather than A/B.
- `list_evidence` takes an optional file, symbol or test rather than a claim ID: claims arrive
  in G04, and G05 lists each claim's evidence with the same relevance rule.

## Known gaps
- The tools' effect on verdicts with the injection fixture is G05's to show.
- `read_snippet` and `get_diff` read text as UTF-8 with replacement; a binary file reads as
  replacement characters rather than being refused.

## Dependencies added
None.

## Research notes
- research/04, recommendation A.2 (the four tools, read-only, from Repro's own store, with
  server-side path normalisation) and A.3 (delimited untrusted PR text).
- git's diff drivers and `$GIT_DIR/info/attributes` (git-diff(1), gitattributes(5)): that
  the repository's own attributes file configures a driver for every diff, and that
  `--no-ext-diff --no-textconv` keeps it from running, is shown by the control and the check
  in `test_a_diff_is_git_s_own_and_runs_nothing`.
