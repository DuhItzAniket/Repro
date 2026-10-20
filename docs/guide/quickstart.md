# Quickstart

From nothing to your first Reproduction Card, on Windows, Linux or macOS. Allow ten minutes.

## 1. What you need
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)**, which installs Repro and
  the Python it runs on (3.13).
- **git**.
- **Docker** (optional). With it, the code under test runs in a container with no network:
  isolation level L3. Without it, Repro runs the code in a contained process (memory, process
  and time limits) and records what it tried to do: level L2. The card always says which level
  a run reached.
- **Node.js** and the project's package manager (npm, pnpm or Yarn), for JavaScript and
  TypeScript projects only.

Repro checks Python projects tested with pytest. Their tests run on Python 3.13, whatever
versions the project supports, and the version is not a setting yet: a project, or an older
commit, whose test dependencies do not work on 3.13 shows `collection_error` or
`environment_failed` on its card.

It also checks JavaScript and TypeScript projects tested with Vitest or Jest (checked with
Vitest 4.1 and 5.0, and Jest 30), with an npm, pnpm or Yarn 1 lockfile. Their dependencies are
installed from the lockfile with lifecycle scripts off. With Docker, their tests run in a
container with Node and no network (L3); without it, on the machine's Node.js in a contained
process (L2). Their public API is read by a TypeScript compiler Repro fetches once, which needs
Node.js on the machine. The card lists what it could not check: timing, which is Python's
alone, and at L2 the network.

## 2. Install
Repro is on PyPI from v1.2.0, as `repro-engine`:

```
uv tool install --python 3.13 repro-engine
```

This installs the `repro` command. If your shell cannot find it, run `uv tool update-shell` and
open a new terminal.

**From a release's wheels.** Each GitHub release, from v1.0.0, attaches its two wheels. Replace
`<version>` with the release's version (for example `1.3.0`):

```
uv tool install --python 3.13 --from "repro-engine @ https://github.com/DuhItzAniket/Repro/releases/download/v<version>/repro_engine-<version>-py3-none-any.whl" --with "repro-events @ https://github.com/DuhItzAniket/Repro/releases/download/v<version>/repro_events-<version>-py3-none-any.whl" repro-engine
```

## 3. Check the machine
```
repro doctor
```
Each line is a check. `ok` and `warn` are fine. A `fail` names what to fix, and `repro doctor`
exits 1 until it is fixed. The `isolation` line says which level your runs will reach. The
`containment` line above it is the fallback, the contained process Repro uses when no container
can run (L2). The other lines say where Repro keeps its data, whether the cockpit is there and,
on Windows, whether long paths are on.

## 4. Run it on a change
In a git repository with a pytest, Vitest or Jest suite, choose two refs: the **base** (where
the change starts, often `main`) and the **head** (the change, often your branch). Any commit works as a
ref: a branch, a tag or a commit's hash. For a merge commit, its first parent (`<hash>^1`) is
the base.

```
repro run --repo . --base main --head my-branch
```

Repro reads the language from the repository's root: a Python project's files
(`pyproject.toml`, `setup.py`, `setup.cfg`, requirement files), else a `package.json`. A root
with both is taken as Python; `--language javascript` chooses the other.

Repro then:
1. takes a copy of each commit, without its `.git`;
2. builds an environment for each side, with the dependencies the tests need;
3. picks the tests that reach the changed code;
4. runs them on base twice and on head once, traced;
5. compares outcomes, behaviour, public API, dependencies and timings.

Among its log lines, it prints the cockpit's address:
`repro: cockpit at http://127.0.0.1:8780/?run=run_…#token=… (Ctrl+C to stop)`. Open it, or add
`--open` next time. The part after `#token=` is this server's key: the cockpit shows nothing
without it. When the run ends, its last line gives the run's ID and the card's status, for
example `repro: run_… completed (…): the card is FLAGGED`. The server keeps going until you
press Ctrl+C.

**Many runs at once.** The same server shows every run in its data directory at
`/fleet.html`, one tile each: running, then the card's status, refreshed every two seconds.
Open it in the tab that has the token (`http://127.0.0.1:8780/fleet.html` once the cockpit has
taken it). A tile opens its run in the cockpit.

**Or give it a pull request.** With a GitHub pull request's address, Repro reads its base,
head, title and description from GitHub and fetches its commits, a fork's included, into a
mirror of its own in the data directory:

```
repro run --pr https://github.com/<owner>/<repo>/pull/<number>
```

It compares the pull request's head with where it left its base branch (their merge base),
as GitHub's "Files changed" does. A public repository needs no token; a private one, or more
than 60 requests an hour, needs one in `GITHUB_TOKEN` or `GH_TOKEN`. To use a clone you
already have instead of the mirror, add `--repo <path>`: Repro fetches nothing into it.

To run without the cockpit, as in a script or CI, add `--no-serve`: `repro run` then exits
when the run ends, 0 if it completed and 1 if it did not, and the card is read with
`repro export` (step 6).

The first run on a project builds its environments and takes longest; with Docker, the first
run on a machine also builds Repro's sandbox image, which downloads its base image. The next
run of the same change reuses them.

## 5. Read the card
When the run ends, the cockpit's header shows the card's status, and its button opens the whole
card; `repro export run_<id> --format md` prints the same card in the terminal. Every card
answers three questions:
- **The status.** `VERIFIED`, `FLAGGED` or `UNVERIFIABLE`, and why.
- **What changed (the gap).** Each difference between base and head, and what became of it.
- **What could not be checked (the missing items)**, with what would resolve each.

[Reading a card](reading-a-card.md) explains every part.

## 6. Keep or share it
The run is stored on your machine, in Repro's data directory (`~/.repro`; on Windows
`%USERPROFILE%\.repro`, or `REPRO_DATA_DIR`), under the ID it printed (`run_…`, in the address
and the last line). [Logs and data](troubleshooting.md#logs-and-data) lists everything Repro
keeps, Docker's volumes included:

```
repro export run_<id> --format md        # Markdown, for a pull request or a person
repro export run_<id> --format json      # the card itself, canonical JSON
repro export run_<id> --format in-toto   # an in-toto attestation, for policies and signing
repro export run_<id> --format sarif     # SARIF 2.1.0, for code scanning
repro export run_<id> --format junit     # JUnit XML, for CI test reports
repro replay run_<id>                    # the run again in the cockpit, from the start
```

Each export assembles the card again from the run's log, and refuses one that differs from the
card the run published.

For a pull request, `repro report run_<id>` puts the card on it: a check run named `Repro` on
its head commit (VERIFIED `success`, FLAGGED `failure`, UNVERIFIABLE `neutral`), with
annotations at the changed code, and one comment that each report updates. The token
(`GITHUB_TOKEN` or `GH_TOKEN`) must be allowed to write check runs and pull request comments.

## 7. Claims (optional)
Without agents, Repro reports what changed but cannot say whether the change does what its
author says: every unexplained difference flags. With agents, it reads the pull request's
claims and has each judged against the evidence; a verdict that cites no evidence is rejected.
Agents are off by default and reach a model only when you turn them on:

```
REPRO_AGENTS=claude repro run --repo . --base main --head my-branch --pr-title "Fix the date parser" --pr-body "Naive datetimes are now read as UTC."
```

In PowerShell, set the variable first: `$env:REPRO_AGENTS = "claude"`. The backends (`claude`,
`groq`, `openai`), their keys and the budget are settings: see
[the settings](../../engine/README.md#settings).

## 8. A policy for your repository (optional)
A `repro.yml` at the repository's root sets invariants every change must keep, such as no
network access in tests, paths it must not touch, or a timing budget. Repro reads it from the
base side, so a change cannot weaken the policy it is judged by. See
[`repro.yml`](repro-yml.md).

## If something goes wrong
[Troubleshooting](troubleshooting.md) lists what can fail, what the card says, and what fixes it.
