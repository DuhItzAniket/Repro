# G01 — LLM backend & locked-down runtime

| | |
|---|---|
| **Stage** | G — Agents |
| **Status** | done |
| **Depends on** | C03 |
| **Branch / PR** | `phase/G01-llm-backend` · [#60](https://github.com/DuhItzAniket/Repro/pull/60) |
| **Started / finished** | 2026-10-15 / 2026-10-15 |

## Objective
One way for the engine to reach a model: an `LLMBackend` protocol, and its default
implementation on the Claude Agent SDK under the full lockdown of ADR-0007. Every call has a
budget, a run starts no more agents at once than the machine can hold, and every call is
reported as the `agent.*` events the cockpit's dispatch and workspace panels draw.

## Scope
- **The protocol** (`repro.agents.backend`): an `AgentRequest` (role, system prompt, prompt,
  model, `Budget`, read-only `ReproTool`s, optional output schema, effort) and an `AgentResult`
  (an outcome of `ok`, `max_turns`, `max_budget`, `timeout`, `invalid_output` or `error`; the
  structured answer or text; turns; client-side usage; the tool calls made and whether each
  was allowed). What the model does never raises.
- **The SDK backend** (`repro.agents.sdk.AgentSdkBackend`): each call in a workspace of its own
  (an empty `cwd`, a Claude configuration directory, the system prompt as a file), removed
  afterwards; Repro's tools as one in-process MCP server, `repro`.
- **The lockdown** (`repro.agents.lockdown`): `tools=[]`; `allowed_tools` and a `PreToolUse`
  gate that permit exactly the call's own `mcp__repro__*` tools (and `StructuredOutput` when it
  asks for a schema); `dontAsk`; `strict_mcp_config`, no plugins or skills; `setting_sources=[]`;
  `verbatim_prompts`; and `CLAUDE_CONFIG_DIR` (per call), `CLAUDE_CODE_DISABLE_CLAUDE_MDS`,
  `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`, and subagents
  held to their floor.
- **Budgets**: `max_turns`, `max_budget_usd` and a wall-clock `timeout_s` on every call.
- **Dispatch** (`repro.agents.dispatch`): concurrency `min(12, free RAM in GiB)`, at least 1
  (Windows `GlobalMemoryStatusEx`, Linux `MemAvailable`); the 12 dispatch slots, lowest free
  first; agent ids `a01`…`a999`.
- **Events** (`repro.agents.events.run_agent`): `agent.spawned` with the slot, `agent.state`
  (`waiting` only when queued, then `thinking` and `tool_call` with `detail`, `progress` the
  share of the turn budget used, then `done` or `failed`), and `cost.estimate`. Cancelling the
  job cancels the call.

## Out of scope
- Cassettes, prompt versioning and cost accounting (G02); the evidence tools (G03); any agent
  role (G04–G08). No pipeline job runs an agent yet.

## Design notes
- **Test against the real CLI, offline.** The SDK spawns the Claude Code CLI it bundles. A
  local stand-in for the Messages API (`engine/tests/fake_messages_api.py`) answers at
  `ANTHROPIC_BASE_URL`, records each request and streams scripted replies, so the tests see
  exactly what reaches the model, with no network and no key.
- **A plant only proves something if it works.** Each placement of a planted `CLAUDE.md`,
  hooks, skills, subagents, commands and `.mcp.json` (in an ancestor of the `cwd`, in the `cwd`,
  in the configuration directory) is first run on an unlocked CLI, where it loads; then under
  the lockdown, where it does not.
- **The gate permits a call's own tools, not a prefix.** A Repro tool the call was not given is
  denied as firmly as Bash. The CLI's `StructuredOutput` tool carries the answer when the call
  has a schema: the first version denied it with everything outside `mcp__repro__*`, and the
  run looped to its turn limit.
- **The SDK raises after an error result.** On `error_max_turns` and the like, the CLI exits
  non-zero after yielding the result, and the SDK raises `ResultError`; the backend reports the
  result it already holds.
- **Waiting is polled.** Jobs run in threads of their own, each with its own event loop, so the
  dispatch is thread-safe and waits by polling (50 ms), never blocking a loop.

## Acceptance criteria
- [x] AC1 (roadmap): tests prove built-in tools are unavailable.
- [x] AC2 (roadmap): a `CLAUDE.md` or hook planted in the target repo is never loaded.
- [x] AC3 (roadmap): calls outside `mcp__repro__*` are denied.
- [x] AC4: budgets, the concurrency limiter, and `agent.spawned` / `agent.state` events valid
  against the schema.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_the_model_sees_the_calls_own_tools_and_prompts_only`: every request's tools are exactly `mcp__repro__ping`; the system prompt ends with the call's file; an `@CLAUDE.md /init` prompt arrives verbatim; `test_a_structured_answer_comes_through_structured_output` |
| AC2 | `test_control_the_plant_works_on_an_unlocked_cli[ancestor, cwd, config]`, then `test_the_lockdown_loads_and_runs_nothing_planted[…]`, `test_claude_md_stays_out_even_if_settings_were_loaded[…]`, `test_the_backend_with_its_scratch_inside_the_target_loads_nothing` |
| AC3 | `test_calls_outside_the_calls_own_tools_are_denied_even_if_offered` (a foreign server's tool, an undeclared Repro tool and Bash, all pre-approved by mistake: denied, no effect), `test_the_backend_reports_which_calls_it_allowed`, `test_the_gate_denies_every_other_tool[…]` |
| AC4 | `test_a_run_out_of_turns_ends_as_max_turns`, `test_a_run_without_a_valid_structured_answer_is_invalid_output[…]`, `test_every_budget_limit_is_positive`; `test_agents_dispatch.py`; `test_agents_events.py` (schema-validated logs from real runs) |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.agents`: `backend` (`LLMBackend`, `AgentRequest`, `AgentResult`, `Budget`,
  `ReproTool`, `Usage`, `Progress`), `lockdown` (`lockdown_options`, `lockdown_env`,
  `permitted_tools`, `tool_gate`), `sdk` (`AgentSdkBackend`), `dispatch` (`Dispatch`,
  `concurrency_for`, `default_concurrency`, `free_memory_gib`), `events` (`run_agent`).
- Dependency `claude-agent-sdk==0.2.167` (bundles CLI 2.1.300).
- Tests: `test_agents_lockdown.py` (32), `test_agents_dispatch.py` (17), `test_agents_events.py`
  (6), `test_agents_cli.py` (17, the real CLI); `fake_messages_api.py`, `agent_support.py`.

## Evidence
The real CLI (2.1.300) against the local API, Windows:

| Placement of the plant | Unlocked CLI loads | Under the lockdown |
|---|---|---|
| ancestor of the `cwd` (scratch inside the target) | the project's `CLAUDE.md` | nothing |
| the `cwd` is the target | its `CLAUDE.md`; its `SessionStart` and `UserPromptSubmit` hooks run | nothing |
| the configuration directory | its `CLAUDE.md`; its hooks run | nothing |

- Mutations, one at a time: `setting_sources` left to the SDK's default lets the `cwd` and
  configuration plants through (2 tests fail); dropping `CLAUDE_CODE_DISABLE_CLAUDE_MDS` alone
  changes nothing above (the settings layer holds), but with settings on it lets every
  `CLAUDE.md` through (3 tests fail); a gate that allows everything lets the pre-approved
  foreign tools run (1 test fails).
- What the model is sent: the SDK's one-line preamble and the call's prompt file as the system
  prompt, the call's tools only, and an environment block (working directory, platform, OS
  version, date) the CLI adds.
- Full suite (Windows, Docker stopped): 1510 passed, 13 skipped, 1 failed: `net-call`'s
  `test_summary` timed as a performance regression while the machine had about 0.4 GiB free;
  it passed when run alone (the D07 timing effect noted in F05).
- CI run: linked in the PR (#60).

## Deviations from spec
- ARCHITECTURE §10.2 asked for a subagent depth of 1: the variable takes a positive number and
  ignores anything else, so 1 is its floor; with no Agent tool there is no way to start one.
- The gate permits `StructuredOutput` with an output schema: the CLI delivers `output_format`
  through it.
- The gate permits the call's own tools rather than any `mcp__repro__*` name.

## Known gaps
- The CLI tells the model its working directory, platform and OS version; the directory is the
  call's scratch path, under the machine's temporary or Repro directory.
- Managed policy settings on the host are read regardless (research/04 §1.3): they are the
  machine owner's, not the target's.
- No pipeline stage runs an agent yet; the jobs that will (G04–G08) choose the concurrency per
  run.
- The structured-output schema travels on the CLI's command line (`--json-schema`); per-claim
  schemas are small, but a large one would meet Windows' command-line limit.

## Dependencies added
- `claude-agent-sdk` 0.2.167 (MIT; PyPI, released 2026-10-14). It bundles the Claude Code CLI
  2.1.300, whose use is governed by Anthropic's Commercial Terms (research/04 §1.1). Since the
  0.2.165 that research/04 verified: the bundled CLI moved to 2.1.299 and 2.1.300, and hook
  input and output types were added (CHANGELOG 0.2.166, 0.2.167, read 2026-10-15).

## Research notes
- research/04 §1.3 (restricting tools), §1.5 (structured output), §1.10 (one process per
  session, about 1 GiB each); ADR-0007; ARCHITECTURE §10.
- Claude Code's environment variables (code.claude.com/docs/en/env-vars, read 2026-10-15):
  `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` take a
  positive whole number and ignore anything else; `CLAUDE_CODE_DISABLE_CLAUDE_MDS`;
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`; `CLAUDE_CONFIG_DIR`.
- Microsoft Learn, `MEMORYSTATUSEX` (`ullAvailPhys`); proc(5), `MemAvailable`.
