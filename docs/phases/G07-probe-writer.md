# G07 — Probe-writer agent

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | in progress |
| **Depends on** | G03, E06 |
| **Branch / PR** | `phase/G07-probe-writer` · PR pending |
| **Started / finished** | 2026-10-16 / — |

## Objective
Find differences that only realistic inputs reach. An agent that never sees the claims proposes
inputs for the changed functions, and they run beside Hypothesis's inputs on base, base again
and head.

## Scope
- **The probe writer** (`repro.agents.prober`, prompt `probe/1`, in the `probes` job with
  agents on). For each function E06 can probe (up to 6 per call), it is shown:
  - the definition as it is on head;
  - its parameters' types, and the shape its arguments take (`{"text": <str>}`);
  - the diff of its file.

  It is never shown the PR's text or claims (ARCHITECTURE §4.4). It answers with up to 8
  inputs per function, each with what it tries.
- **The filters, counted and logged.**
  - On the host: a proposal must name a function it was shown and exactly that function's
    parameters, each value of its annotated JSON type within E06's bounds
    (`probes.fits`, `probes.arranged`). Otherwise it is dropped.
  - In the sandbox: the kept proposals, without repeats of Hypothesis's inputs, run after them
    in the same three runs. A proposal the base runs disagree on is left out.
  - The run's log states each count: proposed, dropped, ran, unstable, differing.
- **Attribution.** Each `probe_diff` records which generator's inputs differ (`found_by`:
  `hypothesis`, `agent` or both) and how many inputs were proposed. Its summary says whose
  input the reproducer is ("generated input" or "the probe writer's input"), so the card shows
  which kind supports a finding.
- **Failure.** A probe writer that fails is an `agent_failed` missing item naming the
  functions. That includes a replay with no cassette for its call. Hypothesis's inputs run
  regardless. Any agent whose cassette is missing or stale now ends with a `failed` state, so
  the cockpit does not show it thinking forever.
- **A setting**: `agent_probes` (`REPRO_AGENT_PROBES`), on by default, switches the probe
  writer off.
- **New fixture `probe-semantic`.**
  - The change: `to_utc()` subtracts the UTC offset in whole hours.
  - That is right for `+01:00`, the only offset its tests use, and 30 minutes off for `+05:30`.
  - Random text is almost never a timestamp with a half-hour offset. Without agents the card
    is VERIFIED; with them, FLAGGED.

## Out of scope
- **Probes for functions E06 cannot probe** (methods, objects, fixtures, untyped parameters).
  They would need written test code (see Design notes).
- **The reviewed run of `probe-semantic`** with its cassettes, replayed in
  `test_agents_run.py`. It waits for the API's daily quota (see Evidence).

## Design notes
- **Inputs, not code.** ARCHITECTURE §4.4 planned a probe writer that writes pytest probes.
  This one proposes inputs as data, which E06's runner calls.
  - No agent-written byte is ever executed (T15). A prompt-injected probe writer can only
    choose arguments for the target's own functions, inside the sandbox.
  - The filters are mechanical. The runs reuse E06's determinism check (A against A2) and its
    reproducers.
  - The cost: only functions with JSON-typed parameters can be probed. §4.4 has an as-built
    note.
- **Claim-blind by construction.** `prober_request` takes the candidates and the repository
  sources only, so no code path can hand it the PR's text.
- **The argument shape is spelled out.** In the first live call the model proposed exactly
  the right cases (`+02:30`, `-03:45`, `+00:45`) but gave each as a bare string, not an object
  naming the parameter. All 8 were dropped. `probe/1` now shows each function's argument
  shape and says "never a bare value". The draft was never committed, and its cassette was
  discarded.
- **Strict about the filter.** A bare string could be guessed to mean the only parameter, but
  the filter does not guess. A proposal that does not fit is counted as dropped. The prompt
  is fixed instead.

## Acceptance criteria
- [x] AC1 (roadmap): on a fixture whose tests pass on a wrong change, generated probes expose
  the divergence.
- [x] AC2 (roadmap): the filter rejection rate is reported.
- [x] AC3: claim-blind; TestGen-LLM-style filters; run on both sides (base twice, then head).

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_recorded_probe_writer_exposes_the_divergence`: the live call replayed from its cassette on `probe-semantic`. Hypothesis's inputs find nothing (`test_the_probe_semantic_fixture_needs_a_realistic_input`), and the agent's do. The fixture's deterministic run in `test_run_stage.py` is VERIFIED |
| AC2 | The counts in the log and in `Probing.proposed`; `test_a_realistic_input_finds_what_random_ones_do_not` checks the logged lines; `test_only_proposals_that_fit_their_signature_are_kept` checks the filter |
| AC3 | `test_the_probe_writer_sees_each_function_and_its_change_not_the_claims` (untrusted blocks, no claims, strict schema); `test_fits`; `test_a_proposal_names_exactly_the_parameters`; `test_differences_say_which_inputs_found_them`; `test_without_the_probe_writer_the_probes_still_run` |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.prober`: `prober_request`, `read_proposals`, `schema`, `shape`, `type_text`.
  Prompt `probe/1` (locked).
- In `repro.runner.probes`:
  - `fits` and `arranged`;
  - `probe(..., proposed=)`;
  - per-function generated counts, `Probing.proposed`;
  - `ProbeDiff.found_by`, with `inputs_proposed` and `found_by` in the evidence.
- The probe writer in the `probes` job (`run_jobs(..., agents=)`). `found_by` is shown to
  reviewers.
- Fixture `probe-semantic` (spec, expectation, golden card), labelled in the claim set
  (19 PRs, 46 labels).
- Tests:
  - `test_agents_prober.py` (8);
  - 4 more in `test_probes.py` (one parametrised over 9 types);
  - `probe-semantic` in `test_run_stage.py`.

## Evidence
Recorded live on 2026-10-16 (Groq, `openai/gpt-oss-120b`), replayed offline:

| | Count |
|---|---|
| Functions shown | 1 (`stamps.utc:to_utc`) |
| Inputs proposed | 8 |
| Dropped by the signature filter | 0 (0 %) |
| Ran on base, base again and head | 8 |
| Left out as unstable (A ≠ A2) | 0 |
| Differing between base and head | 3: `+05:30`, `-04:45`, `+02:15` |
| Hypothesis's inputs (40) differing | 0 |
| Tokens / estimated cost of the call | 954 in, 1,718 out / $0.0012 |

- The five whole-hour or naive inputs (`+00:00`, `+14:00`, `-12:00`, no offset, date only)
  agree on both sides, as they should.
- The `probe_diff` cites the first one: `to_utc(text='2023-05-15T12:34:56+05:30')` gives
  `07:04:56+00:00` on base and `07:34:56+00:00` on head (`found_by: agent`).
- The draft prompt's call (discarded, see Design notes) dropped 8 of 8.
- The claim set with `probe-semantic`: precision 0.958 (46/48), recall 1.000 (46/46). This is
  the third row of `bench/results/agent-evals.csv`.
- The reviewed run was recorded as far as the review. The review then waited on the API's
  tokens-per-day limit (200,000 for the model; 199,466 used), past the review job's 600 s.
  Its cassettes were discarded.
- CI run: linked in the PR.

## Deviations from spec
- ARCHITECTURE §4.4: the probe writer proposes inputs, not pytest probes, and a reproducer is
  a call, not probe source (see Design notes).

## Known gaps
- Only module-level functions with JSON-typed parameters on both sides get proposals.
- The reviewed `probe-semantic` run is not yet replayed in `test_agents_run.py`.
- **The Gate G runs predate the probe writer.** `honest-fix`, `injection`, `silent-change`
  and `false-claim` were recorded before it existed, and `test_agents_run.py` replays them
  with `REPRO_AGENT_PROBES=off`.
  - Its inputs would add evidence (`parse_date` is probeable), so every reviewer call of those
    runs must be recorded again.
  - That is about 100,000 tokens, roughly 12 hours of the API's daily refill (200,000 tokens a
    day, refilled continuously). It is due before Gate G.
  - Their cards must then hold no `agent_failed` item, which the test now asserts.

## Dependencies added
None.

## Research notes
- TestGen-LLM's filters (research/02 §9.1) require that a generated test:
  - builds;
  - passes reliably;
  - increases coverage.

  Here the first two map to fitting the signature, and to running on base and agreeing across
  A and A2. The third has no counterpart: a kept proposal is evidence only when it differs
  between base and head.
