# C01 — Engine skeleton, configuration & CLI

| | |
|---|---|
| **Stage** | C — Engine core & live stream |
| **Status** | in progress |
| **Depends on** | A05 |
| **Branch / PR** | `phase/C01-engine-skeleton` · PR pending |
| **Started / finished** | 2026-10-14 / — |

## Objective
The engine has its command surface, settings, structured logs and Windows-safe data paths, and
`repro doctor` tells a user, on Windows or Linux, whether their machine can run Repro and what
to fix if not.

## Scope
- **CLI** (`repro`, Typer): `doctor` works. `run`, `replay`, `serve` and `export` exist with the
  options their phases need, and exit with status 2 and a message naming the phase that brings
  them, so nothing pretends to work.
- **Settings** (`repro.config`): a frozen, validated `Settings` model. Precedence: command-line
  flags, then `REPRO_*` environment variables, then the TOML file (`REPRO_CONFIG`, else
  `config.toml` in the data directory), then defaults. Unknown keys and invalid values are errors
  that name their source (flag, variable or file and key). Fields: `data_dir`, `run_root`,
  `log_level`, `log_format`, `concurrency`, `sandbox`.
- **Paths** (`repro.paths`): defaults per platform, computed purely from the environment so both
  flavours are tested on any OS:
  - data directory: `~/.repro` (`%USERPROFILE%\.repro` on Windows), holding `repro.db`, `runs/`
    (artifacts, C02), `logs/` and `config.toml` (ARCHITECTURE §11, §12);
  - run root for scratch snapshots and worktrees: `%LOCALAPPDATA%\repro\r` on Windows, kept
    short (ARCHITECTURE §14), and `<data dir>/r` elsewhere. A run's scratch directory is the
    root plus 8 characters of its ID.
- **Structured logging** (`repro.logs`): JSON lines on stderr by default (`ts` in UTC with
  milliseconds, `level`, `logger`, `msg`, extra fields, exception type and traceback); a text
  format for people. Fields whose names look like credentials are redacted. stdout stays free
  for command output.
- **`repro doctor`**: checks, each `ok`, `warn` or `fail` with a hint:
  - Python running the engine (≥ 3.12, required: `sys.monitoring`);
  - git (≥ 2.40, required);
  - uv (≥ 0.13 ok, the toolchain baseline; anything older or missing is a warning, and below
    0.12.18 the hint names the Windows wheel path-traversal fix; it becomes required when
    Stage D provisions environments);
  - Docker: CLI, daemon, server OS and kernel (Linux containers; WSL2 on Windows). Missing or
    stopped is a warning: Repro then reports `isolation: process` (ADR-0004);
  - data directory writable (or creatable), without creating it;
  - run root length, and on Windows whether long paths are enabled.

  `--json` prints one machine-readable report. Exit status 1 when a required check fails.

## Out of scope
- The database, evidence and artifact stores (C02), the event bus and orchestrator (C03), the
  API (C04), git operations (C05) and analysis (C06–C07).
- Model and budget settings (Stage G), policy files (`repro.yml`, Stage F).

## Design notes
- Probes run fixed argument vectors through `subprocess` without a shell, with timeouts, and
  are injected, so every outcome (missing, old, malformed, timed out) is unit-tested without the
  tool installed. Doctor never changes the machine: it does not create the data directory and it
  only reads the Windows registry.
- The run-root warning threshold (80 characters) is a project choice: it leaves 180 of
  Windows' 260-character limit for paths inside a target repository when long paths are off.
- No new dependency: pydantic 2.14.1 is already in the lockfile (via `repro-events`), and TOML
  parsing uses the standard library (`tomllib`).

## Acceptance criteria
- [x] AC1 (roadmap): `repro doctor` reports git, uv, Python and Docker capabilities on Windows
      and Linux.
- [x] AC2: settings resolve with the documented precedence, and invalid configuration fails with
      a message naming its source.
- [x] AC3: default paths follow the platform rules (`%USERPROFILE%`, `%LOCALAPPDATA%`, `~`) and a
      run's scratch path stays within the length budget.
- [x] AC4: logs are one JSON object per line on stderr, in UTC, with credentials redacted.
- [x] AC5: unfinished commands fail clearly (exit 2, naming their phase).

## Test plan
| Criterion | Check |
|---|---|
| AC1 | unit tests with fake probes for every outcome; `test_doctor_runs_on_this_machine` (real tools) in CI on Ubuntu and Windows |
| AC2 | `test_config.py`: precedence, unknown keys, invalid values, malformed TOML |
| AC3 | `test_paths.py`: both platform flavours from injected environments |
| AC4 | `test_logs.py` |
| AC5 | `test_cli.py` |

---
*Filled in at the end of the phase:*

## What shipped
- `engine/src/repro/`: `paths.py`, `config/settings.py`, `logs.py`, `doctor.py`, and `cli.py`
  with `doctor` and the declared commands. The engine now depends on pydantic directly (already
  locked at 2.14.1 through `repro-events`).
- Tests: `test_paths.py` (11), `test_config.py` (15), `test_logs.py` (9), `test_doctor.py` (48,
  one POSIX-only), `test_cli.py` (+10): pytest 497 → 590 (589 pass and 1 skips on Windows).

## Evidence
- `repro doctor` on the development machine (Windows 11, x64): every check ok, including Docker
  29.8.2 with Linux containers on the WSL2 kernel and long paths enabled.
- `test_doctor_runs_on_this_machine` runs the real `repro doctor --json` against the installed
  tools in CI on Ubuntu and Windows (run linked in the PR).
- Ruff, ruff format, mypy (strict) and the licence allow-list pass.

## Deviations from spec
- The run root's length budget applies on Windows only: other platforms have no 260-character
  limit, and Ruff rightly rejected suggesting a world-writable `/tmp` path as the fix.

## Known gaps
- `run`, `replay`, `serve` and `export` are declared only (C03, C04, C08, F05).
- uv becomes a required check when Stage D provisions environments (D03).

## Dependencies added
None.

## Research notes
