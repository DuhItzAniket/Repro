# G10 — OpenAI-compatible backend (Groq, local models)

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | in progress |
| **Depends on** | G01, G02 |
| **Branch / PR** | `phase/G10-openai-backend` · PR pending |
| **Started / finished** | 2026-10-16 / — |

*Added to Stage G on 2026-10-16 by the owner's decision recorded in ADR-0016, and done before
G04, whose recordings and evaluation use it.*

## Objective
A second `LLMBackend` for any OpenAI-compatible Chat Completions API, so that Stage G's agents
can be recorded and measured with the owner's Groq key, and so that a user can run the agent
stages on a local model or a router as well as on Claude.

## Scope
- `repro.agents.openai_compat.OpenAICompatibleBackend` with an `Endpoint` (base URL, the
  environment variable holding the key or none, a price table, temperature, output cap,
  reasoning controls, retries, request timeout); `Endpoint.groq()`.
- Repro's own agent loop: the request's tools as functions; each call answered from its
  `ReproTool`, any other name refused; turns, estimated dollars and wall-clock time bounded.
- Structured answers asked for alone with `response_format` `json_schema` (strict when the
  schema allows), validated against the schema, retried once.
- Rate limits and server errors retried (`retry-after`, then backoff); the key read from the
  environment per call and kept out of every result and message.
- Costs from the price table (Groq's prices, with sources); `Usage.priced`, so a model with no
  known price gets no `cost.estimate`.

## Out of scope
- Choosing the backend from settings, and which model each role uses (G04, with the first
  stage that runs an agent).

## Design notes
- **Two calls where one would do.** Groq cannot combine structured outputs with tools
  (ADR-0016), so the answer is a separate, tool-free request that sees the whole conversation.
  It costs one turn, counted against `max_turns` like any other.
- **Strict only when it is honest.** Strict mode decodes to the schema, but requires every
  property to be required and no other allowed; a schema that does not say so is sent with
  `strict: false` and checked by Repro alone.
- **Effort.** The request's effort becomes gpt-oss's `reasoning_effort` (`xhigh` and `max`
  become `high`, its highest); reasoning text is not requested (`include_reasoning: false`),
  since nothing reads it.
- **Temperature 0.5 on Groq**, the low end of the range Groq recommends for reasoning models,
  for answers that vary least; cassettes, not temperature, make CI deterministic.

## Acceptance criteria
- [x] AC1: the backend runs the tool loop, refusing every tool outside the call's own, and
  returns schema-checked structured answers.
- [x] AC2: turns, estimated cost and time end a call with the matching outcome; rate limits are
  retried; API errors end it as `error` without the key.
- [x] AC3: a call through it records and replays through a cassette (G02).
- [x] AC4: one live call to Groq succeeds with the owner's key (recorded in the evidence, not a
  test: tests never reach the API).

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_tool_loop_runs_the_calls_own_tools`, `test_a_call_outside_the_calls_tools_or_malformed_is_refused[…]`, `test_a_tool_that_raises_tells_the_model`, `test_a_structured_answer_is_asked_for_alone_and_checked`, `test_an_answer_that_breaks_the_schema_is_retried_once_then_refused`, `test_strict_mode_only_for_schemas_it_can_take` |
| AC2 | `test_turns_budget_and_time_end_a_call`, `test_a_rate_limit_waits_for_retry_after`, `test_an_api_error_ends_the_call_without_the_key[…]`, `test_no_key_means_no_request`, `test_a_plain_call_sends_the_request_and_counts_its_cost`, `test_a_local_server_gets_no_key_and_an_unpriced_model_no_cost` |
| AC3 | `test_a_call_records_and_replays_through_a_cassette` |
| AC4 | a live call to `openai/gpt-oss-120b` with a tool and a schema, its usage and estimated cost, in Evidence |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents.openai_compat`: `OpenAICompatibleBackend`, `Endpoint` (`Endpoint.groq()`),
  `Price`, `GROQ_PRICES`, `strict_allowed`.
- `Usage.priced`; `run_agent` emits no `cost.estimate` for an unpriced model; cassettes record
  `priced`.
- ADR-0016; the G10 row and paragraph in the ROADMAP; CLAUDE.md's stack line.
- Tests: `test_agents_openai.py` (17) against `fake_openai_api.py`; one more in
  `test_agents_events.py`; the golden cassette gains `priced`.

## Evidence
- One live call (2026-10-16) to `openai/gpt-oss-120b` with the owner's key, through
  `Endpoint.groq()`: a `ping` tool and a strict schema; the model called the tool once, the
  structured answer validated, three turns, 591 input and 121 output tokens, an estimated
  $0.000161.
- CI run: linked in the PR.

## Deviations from spec
- A phase added to Stage G by the owner's decision (ADR-0016); G04 now depends on it.

## Known gaps
- Groq's free limits (8,000 tokens a minute per model) bound a call's prompt and tool outputs;
  the agent prompts (G04-G08) are written to fit.
- Reasoning text is not requested, so a cassette from this backend records no thinking.
- Which backend and model each role uses is set from the settings in G04.

## Dependencies added
None (the HTTP client is the standard library's; `jsonschema` was already a dependency).

## Research notes
- ADR-0016's context, each fact with its source: console.groq.com/docs/openai, /tool-use,
  /structured-outputs, /reasoning, /rate-limits and each model's page, read 2026-10-16.

