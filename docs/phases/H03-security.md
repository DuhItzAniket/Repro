# H03 — Security hardening

| | |
|---|---|
| **Stage** | H — Hardening & first release |
| **Status** | done |
| **Depends on** | H01 |
| **Branch / PR** | `phase/H03-security` · [#73](https://github.com/DuhItzAniket/Repro/pull/73) |
| **Started / finished** | 2026-10-17 / 2026-10-17 |

## Objective
The threat model is reviewed whole, and every threat in it is either met by a test or carries
a stated residual risk. What the model left to H03 is done: the API's session token (T13),
gVisor on Linux CI (L4), the audit of what leaves a run (T12) and of Repro's own
dependencies.

## Scope
- **The review.** THREAT_MODEL.md §7 lists, for each of T1–T19, the tests that meet its
  mitigation (`file.py::test`), or why none can. `test_threat_model.py` keeps it in step with
  §4 and with the test modules: a new threat without a row fails, and so does a row naming a
  test that no longer exists.
- **T13, the session token.**
  - Each server `repro serve`, `run` or `replay` starts makes a token of its own (32 random
    bytes), and every request for the engine's data must carry it (`repro.api.token`). The
    cockpit's own files need none.
  - The printed URL holds it in its fragment, which a browser never sends. The cockpit keeps it
    in `sessionStorage`, removes it from the address bar, and sends it as a bearer header, or
    on the event stream as a query parameter (`apps/web/src/data/session.ts`). A page opened
    without it says so instead of showing the demo.
  - No access log, since the stream's request line holds the token. The browser is started on
    a page only the user can read, not on a command line holding the token.
  - `repro serve` stays on loopback: with no TLS, the token would cross a network in clear
    text.
- **gVisor, L4.** `docker_runtime = "runsc"` runs the containers that hold the target's code
  under gVisor. The sandbox checks that Docker has the runtime before it starts, and states L4
  only then. A CI job, `gvisor`, installs it as gVisor's documentation says and runs the
  Docker test module, escape suite included, plus one fixture end to end.
- **The escape suite, expanded.** Seven more attempts in the container, each blocked at L3 and
  under gVisor: becoming root, a raw socket, mounting a filesystem, Docker's own socket, a
  kernel setting under `/proc/sys`, kernel devices, the host's environment.
- **Detection judged by where a path leads** (found in H02). The audit hook compared written
  paths with its roots as written. A link inside the run's directory that leads out went
  unreported, and a path through a redirected folder (a packaged app's), a junction or a short
  name was reported falsely. Both sides are now resolved first.
- **T12, the audit of what leaves a run.**
  - The home directory is written `~` in every string of every event. Log messages, values and
    errors pass the events' credential scrubbing.
  - `test_secrets.py` runs `repro run` with four kinds of credentials in the host's
    environment, on a target that prints its environment and fails holding a token. It finds:
    no credential in any file the run wrote, and neither the token nor the home directory in
    the events, the card or its exports.
- **The dependency audit.** pip-audit 2.10.1 over the 59 locked Python packages (hashes
  checked, nothing installed) and `pnpm audit` over the JavaScript ones: no known
  vulnerabilities today. A CI job, `dependency audit`, repeats it on every PR. It is not a
  required check, so that an advisory published today cannot block unrelated work.

## Out of scope
- **TLS, and listening beyond loopback.** A token that crosses a network in clear text
  protects nothing; `repro serve` stays on 127.0.0.1 or ::1.
- **Scrubbing raw artifacts.** JUnit XML and the plugin's results are kept as the target wrote
  them: they are evidence, and rewriting them would change their digests. They stay on the
  machine and the API serves them only with the token (T12's residual).
- **gVisor off Linux.** It runs on Linux only; on Windows and macOS L3 is the highest level.
- **Same-user processes**, which can read the terminal the token is printed to (§6 of the
  threat model).

## Design notes
- **A fragment, not a cookie.** A cookie would need no change to the cockpit, but browsers do
  not isolate cookies by port (RFC 6265 §8.5): one set by 127.0.0.1:8780 is sent to every
  server on 127.0.0.1, so any local server the user visits would receive the token.
  `sessionStorage` is per origin, port included, and a fragment never leaves the browser.
- **The stream takes the token in its query**, because a browser cannot set headers on a
  WebSocket handshake. That is why the access log is off, and why the REST routes refuse a
  token in the query: there it would only end up in logs.
- **A page, not a command line.** The URL with the token could be read from the browser's
  command line by other users of the machine (on Linux, `/proc/<pid>/cmdline`). The browser is
  started on a file only the user can read, which sends it on.
- **L4 only when it is there.** The runtime is checked against `docker info` before anything
  starts; naming one Docker lacks is an error, never a silent L3. Another runtime is passed on
  but states L3: Repro knows of no layer it adds.
- **Judged where it lands.** The hook resolves both the written path and its roots. A write
  that lands in the run's directory through a link is not an attempt; a write that leaves it
  through one is, which before was missed.

## Acceptance criteria
- [x] AC1 (roadmap): every THREAT_MODEL item has a test or a documented residual risk.
- [x] AC2: the API's data needs the session token, and the token appears in no request line,
  log, `Referer` or command line.
- [x] AC3: the container suite, escapes included, passes under gVisor on Linux CI, and a run
  there states L4.
- [x] AC4: nothing secret or personal leaves a run: no host credential in any file it wrote,
  and neither a target's token nor the home directory in its events, card or exports.
- [x] AC5: Repro's locked dependencies have no known vulnerabilities, and CI checks it.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_threat_model.py` over THREAT_MODEL.md §4 and §7 |
| AC2 | `test_api_security.py` (the token's tests); `test_cli.py::test_the_browser_is_opened_on_a_private_page_not_the_token`, `::test_the_server_logs_no_request_lines`; `session.test.ts`; Gate C's spec through the printed URL |
| AC3 | CI job `gvisor`: `test_sandbox_docker.py` with `REPRO_DOCKER_RUNTIME=runsc`, `test_run_stage.py::test_a_run_under_gvisor_is_l4` |
| AC4 | `test_secrets.py`; `test_bus.py::test_the_home_directory_is_stored_as_a_tilde`; `test_logs.py` |
| AC5 | CI job `dependency audit` |
| — | `test_sandbox.py::test_a_write_is_judged_by_where_its_path_resolves`; `test_provision_env.py::test_a_side_that_rewrites_its_environment_poisons_nothing` |

---
*Filled in at the end of the phase:*

## What shipped
- **Code.**
  - `repro.api.token`. `create_app(..., token=)`: the REST routes and the replay log behind a
    router whose dependency checks the token; the stream checks it before accepting.
  - The CLI: a token per server, the URL's fragment, no access log, the private page that
    opens the browser, and the loopback-only message.
  - `DockerSandbox(runtime=)`: the runtime check, `--runtime` on the target's containers, and
    L4 under gVisor. The `docker_runtime` setting (`REPRO_DOCKER_RUNTIME`).
  - The audit hook resolves paths (`_real`).
  - `repro.scrub` writes the home directory `~`. `repro.logs` scrubs messages, values and
    errors.
  - The cockpit: `src/data/session.ts`, the stream URL's token, and the message for a page
    without one.
- **CI.** Jobs `gvisor` and `dependency audit`.
- **Docs.**
  - THREAT_MODEL: T1, T2, T12 and T13 rewritten, and §7.
  - ARCHITECTURE: the session token, L4 and the secrets rule. FAILURES: a missing runtime.
  - TEST_STRATEGY layer 10; `engine/README.md` (`docker_runtime`); the paper log.
- **Tests.**
  - New: `test_threat_model.py` (2), `test_secrets.py` (1), `session.test.ts` (5), and in
    `test_api_security.py` (3), `test_cli.py` (2), `test_sandbox.py` (1),
    `test_sandbox_docker.py` (2, and 7 escapes), `test_run_stage.py` (1),
    `test_provision_env.py` (1), `test_bus.py` (1), `test_logs.py` (1) and `source.test.ts` (1).
  - Updated: the CLI's servers get a known token in tests (`api_support.known_token`). The
    gate specs put test mode in the query, before the fragment.

## Evidence
- **Local**, Windows with Docker Desktop (`-m "not agent_eval and not chaos"`): 1,875 passed,
  4 skipped (2 POSIX-only, 2 gVisor-only).
  - The container module: 22 passed, the 12 escapes included; the gVisor-only test
    skipped.
  - `pnpm test`: 47 + 34 + 310 passed.
  - Gate C's spec in Edge, through the printed URL: passed.
  - The token in a real browser: without it the cockpit says so; with it, a stored run of
    6,159 events streamed in full, and the address bar lost the fragment.
- **Audits.** pip-audit 2.10.1 over the 59 locked Python packages and `pnpm audit`: no known
  vulnerabilities (2026-10-17).
- **Under gVisor** (CI's `gvisor` job, runsc release-20261012.0): the container module and the
  end-to-end run passed but for the fork bomb, whose container gVisor ended when its tasks
  reached the pids limit, before the timeout: the limit counts the sandbox's own threads.
  The test now holds each runtime to what it does; T4's residual says so.
- CI run: linked in the PR (#73).

## Deviations from spec
- **The token is not a cookie**, as a first design would have it: see Design notes.

## Known gaps
- **T3 at L0–L2.** No test shows the host's `.git` untouched there, because nothing stops a
  target that finds it; T2's residual covers it.
- **The preview cap (T12, E04)** has no test of its own.
- **`net-call`'s flaky end-to-end test** (H02's known gap) is still open, as a follow-up.

## Dependencies added
None to the project. CI runs pip-audit 2.10.1 through `uvx`, outside the project's
environment.

## Research notes
- A browser's cookie jar is per host, not per origin, which rules cookies out for anything
  served on 127.0.0.1 next to other local servers. A URL fragment plus `sessionStorage` gives a
  per-port secret that never leaves the browser.
- A threat model is only as good as its link to tests. Tracing each threat to tests found one
  with none (T6) at once.
