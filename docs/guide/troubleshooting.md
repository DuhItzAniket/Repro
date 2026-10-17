# Troubleshooting

Start with `repro doctor`: it checks Python, SQLite, git, uv, Docker, the isolation runs will
reach, the data directory, the run root, the cockpit and, on Windows, long paths. Each problem
line says what to do.

A run that cannot check something does not fail silently: the card lists it under **Missing**,
with what would resolve it. [The failure catalogue](../FAILURES.md) lists every such failure,
what the card says, and its fix. The problems below come before or around a run.

## Installing and starting
**`repro` is not found after `uv tool install`.** uv's tool directory is not on your `PATH`. Run
`uv tool update-shell`, then open a new terminal.

**`repro doctor` exits 1.** A required check failed (`fail`): Python, SQLite, git, or the data
directory. Its line says what is missing. Warnings (`warn`) never stop a run.

**`cannot listen on 127.0.0.1:8780`.** Another program, or another Repro, uses the port. Pass
`--port` with another one.

**`… is not a loopback address`.** The cockpit listens on 127.0.0.1 or ::1 only. Its session
token would cross the network in clear text.

## The cockpit
**It says "This engine needs its session token".** The page was opened without the token, or
with the token of an earlier server: each server makes its own. Open the address `repro`
printed, which ends in `#token=…`. Restarting `repro run`, `serve` or `replay` gives a new one.

**`repro run` says the cockpit is not built.** You are running from a checkout without a build.
Run `pnpm build`, or install a release, whose wheel carries the cockpit. The run itself is not
affected: `repro export` gives its card.

**The cockpit stays still in a background tab.** Browsers pause animation in hidden tabs; the
run carries on, and the cockpit catches up when the tab is shown.

## Docker and isolation
**`the sandbox could not start`.** Docker was asked for (`sandbox = "docker"`) but is not
running or not installed. Start Docker Desktop (or the Docker service), or run in a contained
process: `REPRO_SANDBOX=process`. With the default, `auto`, Repro uses Docker only when it
answers.

**`Docker has no runtime 'runsc'`.** `docker_runtime = "runsc"` asks for gVisor, which is not
installed as Docker's runtime. Install it as [gVisor's guide](https://gvisor.dev/docs/user_guide/install/)
says (`runsc install`), or unset `docker_runtime` for L3. gVisor runs on Linux only.

**The card says `network: detected-only`.** The run was in a contained process (L2): network
attempts were recorded, not blocked. Install Docker for L3, where the network is cut off.

**Windows: "long paths are off".** Paths over 260 characters can fail in Python and its tools.
Enable `LongPathsEnabled` (Group Policy or the registry; needs an administrator), or keep the
run root short (`REPRO_RUN_ROOT`). Repro passes `core.longpaths=true` to git itself.

## The run
**`environment_failed`: the project's install failed.** Repro installs dependencies from the
package index, from wheels only, and builds the project itself offline in the sandbox. A
dependency with no wheel, a requirement that points elsewhere (a URL, a path, a git
repository), or a build that needs the network cannot be installed.

**`run_incomplete`: a test run ended early.** The run stopped before pytest finished: the
suite could not start (a `conftest.py` or a plugin that does not import), the interpreter
crashed, or the process was killed. The detail gives the exit status and ends with the line of
the run's output that names its error. Run that side's tests yourself to see the rest. To tell
the project from Repro's sandbox, run once with `REPRO_SANDBOX=process`: if the tests run
there, the problem is the container's.

**`collection_error`: a test module could not be imported.** Its tests did not run on that side,
and the detail gives the line that names the error. When the error comes from a test
dependency (an old pin that does not work on Python 3.13, which Repro runs the tests on, say),
update the project's test requirements; an old commit keeps its pins, so the error stays on
its cards.

**`no test was selected`, or `no_covering_test`.** No test reaches the changed code. Repro picks
tests by what they ran on base, so a change no test exercises cannot be checked. Add a test
that calls it.

**`run_incomplete` past its limit, or `memory_limit`.** A test run reached its limit: 900 s and
4096 MiB by default (`test_timeout_s`, `memory_limit_mb`). If the change is meant to be slower
or larger, raise the limit; otherwise the change is the cause, and the card says which side
reached it.

**A run is slow the first time.** The first run builds both sides' environments and a map of
which test runs which code. The next run of a change on the same base reuses both.

## Agents
**Agents are on but no claim is read.** Claims come from `--pr-title` and `--pr-body`
(or `--pr-file`), else from the commit messages. A change described nowhere has none.

**`agent_failed`.** A model call failed, timed out or reached the run's budget
(`agent_budget_usd`, US$2 by default). The deterministic part of the card still stands; the
claims it could not judge stay unsupported.

## Logs and data
Logs go to stderr, as JSON lines. `--log-format text` is easier to read, and `--log-level`
chooses how much is shown (`debug`, `info`, `warning`, `error`). Both are options of `repro`
itself, so they come before the command: `repro --log-format text run …`. The cockpit server's
own lines are logged the same way. Credentials, the session token included, and your home
directory are scrubbed from the logs.

What Repro keeps, and where:
- **Runs, test maps and environments** (for the contained process): the data directory,
  `~/.repro` (`%USERPROFILE%\.repro` on Windows), or `REPRO_DATA_DIR`.
- **Scratch copies of the code**, removed after each run: the run root, `%LOCALAPPDATA%\repro\r`
  on Windows and `<data directory>/r` elsewhere, or `REPRO_RUN_ROOT`. `repro doctor` shows both.
- **With Docker:** the sandbox image (`repro-sandbox:<digest>`) and the environments' volumes
  (`repro-env-…`).

To start afresh, delete the data directory and, with Docker, those volumes and the image
(`docker volume rm`, `docker image rm`).

## Settings you may need
Each is an environment variable. Every setting can also go in `config.toml` in the data
directory, under its name in [the engine's README](../../engine/README.md#settings), which lists
them all.

| Variable | What it sets | Default |
|---|---|---|
| `REPRO_SANDBOX` | Where the target's code runs: `docker`, `process`, or `auto` | `auto`: Docker when it answers |
| `REPRO_DOCKER_RUNTIME` | `runsc` runs containers under gVisor (L4, Linux only) | Docker's default |
| `REPRO_TEST_TIMEOUT_S` | Each test run's time limit, in seconds | `900` |
| `REPRO_MEMORY_LIMIT_MB` | Each test run's memory limit | `4096` |
| `REPRO_DATA_DIR`, `REPRO_RUN_ROOT` | Where runs and scratch copies go | above |
| `REPRO_AGENTS` | `claude`, `groq` or `openai` to judge claims | `off` |
| `REPRO_LOG_FORMAT`, `REPRO_LOG_LEVEL` | The logs: `json` or `text`, and how much | `json`, `info` |
