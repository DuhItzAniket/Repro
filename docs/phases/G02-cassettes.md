# G02 — Cassettes, prompt versioning & cost accounting

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | in progress |
| **Depends on** | G01 |
| **Branch / PR** | `phase/G02-cassettes` · PR pending |
| **Started / finished** | 2026-10-15 / — |

## Objective
Make every agent call reproducible without a model: record a call once, replay it offline
from a cassette keyed by (prompt version, model, input digest), and fail, never call the API,
when a recording is missing. Give prompts versions that always mean one text, and account for
what calls cost, per model and per run.

## Scope
- **Cassettes** (`repro.agents.cassette.CassetteBackend`, an `LLMBackend`): `record` makes the
  call through another backend and writes the cassette; `replay` serves recorded calls only and
  has no backend to call. A cassette holds the request (for review), the transcript (progress
  and Repro tool calls with their outputs, in order) and the result.
- **The key**: the prompt version, the model, and the SHA-256 of the input (role, prompts,
  tools, output schema, effort; not the budget) with its run-specific IDs (`ev_`, `evt_`,
  `run_` ULIDs) normalised by kind and first-seen order.
- **Replay in another run**: the recording's IDs are mapped to the current run's in tool calls,
  progress and the answer; the recorded tool calls are made again and must return what they
  returned (`StaleCassetteError` otherwise); a missing cassette is `MissingCassetteError`.
- **Prompt files** (`repro.agents.prompts`): `<name>.md` with a `version:` front matter, rendered
  with `string.Template` (exactly its placeholders, filled once); `lock.json` holds every
  version's SHA-256, only ever added to. `AgentRequest.prompt_version` (`name/number`).
- **Cost accounting**: usage per model from the CLI's `model_usage`; one `cost.estimate` per
  model a call used, with `source` `live` or `cassette` (an optional payload field); a
  `RunLedger` that totals a run's estimates and, with a limit, reserves each call's dollar
  budget out of what is left and starts no call once it is spent.
- **Offline tests**: the repository's conftest points every test at a closed loopback port with
  a dummy key and turns the CLI's nonessential traffic off; tests that start the CLI
  (`model_cli`) run behind a proxy that refuses and records every connection past loopback, and
  fail if there was one.

## Out of scope
- The prompts themselves and the cassettes of real agent roles (G04–G08); settings for the
  backend's mode, the cassette directory and a default run budget, which come with the first
  stage that runs agents (G04).

## Design notes
- **IDs are the only thing two runs of the same call differ in.** Evidence IDs are drawn afresh
  in every run and prompts carry them, so a digest of the raw input would never match a
  cassette in a later run, in CI or anywhere. Normalising by first-seen order makes the digest
  stable, and the same order maps the recording's IDs to the run's on replay; an ID the model
  made up, never in its input, stays as it is, so validation (G05) still rejects it.
- **A replay checks its premises.** The model's answer rests on what its tools returned, so
  replay calls them again and compares; a cassette whose evidence changed fails as stale rather
  than serving an answer to a question no longer asked.
- **Not the budget.** A run's ledger lowers a call's dollar budget as the run spends; leaving
  the budget out of the digest keeps that call the same call.
- **Only the model's behaviour is recorded.** `timeout` and `error` describe the
  infrastructure; recording them would replay an outage.
- **Cassettes are reviewable and stable**: canonical JSON, scrubbed like events, with the SDK
  and CLI versions but no time, so a cassette changes only when the call does.
- **A replayed cost is labelled.** It is what the call cost when recorded; `source` says so
  instead of presenting it as spending.

## Acceptance criteria
- [ ] AC1 (roadmap): cassettes keyed by (prompt version, model, input digest), with a missing
  cassette failing the test.
- [ ] AC2 (roadmap): prompt files versioned.
- [ ] AC3 (roadmap): `cost.estimate` events.
- [ ] AC4 (roadmap): the full agent test suite runs offline in CI.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_agents_cassette.py`: the same call in another run has the same digest, anything the model is given changes it, the budget does not; record, then replay in another run with that run's IDs; a missing cassette fails and calls nothing; stale evidence and failing tools; outcomes recorded or not; canonical, scrubbed files; `test_a_call_recorded_through_the_cli_replays_offline` (golden cassette) |
| AC2 | `test_agents_prompts.py`: front matter, rendering, the lock (new versions locked, changed text refused, old digests kept), `test_every_packaged_prompt_version_is_locked` |
| AC3 | `test_agents_events.py`: one `cost.estimate` per model with its `source`; a run whose budget is spent starts no more calls; `test_agents_cost.py`; schema examples |
| AC4 | the conftest guard on every test; `model_cli` tests behind the refusing proxy; `test_control_the_offline_check_sees_the_cli_leave_the_machine`; `test_no_test_can_reach_a_real_model`; CI on Ubuntu and Windows |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.cassette`: `CassetteBackend`, `CassetteKey`, `Ids`, `input_digest`,
  `MissingCassetteError`, `StaleCassetteError`.
- `repro.agents.prompts`: `Prompt`, `read_prompt`, `load_prompt`, `lock_problems`,
  `lock_new_versions`; `prompts/lock.json` (empty until G04's first prompt).
- `repro.agents.cost.RunLedger`; `run_agent(..., ledger=)`; `AgentRequest.prompt_version`;
  `AgentResult.by_model` and `replayed`; usage from `model_usage`.
- Schema: `cost.estimate.source` (optional), with examples.
- Tests: `test_agents_cassette.py` (27), `test_agents_prompts.py` (13), `test_agents_cost.py`
  (6), two more in `test_agents_events.py`; `refusing_proxy.py`; the conftest guard and the
  `model_cli` marker; golden cassette `engine/tests/golden/cassettes/review-1.json`.

## Evidence
- Recorded through the bundled CLI (2.1.300) against the local stand-in for the API, then
  replayed in another run with fresh IDs and no API: the answer cites the new run's evidence ID,
  and the stand-in received no further request (`test_a_call_recorded_through_the_cli_replays_offline`).
- Offline, measured with the refusing proxy: an unlocked CLI with its nonessential traffic on
  tried to reach `api.anthropic.com:443` five times per session (feature flags and telemetry,
  per the CLI's network documentation) although the model API was local. With the switch off,
  as the lockdown and now every test set it, no CLI test tried to connect past loopback.
  Removing the switch from the guard failed the three unlocked control tests with those
  attempts.
- CI run: linked in the PR.

## Deviations from spec
- ARCHITECTURE §10.5 keyed cassettes by the input digest; the digest is taken with run-specific
  IDs normalised, since a raw digest would never match in another run.
- `cost.estimate` gained an optional `source` field (additive), so a replayed cost is not
  presented as spending.
- The run budget is in place (`RunLedger`) without a default limit; the default is a product
  decision for when a stage first runs agents (G04).

## Known gaps
- No packaged prompt yet, so the lock is empty; G04's reader prompt is the first.
- Recording real cassettes needs an API key and spends money: that is the owner's decision,
  made per phase from G04 on. Recording uses `CassetteBackend(root, "record", AgentSdkBackend(...))`;
  a command for it comes with G04.
- Under concurrency, which call a nearly spent run budget turns away can differ between a live
  run and its replay, since calls settle in the order they finish.
- Replay calls the recorded tools in the order they finished when recorded, one at a time.

## Dependencies added
None.

## Research notes
- research/04 §1.8: `model_usage` includes subagents and is the field to account with;
  `total_cost_usd` is a client-side estimate; `max_budget_usd` can overshoot.
- Claude Code's network configuration (code.claude.com/docs/en/network-config, read
  2026-10-15): it respects `HTTPS_PROXY`, `HTTP_PROXY` and a comma-separated `NO_PROXY`;
  feature-flag fetches and telemetry go to `api.anthropic.com`; nonessential traffic can be
  turned off with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`.
