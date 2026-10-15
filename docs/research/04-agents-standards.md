<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Research 4 — Agents, evidence-grounded verdicts, standards, schema & transport

Prepared for **Repro** · research date **2026-10-13** · author: research subagent

**Tags:** **[V]** = read on a primary source fetched today (official docs, specs, GitHub repos, PyPI/npm registry). **[S]** = from search snippets or secondary sources. **[U]** = not verified today (from background knowledge or inference). Recommendations are opinions and carry no tag.

Note: the engine and the target environments need Python 3.12+ (for `sys.monitoring`); install it with `uv python install`.

---

## 1. Claude Agent SDK (Python, `claude-agent-sdk`)

### 1.1 Version, requirements, platform
- **Latest version: 0.2.165, released Oct 8, 2026.** Earlier releases: 0.2.164 (Oct 6), 0.2.163 (Sep 30), 0.2.160 (Sep 25), 0.2.158 (Sep 23) **[V PyPI]**. The project ships patch releases every few days, so pin an exact version.
- Requires **Python ≥ 3.10**. Install with `pip install claude-agent-sdk` or `uv add claude-agent-sdk` **[V PyPI, quickstart]**.
- **No separate Node.js or Claude Code install is needed in most cases.** The package bundles a native Claude Code binary, and the SDK spawns it as a subprocess that talks over stdio **[V hosting, quickstart]**. Each SDK release pins the bundled CLI version: 0.2.165 bundles CLI **2.1.294** **[V CHANGELOG]**. The hosting docs say that "updating the SDK is how you update the CLI" **[V hosting]**.
- **Windows:** PyPI publishes a `win_amd64` wheel of about 110 MB. There is **no Windows ARM64 wheel**. On ARM64 Windows, pip falls back to the sdist, no binary is bundled, and you must install Claude Code natively and put it on `PATH` **[V PyPI, quickstart]**. Another Windows constraint is the ~32 KB command-line cap: a string `system_prompt` travels on the CLI command line, so pass large prompts as a file with `system_prompt={"type":"file","path":...}` **[V Python ref]**. The quickstart shows PowerShell setup (`.venv\Scripts\Activate.ps1`, `$env:ANTHROPIC_API_KEY`) **[V]**.
- **The OS sandbox for Bash does not run on native Windows.** The docs say: "The sandbox runs on macOS, Linux, and WSL2. On native Windows, Claude Code runs commands unsandboxed." **[V sandboxing doc]**. In the Python SDK, if `sandbox.enabled=True` but the sandbox can't start, commands run *unsandboxed with a warning* unless you set `"failIfUnavailable": True` **[V Python ref]**.
- **Auth:** `ANTHROPIC_API_KEY`, or Bedrock (`CLAUDE_CODE_USE_BEDROCK=1`), Claude Platform on AWS, Vertex (`CLAUDE_CODE_USE_VERTEX=1`), or Foundry (`CLAUDE_CODE_USE_FOUNDRY=1`). The SDK does **not** auto-load `.env` files. Third-party products may not offer claude.ai login unless Anthropic has approved it **[V quickstart/overview]**.
- **Licence and branding:** use is governed by Anthropic's Commercial Terms. A product must not call itself "Claude Code"; "{Name} Powered by Claude" is allowed **[V overview]**.

### 1.2 `query()` vs `ClaudeSDKClient`
Comparison table from the docs **[V Python ref]**:

| | `query()` | `ClaudeSDKClient` |
|---|---|---|
| Session | new session per call | reuses session |
| Interrupts | ❌ | ✅ (`interrupt()`) |
| Hooks / custom tools | ✅ / ✅ | ✅ / ✅ |
| Use case | one-off tasks | continuous conversations |

The README still says ClaudeSDKClient is needed for custom tools and hooks. The current docs contradict that: they show both features working with `query()` **[V]**. `ClaudeSDKClient` adds `set_permission_mode`, `set_model`, `get_context_usage`, `stop_task` and `disconnect` **[V]**.

### 1.3 Restricting tools (critical for Repro)
- **Availability vs permission.** `tools=[...]` and a bare-name entry in `disallowed_tools` control **which tools are in Claude's context at all**. `tools=[]` removes every built-in tool, so Claude can use only your MCP tools **[V custom-tools]**. `allowed_tools` only **pre-approves** tools: it "does not restrict Claude to this list", and unlisted tools fall through to the permission mode and `can_use_tool` **[V Python ref, permissions]**.
- **Evaluation order:** hooks → deny rules → ask rules → permission mode → allow rules → `can_use_tool` **[V permissions]**. A `PreToolUse` hook deny applies even in `bypassPermissions`. Auto-approved calls never reach `can_use_tool` **[V]**.
- **Permission modes:** `default`, `dontAsk` (denies anything not pre-approved and never calls `can_use_tool`), `acceptEdits`, `bypassPermissions`, `plan`, `auto` (a classifier decides) **[V]**. For a headless agent with a fixed tool surface the docs recommend `allowed_tools=[…]` together with `permission_mode="dontAsk"` **[V]**. When `permission_mode` is unset, the session may start in **auto** mode, so pass the mode explicitly **[V]**.
- **`can_use_tool(tool_name, input, ctx)`** returns `PermissionResultAllow(updated_input=…)` or `PermissionResultDeny(message, interrupt)` **[V]**.
- Allow rules ignore unanchored `"*"` or `"mcp__*"`. Write the tool name in full, e.g. `mcp__repro__*` **[V]**.
- **Untrusted target repos:**
  - When `setting_sources` is omitted, the SDK loads user, project and local settings, **CLAUDE.md, `.claude/` skills, hooks and agents from `cwd` and parent directories** **[V claude-code-features]**. A PR's worktree can therefore inject instructions or hooks if it is the agent's `cwd`.
  - To lock this down, set `setting_sources=[]`, set `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` in `env`, and point `CLAUDE_CONFIG_DIR` at a per-run directory **[V hosting, claude-code-features]**.
  - The docs warn that "managed policy settings and `~/.claude.json` are read regardless" **[V]**.
  - `verbatim_prompts=True` was added in 0.2.158 and needs CLI 2.1.248+. It sends user messages unchanged, with no `@path` expansion and no slash-command dispatch, "to prevent untrusted text from triggering file reads or commands" **[V CHANGELOG]**.
  - Subagent final messages are scanned for instruction-shaped patterns such as control-tag imitation and `Human:` markers (CLI v2.1.210+) **[V subagents]**.

### 1.4 Custom in-process tools (SDK MCP servers)
- Signature: `@tool(name, description, input_schema, annotations=None)`. `input_schema` can be a dict of Python types, `Annotated[...]` for field descriptions, or a full JSON Schema dict. The full-schema form is needed for enums and optional fields **[V Python ref, custom-tools]**.
- `create_sdk_mcp_server(name, version="1.0.0", tools=[...])` returns a config that goes into `ClaudeAgentOptions.mcp_servers={"repro": server}` **[V]**.
- Tool names take the form **`mcp__{server_key}__{tool}`** **[V]**.
- Handlers return `{"content":[...], "is_error": bool}`. An uncaught exception becomes an error result and **the loop continues** **[V]**.
- The **Python** `@tool` forwards only `content` and `is_error`, so `structuredContent` is **not** supported from Python in-process tools **[V]**.
- `ToolAnnotations(readOnlyHint=True)` allows parallel calls. It is a hint, not something the SDK enforces **[V]**.
- Tool search is **on by default** and defers SDK MCP tool schemas until they are needed **[V]**.

### 1.5 Structured output
- `output_format={"type":"json_schema","schema":{...}}`. The validated value arrives in `ResultMessage.structured_output` **[V]**.
- The SDK **validates the output and re-prompts on a mismatch**. This is **not** constrained decoding. If validation keeps failing, the run ends with `subtype="error_max_structured_output_retries"` **[V]**.
- A `success` result can still arrive with `structured_output=None`. Treat that as a failure **[V]**.
- **The SDK validates with JSON Schema draft-07. "Schemas that declare a newer version are rejected."** `format` is treated as an annotation only **[V]**. This matters because Repro's event schema targets draft 2020-12 (see §6).
- For comparison, the raw Messages API's structured outputs **do** use constrained decoding. Their limits **[V]**:
  - `additionalProperties:false` is required.
  - `minItems` accepts only 0 or 1.
  - No recursion and no numeric or string length constraints.
  - `enum` and `const` are supported.
  - Strict tools are limited to 20 per request.
  - Enum casing may drift.

### 1.6 Hooks
- Python hook events: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Stop`, `SubagentStop`, `SubagentStart`, `PreCompact`, `Notification`, `PermissionRequest`. Several others, such as `SessionStart`, are TypeScript-only **[V hooks]**.
- `PreToolUse` can return `permissionDecision` (`allow`, `deny`, `ask` or `defer`), `permissionDecisionReason` and `updatedInput` **[V]**.
- `PostToolUse` can return `additionalContext` or `updatedToolOutput` **[V]**.
- Returning `{"async_": True}` gives fire-and-forget logging **[V]**.
- Matching hooks run **in parallel**, and **deny > defer > ask > allow** **[V]**.
- The default hook timeout is 600 s for most events. A timed-out `PreToolUse` callback means the tool does not run **[V]**.

### 1.7 Streaming and live status
- The SDK yields typed messages: `AssistantMessage` (content blocks including `ToolUseBlock`, `usage`, `message_id`, `parent_tool_use_id`), `ResultMessage`, `SystemMessage`, `RateLimitEvent`, `TaskStarted/Progress/NotificationMessage`, and `StreamEvent` (raw API stream events, only when `include_partial_messages=True`) **[V Python ref]**. These are enough to drive Repro's `agent.state` events.
- `include_hook_events=True` adds hook lifecycle events to the stream **[V]**.
- The SDK also inherits OpenTelemetry configuration from env vars (`CLAUDE_CODE_ENABLE_TELEMETRY=1`, `OTEL_*`). Traces need `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` **[V hosting]**.

### 1.8 Cost, usage, budgets
- `ResultMessage.total_cost_usd` and `model_usage`: the docs say these are "client-side estimates, not authoritative billing data… Do not bill end users" **[V cost-tracking]**.
- `usage` excludes subagents. Use `model_usage` (which includes subagents) for accounting. Deduplicate per-step usage by `message_id`. Per-step `output_tokens` is a placeholder, so read output tokens from the result **[V]**.
- `max_budget_usd` stops the run with `error_max_budget_usd`. It can overshoot **[V]**.
- Other caps: `max_turns`, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` (default 3) and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (default 20) **[V subagents]**.

### 1.9 Models and selection
- Set the model with `model` (an alias such as `"sonnet"` or a full ID), plus `fallback_model`, `effort` (`low` through `max`) and `thinking` **[V Python ref]**.
- Current models **[V models overview, pricing]**:

| Model | API ID | $/MTok in / out | Default effort | Positioning (Anthropic) |
|---|---|---|---|---|
| Claude Fable 5.1 | `claude-fable-5-1` | 10 / 50 | high | "demanding reasoning and long-horizon agentic work" |
| Claude Opus 5.5 | `claude-opus-5-5` | 4 / 20 | **medium** | "long-running agentic coding and knowledge work"; Anthropic's recommended starting point |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | 2 / 10 | high | "best combination of speed and intelligence" |
| Claude Haiku 5.5 | `claude-haiku-5-5` | 0.10 / 0.50 (≤100K-token prompts); 0.50 / 2.50 above that | medium | "classification, extraction, and routing" |

  All four have a 1M-token context and 128K max output. Batch is 50% off. Thinking is adaptive, and is always on for Opus 5.5 and Fable 5.1 **[V]**.
- Anthropic's eval guide: "Generally best practice to use a different model to evaluate than the model used to generate the evaluated output" **[V develop-tests]**.

### 1.10 Concurrency and hosting
- "One agent session maps to one subprocess." The docs give **"1 GiB RAM, 5 GiB disk, and 1 CPU per agent"** as a starting floor, with memory growing as the session runs **[V hosting]**.
- There is no top-level session timeout, so use `max_turns`. Wide parallel fan-outs can hit rate limits **[V]**.
- Give each concurrent session its own `cwd` **[V]**.
- With Repro's planned default of 12 concurrent agents, that floor is roughly 12 GiB of RAM.

### 1.11 Update for G01 (2026-10-15)
- **0.2.167**, released 2026-10-14, is the latest release, under MIT **[V PyPI]**. Since 0.2.165,
  0.2.166 added typed hook inputs and outputs and `SystemInitData`, fixed the type of
  `SandboxSettings.ignoreViolations`, and bundled CLI 2.1.299; 0.2.167 bundles CLI **2.1.300**
  **[V CHANGELOG]**.
- `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` takes "a positive whole number in plain digits;
  anything else is ignored", and 1 turns nesting off; `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`
  is the same. `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` keeps every CLAUDE.md (user, project, auto
  memory) out of context **[V env-vars]**.
- After an error result (`error_max_turns`, ...) the CLI exits non-zero and the SDK raises
  `ResultError`, which carries the result's subtype, errors and `terminal_reason`, after the
  `ResultMessage` itself has been yielded **[V SDK source, `_errors.py`, `_internal/query.py`]**.
- Measured with CLI 2.1.300 against a local stand-in for the Messages API
  (`engine/tests/test_agents_cli.py`), not documented:
  - `output_format` reaches the model as a tool named `StructuredOutput` whose input schema is
    the output schema. A text answer is re-prompted once, then ends as `success` with no
    `structured_output`; an answer that breaks the schema ends as
    `error_max_structured_output_retries` after five requests in all.
  - With `system_prompt` as a file, the system prompt is the SDK's one-line preamble ("You are a
    Claude agent, built on Anthropic's Claude Agent SDK.") and the file's text; the CLI adds an
    environment block (working directory, platform, OS version, date) as a message.
  - An unlocked CLI (`setting_sources` naming user, project and local) loads a `CLAUDE.md` from
    the `cwd`'s ancestors, runs the project's hooks only when the `cwd` is the project, and loads
    the `CLAUDE.md` and hooks of the `CLAUDE_CONFIG_DIR` directory.

---

## 2. Evidence-cited LLM verdicts and judge reliability

### 2.1 Anthropic Citations and search results
- **Citations (GA, all active models).** Set `citations:{enabled:true}` on `document` blocks: plain text, PDF, or custom content. Custom content is cited at block level with no further chunking **[V citations]**.
- The API returns `cited_text` with char, page or block locations. Docs: "citations are guaranteed to contain valid pointers to the provided documents" **[V]**.
- `cited_text` does not count toward output tokens **[V]**.
- **Citations and structured outputs (`output_config.format`) are incompatible: using both returns a 400** **[V]**.
- **`search_result` content blocks** take `source`, `title`, `content[]` and `citations`. They can be returned **from tool results** or sent as top-level content. Citations come back as `search_result_location` with `source`, `search_result_index` and `start_block_index`/`end_block_index`. No beta header is needed **[V search-results]**. In Repro, `source` could hold an evidence ID such as `ev_…`.
- **Agent SDK caveat:** the Python in-process `@tool` result supports only `text`, `image`, `audio`, `resource` and `resource_link` content **[V custom-tools]**. Whether an Agent SDK tool can return `search_result` blocks is **[U]**. Assume API-level Citations are **not available** through Agent SDK custom tools.

### 2.2 Anthropic grounding guidance
- **Reduce hallucinations [V]:**
  - Allow "I don't know".
  - Extract word-for-word quotes first.
  - "Verify with citations… If it can't find a quote, it must retract the claim."
  - Best-of-N consistency checks.
  - Restrict the model to the provided material.
- **LLM grading tips [V develop-tests]:**
  - Use detailed, clear rubrics.
  - Make the output "empirical or specific", e.g. correct/incorrect or a 1–5 scale.
  - Grade with thinking on.
  - Prefer code-based grading wherever possible.

### 2.3 Judge biases and mitigations (literature)
- **Zheng et al., NeurIPS 2023 (MT-Bench) [V]:**
  - **Position bias:** GPT-4 gave consistent verdicts when the answer order was swapped in only 65% of cases. Claude-v1 managed 23.8% and favoured the first position 75% of the time.
  - The mitigation is to **judge both orders** and declare a win only if the verdicts agree, otherwise a tie. Few-shot examples raised GPT-4's consistency to 77.5%.
  - **Verbosity bias:** a "repetitive list" padding attack fooled GPT-3.5 and Claude-v1 91.3% of the time and GPT-4 8.7%.
  - **Self-enhancement bias:** GPT-4 rated itself about 10% higher than humans did, Claude-v1 about 25%. The authors call this data inconclusive.
  - **Reasoning/math grading:** GPT-4 failed 70% of math items. Chain-of-thought brought that to 30%, and a **reference-guided judge** to 15%.
  - Agreement with experts was about 85%, against 81% for human–human agreement.
- **Wang et al., 2023, "LLMs are not Fair Evaluators" [V]:** order manipulation flipped the outcome on 66 of 80 queries. Proposed fixes:
  - **Multiple Evidence Calibration:** generate evidence before scoring.
  - **Balanced Position Calibration:** average over both orders.
  - **Human-in-the-loop** review for high-entropy cases.
- **Panickssery, Bowman & Feng, 2024 [V]:** LLM evaluators **recognize and favour their own generations**, and self-recognition ability correlates linearly with self-preference. This applies directly to Repro, where Claude may judge PRs that Claude wrote.
- **Verga et al., 2024, PoLL "Replacing Judges with Juries" [V]:** a panel of smaller models from **different families** beat a single large judge across 6 datasets, showed less intra-model bias, and cost about 7× less.
- **Gu et al., 2024–25, "A Survey on LLM-as-a-Judge" [V abstract]:** a survey covering consistency, bias mitigation and judge-reliability benchmarks.

---

## 3. Attestation and provenance: can a Reproduction Card be an attestation?

### 3.1 in-toto Attestation Framework
- **Layers:** Envelope → Statement → Predicate, plus Bundle. The spec page lists **v1.2** as the latest framework version **[V]**.
- **Statement v1** **[V]**:
  - `_type` is `https://in-toto.io/Statement/v1`.
  - `subject[]` is a list of ResourceDescriptors, and **each must have a `digest`**, e.g. `{"gitCommit": "<sha>"}`. Subjects are matched by digest only.
  - `predicateType` is a TypeURI.
  - `predicate` is optional.
- **Envelope:** DSSE v1.0 is recommended. `payloadType` is `application/vnd.in-toto+json`. Consumers must use `predicateType` from the verified payload rather than the media type **[V]**.
- **Vetted predicates [V]:** SLSA Provenance, SLSA Verification Summary, **Test Result**, **SCAI**, **Simple Verification Result (SVR)**, VULNS, SPDX/CycloneDX, Link, Reference, Release, Runtime Traces.
  - **Test Result** (`https://in-toto.io/attestation/test-result/v0.1`): fields `result` (PASSED/WARNED/FAILED), `configuration[]`, `url`, and `passedTests`/`warnedTests`/`failedTests`. The subject is the tested source **[V]**.
  - **SCAI** (`https://in-toto.io/attestation/scai/v0.3`): `attributes[]`, each with `attribute`, `target`, `conditions` and **`evidence` as a ResourceDescriptor**, plus a `producer` **[V]**. This is the closest vetted shape to "claim + cited evidence".
  - **SVR** (`https://in-toto.io/attestation/svr/v0.2`): `verifier{id, policies[]}`, `timeCreated`, and a `properties[]` list of passing properties scoped to a framework prefix. It notes that an SVR "does not contain enough information to reproduce the result" **[V]**.
- **Custom predicates are allowed and expected.** You are asked to justify why existing predicates don't fit. Guidelines **[V]**:
  - Field names in lowerCamelCase.
  - Clearly named RFC 3339 timestamps, e.g. `verifiedAt`.
  - Follow the parsing rules, including the monotonic principle.
  - Vetting is optional: open a PR and maintainers review it at a meeting.
  - "Your predicate is yours."

### 3.2 SLSA v1.2 and the Verification Summary Attestation (VSA)
- **SLSA v1.2 is the current approved spec**. It has a Build track and a **Source track** **[V]**.
- **VSA** (`predicateType: https://slsa.dev/verification_summary/v1`) **[V]**:
  - Required fields: `verifier.id`, `resourceUri`, `policy.uri`, `verificationResult` (PASSED/FAILED) and `verifiedLevels`.
  - Optional fields: `timeVerified`, `inputAttestations`, `dependencyLevels` and `slsaVersion`.
  - "Users MAY use custom values [in verifiedLevels] but MUST NOT use custom values starting with `SLSA_`."
  - Extension fields must use URI names.
  - Consumers must accept only specific (signer, verifier) pairs.
- The Source track already uses **Source VSAs** whose `verifiedLevels` include org-defined values such as `ORG_SOURCE_STATIC_ANALYSIS`, checked against a revision's `subject.digest` **[V]**. That is exactly the pattern a "Repro verified" property would follow.

### 3.3 Signing and distribution
- **GitHub artifact attestations** use Sigstore **[V]**:
  - Public repos go through the public-good instance and transparency log.
  - Private repos use GitHub's own Sigstore instance, which has *no* transparency log.
  - Attestations alone give "SLSA v1.0 Build Level 2".
  - They are verified with `gh attestation verify … -R org/repo`, plus `--predicate-type` for non-default predicates.
- Plan availability **[S]**: public repos on all current plans; private and internal repos need **GitHub Enterprise Cloud**.
- **`actions/attest@v4`** **[V]**:
  - Supports **custom predicates** through `predicate-type` plus `predicate` or `predicate-path`. The predicate can be up to **16 MB**, with up to 1024 subjects.
  - Needs `id-token: write` and `attestations: write`.
  - `actions/attest-build-provenance` is now a v4 wrapper, and "new implementations should use `actions/attest`".
- **cosign:** `cosign attest` / `attest-blob --predicate … --type <URI>` with CUE or Rego policy checks on the predicate **[V docs + S for `--type` with arbitrary URIs]**. CVE-2026-39395 let `verify-blob-attestation` accept mismatched predicate types before 3.0.6 / 2.6.3 **[S]**.
- **sigstore-python 4.5.0** (Jul 28, 2026): `sigstore attest --predicate-type …` signs DSSE, using ambient OIDC in CI or a browser flow locally **[V]**. The docs only show SLSA types as examples; whether it accepts arbitrary predicate types is **[U]**.

---

## 4. Reporting formats and GitHub delivery

### 4.1 SARIF 2.1.0
- **Status:** "SARIF v2.1.0 Plus Errata 01" (28 Aug 2023), an OASIS Standard incorporating errata to the 27 Mar 2020 standard **[V]**.
- `result.kind` takes `pass`, `open` (insufficient information), `informational`, `notApplicable`, `review` (needs a human) or `fail`, which is the default. `result.level` takes `error`, `warning`, `note` or `none`. Results also carry `guid` and `correlationGuid`, and any object can hold a `properties` bag **[V]**.
- `baselineState` (`new`/`unchanged`/`updated`/`absent`) exists in the spec **[U, not fetched]**.
- **GitHub code scanning:**
  - Accepts SARIF **2.1.0 only**, up to 10 MB gzip **[V]**.
  - Per-file limits: 20 runs per file, 25,000 results per run (only the top 5,000 kept), 1,000 locations per result **[V]**.
  - Each result needs `message.text`, `locations[]` and `partialFingerprints` **[V]**.
  - `runAutomationDetails.id` takes the form `category/run-id` **[V]**.
  - **An alert appears on a PR only if all of its lines are in the diff** **[V]**.
  - Upload with `github/codeql-action/upload-sarif@v4`, which needs `security-events: write` **[V]**.
  - Private and internal repos need GitHub Code Security or Advanced Security **[V]**.

### 4.2 JUnit XML
- "There is no official specification." The common subset is `testsuites > testsuite > testcase` with `failure`, `error` and `skipped` children, `properties`, and `system-out`/`system-err` **[V testmoapp/junitxml]**.
- pytest **9.1.1** (Jun 19, 2026) writes it with `--junit-xml=path`. `record_property` "will break schema verifications". `record_testsuite_property` is schema-compatible **[V]**.

### 4.3 GitHub Checks API, comments and summaries
- **Who can write checks:** only GitHub Apps can create check runs through the REST API **[V]**. In Actions, "`checks: write` permits an action to create a check run" through `GITHUB_TOKEN` **[V workflow syntax]**.
- **Check run limits:**
  - **50 annotations per request.** Make further `PATCH` calls to append more **[V]**.
  - Annotation `message` and `raw_details` up to 64 KB each, `title` up to 255 characters, levels `notice`/`warning`/`failure` **[V]**.
  - Up to 3 requested actions **[V]**.
  - Conclusions: `success`, `failure`, `neutral`, `action_required`, `cancelled`, `skipped` and `timed_out` **[V]**.
  - Up to 1,000 check runs with the same name per suite **[V]**.
  - `output.summary` and `output.text` are limited to **65,535 characters** each **[S, from GHES docs]**.
- **Actions job summary (`GITHUB_STEP_SUMMARY`):** up to **1 MiB per step**, and at most 20 step summaries shown per job **[V]**.
- **PR or issue comment body:** about **65,536 characters**. The API returns "Body is too long" with a 422 **[S, no official doc]**.
- **REST rate limits [V]:**

  | Token / limit type | Limit |
  |---|---|
  | `GITHUB_TOKEN` | 1,000 requests/hour per repo (15,000 on GHEC) |
  | GitHub App installation | 5,000/hour, scaling up to 12,500 (15,000 on GHEC) |
  | Secondary: concurrent requests | 100 |
  | Secondary: points per minute | 900 (writes cost 5) |
  | Secondary: content creation | 80/minute and 500/hour |
- **App vs Action:** GitHub Apps are persistent, have centralized webhooks, fine-grained permissions, and rate limits that scale with the installation. Actions "do not run persistently" and are scoped to the repo **[V]**.

---

## 5. Event envelope standards

### 5.1 CloudEvents
- **Latest release: `ce@v1.0.2`**, published "06 Feb" (the releases page doesn't show the year; 2022 **[U]**). The main branch is `1.0.3-wip`, and `specversion` stays `"1.0"` **[V]**.
- **Required attributes:** `id` (non-empty; **`source`+`id` must be unique**), `source` (URI-reference), `specversion` and `type` (reverse-DNS prefix recommended). **Optional:** `datacontenttype`, `dataschema`, `subject` and `time` (RFC 3339) **[V]**.
- **Attribute names**, including extensions, must use only `[a-z0-9]`, *should* be 20 characters or fewer, and must not be `data` **[V]**. **Values must be scalar types** (Boolean, Integer, String, Binary, URI, URI-ref, Timestamp), so an object such as Repro's `target` cannot be an extension attribute **[V]**.
- **`sequence` extension:** a String compared **lexicographically**, so integers need zero-padding. It is comparable only within the same `source` **[V]**.
- **Distributed Tracing extension:** `traceparent` and `tracestate`, for linking events to OTel traces **[V]**.

### 5.2 OpenTelemetry GenAI
- The GenAI semantic conventions have **moved to `open-telemetry/semantic-conventions-genai`**. The agent-spans document is marked **Development**, i.e. not stable **[V]**.
- Operations include `create_agent`, `invoke_agent`, `invoke_workflow`, `execute_tool`, `plan` and `retrieval`, with attributes such as `gen_ai.operation.name`, `gen_ai.provider.name` and `gen_ai.agent.*` **[V]**.
- The Agent SDK can already export OTel traces, metrics and logs through env vars (§1.7) **[V]**.

### 5.3 Event-sourcing practice (Microsoft Azure Architecture Center) [V]
- The event store is the system of record and should never be updated. Corrections are made with compensating events.
- **Schema evolution options:**
  - Tolerant deserialization: ignore unknown fields and use defaults.
  - **A version identifier in the envelope or the type name.**
  - **Upcasters** that run at deserialization and can be chained, leaving stored events unchanged.
  - In-place migration only as a last resort.
- **Ordering:** a timestamp plus an incremental identifier per entity. Reject duplicates on (entity, event id).
- **Snapshots** every N events are an optimization only; the stream stays the source of truth.
- Consumers must be idempotent: track the last processed sequence number per consumer.
- Greg Young's *Versioning in an Event Sourced System* covers the weak-schema and mapping approach **[S]**.

---

## 6. Schema single source of truth: codegen tooling

| Tool | Current version | Notes |
|---|---|---|
| **json-schema-to-typescript** | **16.0.0** (npm `latest`, Node ≥16) **[V]** | See detail below this table. |
| **datamodel-code-generator** | **0.83.0** (Sep 24, 2026, Py ≥3.10) **[V]** | See detail below this table. |
| **quicktype** | **26.0.0** (npm) **[V]** | Generates many languages from JSON Schema. Its Python output is dataclass-based, not Pydantic **[U]**. |
| **Pydantic** | **2.14.1** (Oct 11, 2026, Py ≥3.10) **[V]** | Tagged unions with `Field(discriminator='kind')` over `Literal` fields, or `Discriminator`/`Tag`. These are "more performant and more predictable", and the generated JSON Schema includes an OpenAPI-style `discriminator` **[V]**. |
| **TypeSpec** | `@typespec/compiler` **1.17.0** **[V]** | The 1.0 release had stable OpenAPI 3 and JSON Schema emitters **[S]**. The emitter's JSON Schema draft was not confirmed **[U]**. |

**json-schema-to-typescript detail [V README]:**
- Every draft goes through the same draft-4-based pipeline.
- `const` becomes a literal type, and `$defs` is supported.
- **`oneOf` is treated like `anyOf`**, so a `kind`-const discriminated union becomes a TS union that narrows correctly.
- 2020-12 `prefixItems`, `$dynamicRef`, `$anchor`, `dependentSchemas` and similar keywords are ignored or unsupported.
- `tsType` gives an escape hatch for custom types.

**datamodel-code-generator detail [V]:**
- Supports **Draft 4, 6, 7, 2019-09 and 2020-12**, including `prefixItems` and `$defs`.
- Outputs `pydantic_v2.BaseModel`, Pydantic dataclasses, dataclasses, TypedDict or msgspec.
- **`--check` exits 1 and prints a unified diff when the output is stale**. A GitHub Action (check mode by default), pre-commit support and `[tool.datamodel-codegen]` in pyproject are available.
- Its docs list **`discriminator` as OpenAPI-specific**.
- There are known bug reports about discriminators on list-wrapped and aliased fields **[S]**.

**Alternatives [U]:**
- **TypeSpec:** nicer authoring, but it adds a compiler step and still emits JSON Schema.
- **Protobuf/Buf:** strong breaking-change detection with `buf breaking`, but JSON payloads, SQLite JSON storage and Pydantic validation are second-class, and `oneOf` handling is clunky for a JSON-first UI.

---

## 7. SQLite as an append-only event log
- **WAL [V sqlite.org/wal]:**
  - "Readers do not block writers and a writer does not block readers… there can only be one writer at a time."
  - Automatic checkpoints run at 1,000 pages (`wal_autocheckpoint`).
  - **Checkpoint starvation:** WAL grows without bound if there is always an active reader. Fix it with gaps between reads or `SQLITE_CHECKPOINT_RESTART`/`TRUNCATE`.
  - All processes must be **on the same host; WAL doesn't work over network filesystems**.
  - WAL mode persists on the database file.
  - `synchronous=NORMAL` in WAL drops the per-commit sync. After a power loss the latest transactions may roll back, but the database is not corrupted.
- **Transactions [V lang_transaction]:**
  - Upgrading a DEFERRED read to a write can fail immediately with `SQLITE_BUSY`.
  - `BEGIN IMMEDIATE` takes the write lock up front.
  - IMMEDIATE and EXCLUSIVE behave the same in WAL mode.
- **Throughput [V FAQ]:** "SQLite will easily do 50,000 or more INSERT statements per second… but only a few dozen transactions per second" on rotating disks. A 2024 note adds that it now does "far more than 50K inserts/second", and "putting multiple operations inside a single transaction can improve performance dramatically". This was the only sourced figure found.
- **Python `sqlite3` [V]:**
  - `check_same_thread=True` by default.
  - The `autocommit` attribute (3.12+) should be set to `False` for PEP 249 behaviour. The default is still `LEGACY_TRANSACTION_CONTROL`.
  - `timeout` defaults to 5.0 s.
  - `threadsafety` reflects the compile mode.
- **aiosqlite 0.22.1** (Dec 23, 2025): "a single, shared thread per connection" running a request queue **[V]**. It has no real write concurrency; it bridges to asyncio.
- **JSON [V json1]:** built in since **3.38.0**, including `->` and `->>`. **JSONB** arrived in **3.45.0**. `json_each` and `json_valid` are available. The local Python's SQLite 3.45.1 has all of these **[V local]**.

## 8. FastAPI + WebSockets
- **FastAPI 0.143.0** (Oct 8, 2026, Py ≥3.10) and **uvicorn 0.54.0** (Sep 25, 2026) **[V PyPI]**.
- FastAPI WebSockets use `@app.websocket` with `accept`, `receive_*` and `send_*`, raise `WebSocketDisconnect`, and support dependencies. The in-memory `ConnectionManager` example "will only work with a single process" **[V]**.
- **uvicorn WebSocket defaults [V]:** `--ws auto`, `--ws-max-size 16777216`, `--ws-max-queue 32`, `--ws-ping-interval 20`, `--ws-ping-timeout 20`, `--ws-per-message-deflate True`.
- **Backpressure in `websockets` [V]:**
  - In asyncio, `send()` "waits until [the write buffer] drains under the low-water mark".
  - The `max_queue` incoming buffer applies TCP backpressure.
  - For broadcast, a naive loop stalls on the slowest client.
  - Recommended patterns: **per-client queue + relay task**, or **disconnect clients that fall too far behind**.
  - `broadcast()` applies no backpressure.
- **Replay-then-live:**
  - The KurrentDB "catch-up subscription" reads history from a position (*exclusive*) and then switches to live pushes, with a `CaughtUp` marker. A client that can't keep up gets its subscription dropped and resubscribes from its last stored position **[S]**.
  - SSE's `Last-Event-ID` is the standard resume-from-id model **[V WHATWG]**.

---

## Recommendations for Repro

### A. Agent design (Claude Agent SDK)
1. **Pin `claude-agent-sdk==0.2.165`** (bundled CLI 2.1.294) in `engine/pyproject.toml` and review the CHANGELOG before minor bumps. Use `query()` for one-shot Reader, Reviewer and QA calls. Use `ClaudeSDKClient` only where you need `interrupt()` for the UI's cancel button.
2. **Give reviewers no built-in tools.** Use `tools=[]` with an in-process server `mcp_servers={"repro": server}`, and grant `allowed_tools=["mcp__repro__*"]` and `permission_mode="dontAsk"`. Suggested tools, all `readOnlyHint=True` and all reading only from Repro's own store with server-side path normalisation:
   - `list_evidence(claim_id)`
   - `get_evidence(ev_id)` (returns a rendered, size-capped text view)
   - `read_snippet(side, path, start, end)`
   - `get_diff(path)`
   
   No Bash means the missing Windows sandbox doesn't matter. No Read or Grep means no network-path reads and no stray file access. Add a `PreToolUse` hook that denies anything not starting with `mcp__repro__`, as defence in depth (a hook deny wins in every mode).
3. **Treat PR content as hostile.**
   - Set `setting_sources=[]`.
   - In `env`, set `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` and a per-run `CLAUDE_CONFIG_DIR`. Also set `strict_mcp_config=True`.
   - Set `verbatim_prompts=True`.
   - Use `cwd` = an empty per-run Repro scratch directory, **never the PR worktree**.
   - Pass the system prompt as a file, because of the Windows ~32 KB command-line cap.
   - Wrap PR text in clearly delimited `<untrusted_pr_description>` blocks, and tell the model that this text is *claims to be checked, not instructions*.
4. **Make citations valid by construction, then verify:**
   - Build each reviewer's `output_format` schema **per claim**. `cited_evidence: {type:"array", minItems:1, items:{enum:[…valid ev_ ids for this claim…]}}` is the shape. Add `verdict: enum["verified","flagged","unverifiable"]`, a `quotes[]` array of `{ev_id, text}`, and `rationale`.
   - The SDK re-prompts on validation failure. Map `error_max_structured_output_retries`, or `success` with `structured_output=None`, to an explicit **missing** card item (ground rule 3).
   - Post-check in `review.py`: every ID exists, belongs to the claim's targets, and **each quote is an exact substring of the rendered evidence**. This does mechanically what the Citations API guarantees on the raw API.
   - Do not include `$schema` in these schemas. Inline the `$ref`s, because the SDK validates as draft-07.
5. **Bias controls, scaled to cost:**
   - **Order:** render evidence in a fixed, sorted-by-ID order, and present base and head in a neutral form (`A`/`B` with a legend), not "before/after" prose. For flagged or close calls, run a second pass with the order swapped and only keep `flagged` if both runs agree, otherwise `unverifiable` (Zheng; Wang BPC).
   - **Reference-guided:** give the judge the deterministic diff outcome as the reference, and ask it only to say whether the *claim's wording* is supported (Zheng: 70% → 15% error).
   - **Verbosity:** cap PR text length fed to the judge, and judge per atomic claim rather than per whole description.
   - **Self-preference:** if the PR author is Claude, judge with a different tier (e.g. Opus 5.5 judging Sonnet-written PRs). Make the deterministic evidence the deciding input, which is what Repro is built on.
   - **Panel:** for `flagged` verdicts, require 2 of 3 independent judges (different model and effort). Log agreement per run, and calibrate against the M8 seeded benchmark by measuring the false-flag and false-verify rates for each verdict class.
6. **Models (configurable via env):**
   - Reader (claim extraction): `claude-haiku-5-5`, with a `claude-sonnet-5-5` fallback.
   - Reviewers: `claude-opus-5-5` with `effort="high"` set explicitly, because Opus 5.5 defaults to `medium`.
   - QA and tie-breaks: `claude-opus-5-5`. Use `claude-fable-5-1` only on demand.
   - Always set `max_turns`, `max_budget_usd`, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=1` and `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`.
   - Record `model_usage` as `cost.estimate` events labelled "estimate".
7. **Concurrency:** about 1 GiB per SDK subprocess means **12 concurrent agents needs about 12 GiB**. Make the default `min(12, floor(free_RAM_GiB))`, with 4 as a Windows-laptop default, and queue the rest. The UI can still show 12 slots, with queued agents shown as `idle`.
8. **Stack question to put to the user (ground rule 7):** reviewers don't need Claude Code's built-in tools. Calling the **Anthropic client SDK** directly for reviewers would give:
   - Constrained-decoding structured outputs, or alternatively `search_result` citations (the two can't be combined).
   - No per-agent ~1 GiB subprocess.
   - No CLI binary dependency.

   This changes the decided stack, so ask before doing it. In the meantime, keep the Agent SDK and use the dynamic-enum schema from A4.

### B. Card as attestation: yes, as an optional export, with clear semantics
- Emit the card as an **in-toto Statement v1**:
  - `subject`: `[{name:"head", digest:{gitCommit:<head_sha>}}]`, with the base commit, repo URL and PR number recorded inside the predicate.
  - `predicateType`: a Repro-owned URI such as `https://repro.dev/attestation/reproduction-card/v0.1`, or a GitHub-hosted spec URL until a domain exists.
- Predicate contents, following SCAI's shape and in-toto style (lowerCamelCase field names, `verifiedAt` RFC 3339 timestamps):
  - `claims[]`, each with `verdict`, `evidence[]` as **ResourceDescriptors (`name: ev_…`, `digest.sha256` of the raw artifact, `uri`)**, and the judge models.
  - `missing[]`
  - `invariants[]`
  - `environment` (Python version, lockfile digests, Repro version, seed)
  - `eventLog: {digest, count}`, so a verifier can replay.
- Do **not** reuse the SLSA VSA as the card itself: its PASSED/FAILED plus levels can't express per-claim verdicts. *Optionally* also emit a tiny VSA- or SVR-style summary with `verifiedLevels`/`properties` such as `REPRO_CLAIMS_VERIFIED` and `REPRO_NO_UNEXPLAINED_GAPS`. Don't start any value with `SLSA_`. This matches how the SLSA Source track already uses `ORG_*` properties on commits.
- Raw test runs can additionally be emitted as **test-result v0.1** attestations, one per side.
- **Signing:**
  - Local runs: unsigned JSON, or an unsigned DSSE envelope. Never imply trust that isn't there.
  - CI: `actions/attest@v4` with `predicate-type` and `predicate-path`. The predicate must be 16 MB or less. Needs `id-token: write` and `attestations: write`. Private repos need GHEC **[S]**.
  - Verify with `gh attestation verify --predicate-type <uri>`.
- Document plainly that the attestation proves *who ran what and observed what*. It does not prove correctness, and LLM verdicts are labelled as judgments.

### C. Export formats (in priority order)
1. **Markdown PR comment and job summary.**
   - One **sticky comment**, found and updated by a hidden marker such as `<!-- repro:card run=… -->` **[U practice]**.
   - Keep it under 60,000 characters and link the full card artifact. Put details in collapsible `<details>` blocks.
   - In Actions, also write the same Markdown to `GITHUB_STEP_SUMMARY`, which allows 1 MiB.
2. **GitHub Check run** named `Repro`, using `checks: write` from `GITHUB_TOKEN` in Actions or from an App:
   - Card status → conclusion: verified → `success`, flagged → `failure` or `action_required` (configurable), unverifiable or missing → `neutral`, which is never `success` (ground rule 3).
   - Summary up to about 65K characters. Annotations sent in batches of 50 per PATCH.
3. **SARIF 2.1.0** for code scanning, so flagged claims appear inline:
   - Flagged → `kind:"fail"`, `level:"warning"/"error"`.
   - Unverifiable → `kind:"open"`.
   - Needs a human → `kind:"review"`.
   - Verified → `kind:"pass"`, kept out of the upload by default.
   - Set `partialFingerprints` = hash(claim text + target), `runAutomationDetails.id="repro/<category>"`, and evidence IDs in `properties`.
   - Inline alerts appear only on changed lines, and private repos need GHAS or Code Security. Treat SARIF as optional.
4. **JUnit XML:** one `testcase` per claim. Flagged → `<failure>`, unverifiable → `<skipped message="…">`. This plugs into any CI dashboard. Separately, *ingest* the target's own pytest JUnit with `--junit-xml`, without `record_property`.
5. **in-toto attestation** as in §B.
- **Delivery vehicle:** ship a **GitHub Action first** (no infrastructure; 1,000 req/h/repo is plenty). Move to a **GitHub App** at M-later for org-wide use, persistent webhooks, rate limits that scale, and an "Re-run Repro" requested-action button (at most 3 buttons). Respect the secondary limit of 80 content-creating requests per minute: update the comment and the check, don't post new ones.

### D. Event envelope tweaks and CloudEvents mapping
Keep the core fields; they are user-protected. Propose these **additive** fields to the user:
- `v`: envelope schema version, e.g. `1`.
- `pv`: per-kind payload schema version, which upcasters dispatch on.
- `parent`: optional event ID, for causation such as tool call → agent.
- `producer`: Repro engine version plus the git SHA of the engine.

Lossless CloudEvents 1.0 JSON mapping (export or adapter, not the storage format):

| Repro | CloudEvents | Notes |
|---|---|---|
| `id` (`evt_<ULID>`) | `id` | Unique within source |
| `run_id` | `source` = `/repro/runs/<run_id>` **and** ext `runid` | Per-run source makes `sequence` meaningful |
| `seq` | ext `sequence` = zero-padded string (e.g. 12 digits) | Lexicographic by spec |
| `ts` | `time` | RFC 3339 |
| `kind` | `type` = `dev.repro.<kind>` (e.g. `dev.repro.test.finished`) | Reverse-DNS |
| `stage`, `agent`, `status` | ext `stage`, `agent`, `status` | Lowercase, ≤20 chars, scalar |
| `target` (object) | `subject` = canonical string (`file::symbol` or test nodeid) **plus** full object inside `data` | Extensions can't be objects |
| `payload` | `data` (+ `datacontenttype: application/json`) | |
| `pv` | `dataschema` = `https://…/schemas/<kind>/v<pv>.json` | |
| `v` | n/a, implied by `specversion` mapping | |

- **OTel:** skip it for the MVP. The GenAI conventions are still *Development*, and the event log already serves as the trace. Later, add an optional exporter that projects `stage` → span, agent → `invoke_agent` span and tool call → `execute_tool` span. At that point, set the Agent SDK `OTEL_*` env vars and the CloudEvents `traceparent` extension.
- **Event-sourcing hygiene:**
  - Events are immutable; corrections are compensating `*.retracted` events.
  - Use the `UNIQUE(run_id, seq)` constraint.
  - Upcasters live next to the schema package and are keyed by `(kind, pv)`.
  - Cards and graph views are **projections** that can be rebuilt from events, so no snapshots are needed: runs are thousands of events, not millions.

### E. Codegen toolchain
- Write the source of truth as **JSON Schema 2020-12** in `packages/events/schema/`: one file per payload `kind`, plus `envelope.json` with a `oneOf` over `{kind: {const: …}, payload: {$ref}}`.
- **TypeScript:** `json-schema-to-typescript@16.0.0`. `const` produces literal types, and `oneOf` produces a union, so `switch(ev.kind)` narrows correctly. Avoid `prefixItems`, `$dynamicRef` and `$anchor`.
- **Python:** `datamodel-code-generator==0.83.0` with `--output-model-type pydantic_v2.BaseModel` and pydantic 2.14.x. Because `discriminator` is OpenAPI-only in its docs, use a ~30-line generator step to emit the envelope union as `Annotated[Union[...], Field(discriminator="kind")]`, and test it. Don't rely on codegen discriminator support for JSON Schema input **[U]**.
- **CI drift gates:**
  - `datamodel-codegen --check`, which fails with a diff.
  - Regenerate TS, then `git diff --exit-code`.
  - Validate golden fixtures and recorded replay logs against the schemas in both languages.
  - An "every `kind` has a schema" test.
- **Agent output schemas** (claims, verdicts) live in the same package. Export a **draft-07-compatible, `$ref`-free** variant for `output_format`.
- Not recommended now: TypeSpec (an extra compiler, and the emitter's draft is unconfirmed) and Protobuf/Buf (a poor fit for JSON payloads, SQLite JSON and Pydantic).

### F. Storage and transport
- **SQLite settings:**
  - At open: `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=5000; foreign_keys=ON`.
  - Use **`BEGIN IMMEDIATE`** for writes.
  - Keep the DB under `~/.repro` on a local disk, never a network share.
- **One writer task:**
  - Producers put events on an `asyncio.Queue`.
  - The writer batches up to N events or 20–50 ms into one transaction, assigns `seq` inside it, commits, and only then publishes to subscribers.
  - Use stdlib `sqlite3` on a dedicated writer thread with `autocommit=False` (Python 3.12+). aiosqlite 0.22.1 is equally fine; it is also thread-per-connection.
  - Readers (replay, API) use separate read-only connections.
  - Run `PRAGMA wal_checkpoint(TRUNCATE)` at run end, which avoids checkpoint starvation from long replays.
- **Schema and indexes:**
  - Table `events(run_id, seq, id, ts, stage, agent, kind, status, target_json, payload_json, v, pv)` with `PRIMARY KEY(run_id, seq)` and `UNIQUE(id)`.
  - Add expression indexes on `payload_json ->> '$.ev_id'` and `$.claim_id` where needed. The JSON functions are verified **[V]**; expression indexes over them are **[U]** but standard.
- **WebSocket replay-then-live, gap-free:**
  1. Register the client's bounded queue on the live bus **first**.
  2. Stream `SELECT … WHERE run_id=? AND seq > :from ORDER BY seq` in pages. `from` is exclusive, like `Last-Event-ID`.
  3. Drain the queue, dropping `seq ≤ last_sent`.
  4. Send a `{type:"caught_up", seq}` frame (the KurrentDB `CaughtUp` analogue).
- **Backpressure:**
  - Give each client an `asyncio.Queue(maxsize≈1000)` and a relay task.
  - If the queue overflows, **close with code 1013 or 4000 and a "resync" reason**. The UI reconnects with `?from=<last_seq>`. The replay is lossless because the DB is authoritative.
  - Never apply server backpressure to the engine. The writer must not wait on clients.
  - Batch frames (e.g. arrays of events every 16–33 ms) so `trace.sample` and `log.line` bursts don't produce one frame per event.
  - Keep uvicorn's defaults: 16 MiB max message, 20 s ping/timeout.
  - Consider `--ws-per-message-deflate False` for CPU savings on localhost **[U]**.
- **Versions to pin today:**

  | Package | Version | Released |
  |---|---|---|
  | fastapi | 0.143.0 | Oct 8, 2026 |
  | uvicorn | 0.54.0 | Sep 25, 2026 |
  | pydantic | 2.14.1 | Oct 11, 2026 |
  | claude-agent-sdk | 0.2.165 | Oct 8, 2026 |
  | datamodel-code-generator | 0.83.0 | Sep 24, 2026 |
  | pytest | 9.1.1 | Jun 19, 2026 |
  | json-schema-to-typescript (npm) | 16.0.0 | not checked |

---

## Sources
All accessed 2026-10-13.

| # | URL | Tag |
|---|---|---|
| 1 | https://pypi.org/project/claude-agent-sdk/ | V |
| 2 | https://github.com/anthropics/claude-agent-sdk-python | V |
| 3 | https://github.com/anthropics/claude-agent-sdk-python/blob/main/CHANGELOG.md | V |
| 4 | https://code.claude.com/docs/en/agent-sdk/overview | V |
| 5 | https://code.claude.com/docs/en/agent-sdk/quickstart | V |
| 6 | https://code.claude.com/docs/en/agent-sdk/python | V |
| 7 | https://code.claude.com/docs/en/agent-sdk/custom-tools | V |
| 8 | https://code.claude.com/docs/en/agent-sdk/permissions | V |
| 9 | https://code.claude.com/docs/en/agent-sdk/structured-outputs | V |
| 10 | https://code.claude.com/docs/en/agent-sdk/hooks | V |
| 11 | https://code.claude.com/docs/en/agent-sdk/hosting | V |
| 12 | https://code.claude.com/docs/en/agent-sdk/cost-tracking | V |
| 13 | https://code.claude.com/docs/en/agent-sdk/subagents | V |
| 14 | https://code.claude.com/docs/en/agent-sdk/claude-code-features | V |
| 15 | https://code.claude.com/docs/en/sandboxing | V |
| 16 | https://platform.claude.com/docs/en/about-claude/models/overview | V |
| 17 | https://platform.claude.com/docs/en/about-claude/pricing | V |
| 18 | https://platform.claude.com/docs/en/build-with-claude/structured-outputs | V |
| 19 | https://platform.claude.com/docs/en/build-with-claude/citations | V |
| 20 | https://platform.claude.com/docs/en/build-with-claude/search-results | V |
| 21 | https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-hallucinations | V |
| 22 | https://platform.claude.com/docs/en/test-and-evaluate/develop-tests | V |
| 23 | https://arxiv.org/html/2306.05685v4 (Zheng et al., MT-Bench / LLM-as-a-judge) | V |
| 24 | https://arxiv.org/abs/2305.17926 (Wang et al., LLMs are not Fair Evaluators) | V |
| 25 | https://arxiv.org/abs/2404.13076 (Panickssery et al., self-preference) | V |
| 26 | https://arxiv.org/abs/2404.18796 (Verga et al., PoLL) | V |
| 27 | https://arxiv.org/abs/2411.15594 (Gu et al., Survey on LLM-as-a-Judge) | V (abstract) |
| 28 | https://github.com/in-toto/attestation/tree/main/spec | V |
| 29 | https://raw.githubusercontent.com/in-toto/attestation/main/spec/v1/statement.md | V |
| 30 | https://raw.githubusercontent.com/in-toto/attestation/main/spec/v1/envelope.md | V |
| 31 | https://github.com/in-toto/attestation/blob/main/spec/predicates/README.md | V |
| 32 | https://github.com/in-toto/attestation/blob/main/spec/predicates/test-result.md | V |
| 33 | https://github.com/in-toto/attestation/blob/main/spec/predicates/svr.md | V |
| 34 | https://raw.githubusercontent.com/in-toto/attestation/main/spec/predicates/scai.md | V |
| 35 | https://github.com/in-toto/attestation/blob/main/docs/new_predicate_guidelines.md | V |
| 36 | https://slsa.dev/spec/ | V |
| 37 | https://slsa.dev/spec/v1.1/verification_summary | V |
| 38 | https://slsa.dev/spec/v1.2/verifying-source | V |
| 39 | https://docs.github.com/en/actions/concepts/security/artifact-attestations | V |
| 40 | https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations | V |
| 41 | https://github.com/actions/attest | V |
| 42 | https://github.com/actions/attest-build-provenance | V |
| 43 | GitHub plan availability for attestations (search snippets of docs.github.com + github.blog) | S |
| 44 | https://docs.sigstore.dev/cosign/verifying/attestation/ | V |
| 45 | cosign `attest-blob --type` usage, CVE-2026-39395 (search snippets incl. nvd.nist.gov/vuln/detail/CVE-2026-39395) | S |
| 46 | https://pypi.org/project/sigstore/ | V |
| 47 | https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html | V (partial) |
| 48 | https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/sarif-support-for-code-scanning | V |
| 49 | https://docs.github.com/en/code-security/code-scanning/integrating-with-code-scanning/uploading-a-sarif-file-to-github | V |
| 50 | https://github.com/testmoapp/junitxml | V |
| 51 | https://docs.pytest.org/en/stable/how-to/output.html | V |
| 52 | https://pypi.org/project/pytest/ | V |
| 53 | https://docs.github.com/en/rest/checks/runs | V |
| 54 | https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks | V |
| 55 | Check-run summary 65,535-char limit (search snippets of docs.github.com/en/enterprise-server@3.13/rest/checks/runs) | S |
| 56 | https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands | V |
| 57 | https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax | V |
| 58 | Comment body 65,536 limit (search snippets: github.community, golang.org/issue/45998) | S |
| 59 | https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api | V |
| 60 | https://docs.github.com/en/apps/creating-github-apps/about-creating-github-apps/deciding-when-to-build-a-github-app | V |
| 61 | https://raw.githubusercontent.com/cloudevents/spec/main/cloudevents/spec.md | V |
| 62 | https://github.com/cloudevents/spec/releases | V |
| 63 | https://raw.githubusercontent.com/cloudevents/spec/main/cloudevents/extensions/sequence.md | V |
| 64 | https://raw.githubusercontent.com/cloudevents/spec/main/cloudevents/extensions/distributed-tracing.md | V |
| 65 | https://opentelemetry.io/docs/specs/semconv/gen-ai/ (moved notice) | V |
| 66 | https://github.com/open-telemetry/semantic-conventions-genai | V |
| 67 | https://github.com/open-telemetry/semantic-conventions-genai/blob/main/docs/gen-ai/gen-ai-agent-spans.md | V |
| 68 | https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing | V |
| 69 | https://leanpub.com/esversioning/read (Greg Young), InfoQ summary | S |
| 70 | https://registry.npmjs.org/json-schema-to-typescript/latest | V |
| 71 | https://github.com/bcherny/json-schema-to-typescript | V |
| 72 | https://pypi.org/project/datamodel-code-generator/ | V |
| 73 | https://github.com/koxudaxi/datamodel-code-generator | V |
| 74 | https://datamodel-code-generator.koxudaxi.dev/supported_formats/ | V |
| 75 | https://datamodel-code-generator.koxudaxi.dev/ci-cd/ | V |
| 76 | https://datamodel-code-generator.koxudaxi.dev/cli-reference/ | V |
| 77 | datamodel-code-generator discriminator issues (polar.sh / codspeed snippets) | S |
| 78 | https://registry.npmjs.org/quicktype/latest | V |
| 79 | https://registry.npmjs.org/@typespec/compiler/latest | V |
| 80 | https://typespec.io/blog/typespec-1-0-GA-release/ (via search) | S |
| 81 | https://pypi.org/project/pydantic/ | V |
| 82 | https://pydantic.dev/docs/validation/latest/concepts/unions/ | V |
| 83 | https://www.sqlite.org/wal.html | V |
| 84 | https://www.sqlite.org/faq.html | V |
| 85 | https://www.sqlite.org/lang_transaction.html | V |
| 86 | https://sqlite.org/json1.html | V |
| 87 | https://docs.python.org/3/library/sqlite3.html | V |
| 88 | https://pypi.org/project/aiosqlite/ | V |
| 89 | https://pypi.org/project/fastapi/ | V |
| 90 | https://fastapi.tiangolo.com/advanced/websockets/ | V |
| 91 | https://pypi.org/project/uvicorn/ | V |
| 92 | https://raw.githubusercontent.com/encode/uvicorn/master/docs/settings.md | V |
| 93 | https://websockets.readthedocs.io/en/stable/topics/memory.html | V |
| 94 | https://websockets.readthedocs.io/en/stable/topics/broadcast.html | V |
| 95 | https://docs.kurrent.io/clients/python/v1.1/subscriptions (and other client versions, via search) | S |
| 96 | https://html.spec.whatwg.org/multipage/server-sent-events.html | V |

Gaps: the web-search budget ran out near the end. These items are still **[S]** or **[U]**:
- The check-run summary limit, the comment-body limit, and attestation plan availability.
- Whether datamodel-codegen honours JSON-Schema `discriminator`.
- The draft version the TypeSpec JSON Schema emitter outputs.
- Whether Agent SDK tools can return `search_result` blocks.
- SARIF `baselineState`.
