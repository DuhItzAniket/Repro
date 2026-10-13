# A07 — Test-harness foundations & golden-log tooling

| | |
|---|---|
| **Stage** | A — Foundation |
| **Status** | done |
| **Depends on** | A05 |
| **Branch / PR** | `phase/A07-test-harness` · [#7](https://github.com/DuhItzAniket/Repro/pull/7) |
| **Started / finished** | 2026-10-13 / 2026-10-13 |

## Objective
Give later phases what they need to test deterministic behaviour across machines:
- property testing in both languages;
- event-log validation that enforces the log-level rules;
- normalised golden logs;
- reproducible fixture repositories.

## Scope
- Hypothesis (Python) with `dev`/`ci` profiles; fast-check (TypeScript).
- `repro-events validate` / `normalise` (JSONL logs) in `repro_events.log` and `repro_events.cli`.
- `golden` fixture and `--update-goldens` (root `conftest.py`).
- Fixture-repository builder and the first fixture (`honest-fix`) with its expectation file.

## Design notes
- **Log rules** (`validate_log`):
  - schema errors per event (field-precise, from A04);
  - one `run_id`;
  - `seq` = 1..n with no gaps;
  - unique ids;
  - `parent` points backwards;
  - the first event is `run.started`, and `run.finished`, if present, is last;
  - **evidence must be created before it is cited** (verdicts, invariant results, diff events).
    This is ground rule 1 checked mechanically on every log.
  - Backwards timestamps are a warning only, because `seq` is the order (ADR-0002).
- **Normalisation keeps logs schema-valid:**
  - event ids become synthetic ULIDs derived from `seq`;
  - evidence ids are numbered by first appearance, and run ids collapse to one;
  - `ts` = 2000-01-01T00:00:00.000Z + `seq` ms;
  - `duration_ms` → 0 and `producer` → `repro/0.0.0`;
  - output is canonical JSONL (sorted keys, compact, LF).

  The normalised log can still be validated and replayed. Normalisation is idempotent.
- **Fixture repos are Python data, not files on disk:** buggy fixture code is never
  collected, linted or type-checked as Repro's own. Fixed identities and dates, LF content, and
  `GIT_CONFIG_GLOBAL` pointed at an empty file make commit SHAs **platform-independent**, so
  the test pins them.
- Expectations use TOML (stdlib `tomllib`) instead of the YAML mentioned in TEST_STRATEGY, which
  avoids a YAML dependency before F01 chooses one. TEST_STRATEGY is updated.

## Acceptance criteria
- [x] AC1: A sample log validates (`test_sample_log_is_valid`; `repro-events validate` exits 0).
- [x] AC2: It normalises to a stable golden file (`test_normalised_sample_matches_golden`), and the
      normalised log is still valid and idempotent.
- [x] AC3: The same golden passes on Windows and Linux, including line endings and paths (the
      CI `test` matrix runs it on both; the golden helper compares with LF everywhere).

## Evidence
| Area | Tests |
|---|---|
| Log reading | `test_read_log_reports_bad_lines_and_accepts_crlf` (blank, non-JSON, non-object lines; CRLF accepted) |
| Log rules | seq gap from removing **any** middle event (Hypothesis); evidence cited before creation; first event; duplicate id; forward `parent`; mixed `run_id`; backwards timestamp only warns |
| Normalisation | golden file; still valid; idempotent; **property**: random id remapping, timestamp shifts, durations and producer versions all give the identical normalised log (Hypothesis) |
| CLI | `validate` exits 0 on the sample and 1 on a log with a missing line; `normalise -o` |
| Fixture repos | reproducible builds; **pinned SHAs** (`fe755e4…` base, `44c5e14…` head) on all OSes; LF blobs; head changes only `pkg/dates.py`; the fixture's tests **fail on base and pass on head** |
| TS properties (fast-check) | validity is independent of property order; unknown kinds, `seq` < 1 or non-integer, and extra envelope properties are always rejected |

Totals: pytest **493 passed**; Vitest **48 passed** (web 1, events 47). Ruff, mypy (26 files),
Biome and tsc are clean.

## Deviations from spec
- Expectation files are TOML, not YAML (see Design notes).
- The builder is named `repo_builder.py`, with specs in `specs.py`, instead of a single
  `build_repos.py`. The behaviour is the same and the docs are updated.

## Known gaps
- Only the `honest-fix` fixture exists. Each later phase adds the fixtures it asserts
  (TEST_STRATEGY §3 table).
- `repro-events validate` does not yet check stage ordering. Validating that against
  `stage.started`/`stage.finished` pairs is left for C03, when the orchestrator defines it.

## Dependencies added
| Package | Version | Licence | Why |
|---|---|---|---|
| hypothesis (dev) | 6.169.0 | MPL-2.0 | Property-based tests (Python) |
| fast-check (dev) | 4.10.2 | MIT | Property-based tests (TypeScript) |

## Research notes
The "evidence before citation" log rule and the normalised, still-valid log format support the
replayability claim (C5) and RQ4 (grounding).
