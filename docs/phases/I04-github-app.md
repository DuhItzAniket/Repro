# I04 — The GitHub App

| | |
|---|---|
| **Stage** | I — GitHub integration |
| **Status** | done |
| **Depends on** | I03 (and I01, I02); K10 for L5 |
| **Branch / PR** | `phase/I04-github-app` · [#117](https://github.com/DuhItzAniket/Repro/pull/117) |
| **Started / finished** | 2026-10-21 / 2026-10-21 |

## Objective
The roadmap's I04: "Webhooks, re-run button, org config". It had been deferred until users
asked. The owner asked on 2026-10-21, chose to run the App on the owner's own machine through a
relay for now, and accepted ADR-0019.

## Scope
- **`repro app register`** registers an App from GitHub's manifest flow, through a loopback
  page. The private key and webhook secret go from GitHub's answer into Repro's data directory
  (`github-app/`, mode 0600 on POSIX) and are never shown.
- **`repro app serve`** reads deliveries from a smee.io relay (`--relay`, by default the one
  registered) or a port of its own (`--listen`). It needs Docker.
- **Deliveries:**
  - each is checked by its signature, then by its delivery ID;
  - a pull request from the repository is run, and a fork's is gated: its check run asks for a
    click;
  - a click or a re-run is run only for someone with `admin` or `write`;
  - of several waiting for one pull request, the latest is run.
- **A run:**
  - a token for that one repository, for an hour, with four permissions;
  - the check run `in_progress`, then `repro run --pr` in its own process, in Docker;
  - the card reported as I02 does it, with the App's ID, the App bot's comment and a
    **Re-run Repro** button;
  - a run that fails completes its check run `neutral`, with the button.
- **Settings:** `app_repositories` (`owner/repo` patterns) and `app_concurrency`.
- **I02's reporting** takes a reporter's login, App ID, buttons and external ID, with the
  Action's defaults unchanged.
- **Docs:**
  - ADR-0019 (accepted) and the guide `docs/guide/github-app.md`;
  - THREAT_MODEL: A6, T20 extended, T21 and T22 new;
  - ARCHITECTURE, the settings, the guide index, README.

## Out of scope
- **Signing.** Sigstore's keyless signing rests on Actions' identity token, so the App's cards
  are not signed.
- A hosted, shared service (PRODUCT.md's non-goal), an organization-wide `.github`
  configuration, and a Marketplace listing of the App.

## Acceptance criteria
- [x] AC1: an App is registered from a manifest, and its secrets reach Repro's data directory
  without being shown.
- [x] AC2: a delivery that does not check its signature, or was seen before, is dropped; one
  that checks is answered at once and queued.
- [x] AC3: a pull request from the repository is run, and its card reported as a check run with
  a re-run button, and one comment.
- [x] AC4: a fork's pull request runs only on a click from someone with write access.
- [x] AC5: a re-run makes a new check run; the comment is updated, not added.
- [x] AC6: the App's token reaches neither the run's events nor its containers.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_github_app.py`: registration against the fake (a stranger's redirect refused, a refusal reported); the files and their modes; the manifest's permissions and events |
| AC2 | `test_github_app.py`: signatures, the relay's compact JSON; `test_github_app_serve.py`: unsigned and repeated deliveries, the App's own port |
| AC3 | `test_github_app_serve.py::test_a_pull_request_from_the_repository_is_run_and_its_card_reported`, a real `repro run` against the fake |
| AC4 | `test_github_app_serve.py::test_a_forks_pull_request_waits_for_a_click`, `::test_a_click_runs_only_for_someone_with_write_access` |
| AC5 | `test_github_app_serve.py::test_a_rerun_gets_a_check_run_of_its_own` |
| AC6 | the first test above: no installation token in the run's events; the tokens asked for one repository |

---
*Filled in at the end of the phase:*

## What shipped
- **Engine:**
  - `integrations/github/appauth.py`: the files, the JWT and installation tokens;
  - `webhook.py`: signatures and decisions;
  - `relay.py`: smee.io's stream;
  - `appserve.py`: the queue, the worker and the port;
  - `appregister.py`: the manifest flow;
  - `report.py`: the reporter's identity, buttons and external ID;
  - the `repro app` commands and the two settings.
- **Dependencies:** PyJWT becomes a direct dependency. It was already installed through `mcp`.
- **Tests:** `test_github_app.py` (31) and `test_github_app_serve.py` (8). The fake GitHub
  gained installation tokens, roles, the manifest's conversion and the App's ID on check runs.

## Evidence
**The live trial.** On 2026-10-21, on the owner's machine: WSL2's Ubuntu 24.04, Docker Engine
29.8.2, `REPRO_DOCKER_RUNTIME=kata`, so every run was at L5. The repository was a private test
repository holding Repro's `silent-change` fixture, with its change as pull request #1.
- **Registration.**
  - `repro app register` opened its page, which WSL2 forwards to the Windows browser.
  - The owner clicked Create on GitHub, and GitHub redirected to the loopback page. The
    manifest flow's `localhost` redirect works, as Probot's code suggested.
  - The App was registered. Its key and secret files were `-rw-------`, and nothing secret was
    printed.
- **The pull request.**
  - Its delivery was queued, and the check run showed `in_progress` within seconds.
  - The card was FLAGGED, at L5 on both sides, with one annotation (`to_celsius(100)`: head
    38, base 37.8) and one comment by `repro-engine[bot]`.
  - From the delivery to the card took 72 s.
  - The run's 84 events hold no token.
- **The re-run button.**
  - The first click re-ran the pull request. It also found a fault: the App had updated the
    completed check run, which then read "failed" while running, and the next card added a
    second copy of the annotation.
  - GitHub's re-run asks for "a new check run" [docs.github.com, "Using the REST API to
    interact with checks"], so the App now makes one whenever its last is completed (commit
    `7af3dc0`, with a test).
  - Two clicks after the fix: two new check runs, each with one annotation. The second click
    waited for the first run, since one pull request's runs never overlap. The comment was
    updated each time, and there is still one.
- **The relay.** 11 deliveries arrived through smee.io: 1 `installation`, 1 `pull_request`
  and 9 `check_run`. All 11 checked their signature against the payload written again
  compactly, and none was dropped.
- **Stopping.** Ctrl+C stopped `repro app serve` cleanly ("stopped", exit 0).
- **Tests:** the App's 39 tests and the GitHub, settings and CLI modules pass on Windows. The
  full suite runs in CI.

## Deviations from spec
- **The organization's configuration.** The roadmap named "org config". It is GitHub's
  installation (which repositories the App sees) narrowed by `app_repositories` on the host,
  with each repository's `.repro.yml` as before. An organization-wide `.github` file is not
  read.

## Known gaps
- **Missed deliveries.** While `serve` is stopped, deliveries through the relay are missed.
  smee.io does not keep them, and GitHub saw them delivered. A push or a re-run asks again.
- **The fork path was not tried live.** It needs a second account to fork from. It is tested
  against the fake.
- **The relay's signature check** passed all 11 deliveries here. A payload that smee.io's
  rewriting changes would be dropped, never run; `--listen` keeps GitHub's bytes.
- **No signing**, and on Windows the key files take the profile's permissions (T22).

## Dependencies added
- PyJWT 2.15.1 (MIT), with `cryptography` (Apache-2.0 or BSD-3-Clause), already in the lock
  through `mcp`.
