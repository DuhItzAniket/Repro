# H06 — User documentation & demo

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | in progress |
| **Depends on** | H05 |
| **Branch / PR** | `phase/H06-docs` · PR pending |
| **Started / finished** | 2026-10-17 / — |

## Objective
Someone who has never seen Repro installs it, runs it on their own repository and reads the
card from the documentation alone. A contributor finds their way around the code from one page.

## Scope
- **The guide** (`docs/guide/`), linked from the README and `docs/README.md`:
  - the quickstart, from nothing to a first card;
  - reading a card: the status and its rules, the runs, the gap and its checks, invariants,
    every missing reason, conditions, replay;
  - the `repro.yml` reference: every invariant, `claims`, `missing`, and how the policy is
    read from base;
  - troubleshooting: installing, the cockpit, Docker and isolation, the run, agents, logs and
    data, and the settings a user is likely to need;
  - a page for contributors: the repository, a run through the code stage by stage, the event
    stream as the contract, common changes, the tests.
- **A recorded demo** (`docs/guide/demo.md`): one real run of the `silent-change` fixture, a
  change no test catches. Four stills of the cockpit, taken from the run's replay, and its
  card. `apps/web/gate/demo.spec.ts` makes the recording again (only with `REPRO_DEMO_OUT`).
- **Docs brought up to date**: CONTRIBUTING's table of CI jobs, the engine README's API
  paragraph (the session token).

## Out of scope
- **A video.** The demo is stills and the card, which a reader can check against the replay;
  the cockpit itself is the moving version (`repro replay`).
- **Hosted documentation.** The guide is Markdown in the repository, read on GitHub.

## Acceptance criteria
- [x] AC1 (roadmap): quickstart, `repro.yml` reference, how to read a card, troubleshooting,
  an overview for contributors, a recorded demo.
- [x] AC2 (roadmap): a reviewer unfamiliar with the project completes the quickstart from the
  docs alone. The second reviewer, given the corrected guide, completed it with no blocker
  (see "The dry runs"); the owner will also run it in person.
- [x] AC3: every relative link and anchor in the guide resolves.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | The pages in `docs/guide/`; each fact checked against the code it describes |
| AC2 | Two dry runs by a fresh agent given only the guide, against `pallets/itsdangerous`, from the release's wheels installed as the quickstart says, in a tool directory of its own |
| AC3 | A link check over the guide, the READMEs and CONTRIBUTING |

---
*Filled in at the end of the phase:*

## The dry runs
The first reviewer completed every step, but its first card had no test evidence: under
Docker, every test run of an installed Repro ended before reporting a test. It also found a
card VERIFIED with no test run, and gaps in the guide. Each was fixed here:

- **An installed Repro ran no test in a container** (Docker Desktop, Windows). The Docker
  sandbox bind-mounted Repro's pytest plugin and audit hook from the installed package. For a
  tool installed with `uv tool install`, the container's user (uid 1000) got "Input/output
  error" reading them, while root could; pytest then could not load `repro_pytest`. Other host
  directories behaved inconsistently too (a fresh copy under `%LOCALAPPDATA%` looked empty even
  to root). The hook now goes into a volume of its own, streamed in as a tar archive and mounted
  read-only, like the commit and its environment: nothing of the host is mounted. From the same
  install location, the three changes the reviewer tried then ran their tests at L3.
- **The install check did not see it.** `scripts/install_check.py` only checked that the first
  run completed. It now requires its card to be VERIFIED, with a selected test and nothing
  missing but the timing of a test too fast to time.
- **A card was VERIFIED although no test run finished.** When base's map run and head's listing
  both end early and no function changed, nothing is selected, so no rule saw the dead runs.
  A test run that does not finish now has a missing reason of its own, `run_incomplete` (it
  was `environment_failed`, or `timeout` past the limit), and leaves the change UNVERIFIABLE
  (`tests_not_run`) whatever was selected. Probe runs keep their reasons: probes are never
  required. Its detail now ends with the line of the run's output that names its error. The
  chaos test `test_a_test_run_that_cannot_start_leaves_the_change_unverifiable` builds such a
  suite; before the fix its card was VERIFIED.
- **A VERIFIED card said "everything was checked" while Missing listed items.** It now says so
  only when Missing is empty.
- **`repro run` did not say the card's status.** Its last line now ends with it.
- **The cockpit's drawer said "None yet."** of an empty table on a finished card; it says
  "None." once the run has finished.
- **The guide:**
  - `--log-format` and `--log-level` placed after the command;
  - `--no-serve` not mentioned;
  - the address's form, and where the run's ID is printed;
  - doctor's `containment` line;
  - the runs' names (A, A2, H);
  - API breakages and test changes missing from the lists, `n/a`, symbol IDs, the card's digest
    and the lock digests;
  - the two event counts;
  - where Repro keeps data;
  - the settings a user needs.

The second reviewer, given the corrected guide and wheels built from this branch, completed the
quickstart from the docs alone, with no blocker: install to a read card in about four minutes,
on a machine with Docker's image and uv's cache already warm. It needed `--help` once, by
choice. On itsdangerous `93ae366` to `2f69e84` it got a FLAGGED card at L3 with 41 tests run,
and explained each row correctly. What it found was fixed here too:

- **The session token reached the terminal's log**: uvicorn logs each WebSocket it accepts with
  its query, `?token=…` included, through a logger the access-log switch does not cover. Its
  loggers now go through Repro's handler (`repro.logs.adopt`), which redacts a credential in a
  query string; its lines are JSON like Repro's own. Checked end to end: the token is printed
  once, in the address for the user, and nowhere else.
- **A change to a class's own code selected none of the tests that use the class.** A class
  attribute (`Signer.default_digest_method`) runs at import, never inside a test, so the map
  holds it for no test, and only the tests of the edited test file ran. Coverage already
  counted such a class as reached through its methods; selection now does the same. On the same
  change, 57 tests run instead of 41, `test_signer.py`'s 16 among them.
- **The Markdown card listed every target** of a missing item (39 test IDs in one cell); it shows
  five and counts the rest. The JSON card keeps them all.
- **The guide:** the Python the tests run on (3.13) and that it is not a setting; any commit as
  a ref; `collection_error`; how tests are selected and reached; the drawer as a summary of the
  card; `modified` beside `base_test_fails_on_head`; the lock file each digest is of; the
  cockpit's Status, Result and row statuses.

## What shipped
- **Docs.** `docs/guide/` (seven pages, its index among them, and the demo's stills and card);
  README and `docs/README.md` links; CONTRIBUTING's CI table; the engine README's API paragraph;
  FAILURES.md (`run_incomplete`), ARCHITECTURE §6.1, THREAT_MODEL T2 (no host mounts) and T13
  (the token in the server's log).
- **Engine.** `repro.sandbox.docker`: the hook in a volume (`hook_archive`). The missing reason
  `run_incomplete` (`packages/events` schema first, then the runner, then the status rules).
  `repro run`'s last line gives the card's status. The VERIFIED reason's wording, on the
  Markdown card and in the cockpit. `repro.logs`: a credential in a query string redacted, and
  uvicorn's loggers adopted. `repro.runner.selection`: a changed class body selects the tests
  that ran its methods. The Markdown card's missing targets: five, and a count.
- **Cockpit.** The drawer's empty tables; the VERIFIED wording.
- **Scripts.** The install check requires a real first run.
- **Tests.** `test_sandbox_docker.py`: the unprivileged user reads the hook from its volume;
  the volume lives as long as the sandbox. `test_sandbox.py`: the hook's archive.
  `test_failures.py`: a suite that cannot start (fixture `suite-cannot-start`). `test_status.py`
  and `test_gap.py`: the new rule. `test_card.py`, `card.test.ts`: the wording and the
  targets. `drawer.test.tsx`, `focus.test.ts`: the drawer. `test_logs.py`, `test_cli.py`: the
  token in uvicorn's lines. `test_selection.py`: a class body's tests.

## Evidence
- **Local**, Windows with Docker Desktop running (`-m "not agent_eval and not chaos"`): 1,902
  passed, 4 skipped (2 POSIX-only, 2 gVisor-only), in 29 min. The chaos tests: 8 passed.
- **The install check**, wheels built from this branch: `uv tool install` 3.3 s, `--version`
  and `doctor` 6.5 s, the first run 32.5 s at L3 (VERIFIED, a test selected), the export and
  its schema check 1.4 s; 44.4 s in all. Against the wheels built before the fixes, the
  stricter check also passed from its own temporary directory: the failure depended on where
  the tool was installed, which is why the hook no longer depends on the host at all.
- **The demo**: recorded from one run of `silent-change` at L3 (`docs/guide/demo/`).
- CI run: linked in the PR.

## Deviations from spec
- **Engine fixes in a documentation phase.** H06's acceptance test found them; v1.0.0 could not
  ship with an install that runs no test in a container, or a card VERIFIED with no test run.
  Each is a separate commit.
- **The reviewer is an agent**, given only the guide. The owner will run the quickstart in
  person later; until then this is recorded as a known gap.

## Known gaps
- **A person has not yet run the quickstart from the docs alone**: the two dry runs were made by
  agents given only the guide. The owner will run it later; what that run finds goes into a
  follow-up.
- **Docker Desktop's bind mounts** were not characterised further: Repro no longer uses any.

## Dependencies added
None.

## Research notes
- An acceptance test by a reader who knows nothing of the code found what 1,902 tests did not:
  every test of the install path ran from a checkout, and the one test of the installed tool
  checked only that a run completed. A test of the installed product must check what the
  product promises (here, that the tests ran), not that it ran to the end.
