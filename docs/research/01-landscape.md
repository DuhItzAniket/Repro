<!-- Research notes compiled 2026-10-13 with AI-assisted web research and reviewed by the maintainers. Every claim carries a verification tag ([V]/[S]/[U]); re-verify against the primary source before citing in publications. -->

# Repro: the commercial and open-source tool landscape (research pass 1)

All sources were accessed on **2026-10-13**. The research ran as four parallel tracks: AI reviewers, execution and verification tools, orchestrators and observability, and adoption and trust stats. Every track used the same tagging rules.

**Tags**
- **[V]**: the primary source was fetched and the claim seen there. A few openai.com pages returned HTTP 403 to the fetcher and were read in a browser instead. Those are marked "[V, browser]".
- **[S]**: seen only in a search snippet or a secondary source, which is named.
- **[U]**: unverified, or general knowledge.

When this document says a vendor page is "not documented", it means the vendor's primary page was read and says nothing either way. That is not proof the feature is missing.

---

## 0. TL;DR, the six facts that matter for Repro

1. **The blanket claim "AI reviewers read the diff; Repro runs it" is no longer true.** Several reviewers now execute code:
   - **OpenAI Codex code review** (since Sep 2025) says it "matches the stated intent of a PR to the actual diff … and executes code and tests to validate behavior" [V, browser].
   - **Greptile TREX** (public beta, Jun 15 2026) "spins up a sandbox, runs the relevant code". It writes and runs targeted tests and attaches logs, screenshots, API traces, scripts and video to its comments [V].
   - **Claude Code ultrareview** runs a fleet of reviewers in a cloud sandbox. It says "every reported finding is independently reproduced and verified" [V].
   - **Ito** builds a sandboxed copy of the app per PR and posts video, logs and repro steps, saying what was mocked [V].
   - **QA.tech** tests each PR's preview deploy and posts a verdict, including **"unverified" when the tests never exercised the change** [V].
   - **Qodex.ai** runs API, UI and security scenarios against each PR's preview deploy and attaches the failing request, response or screenshot [V].
   - **Jazzberry** clones the PR into a microVM and writes and executes code to hunt bugs [V].
2. **Base-vs-head behaviour diffing already exists, but only in pieces:**
   - **Meticulous** runs UI replays on base and head and posts pixel diffs to the PR. It raised $15M in Jul 2026 [V].
   - **Signadot**, **Curtail ReGrade**, **Speedscale**, **Keploy** and **Diffy** diff HTTP or API responses between baseline and candidate [V].
   - **Testora** (Pradel, ICSE '26) runs LLM-generated tests on the old and new versions of **Python PRs** and has an LLM decide whether each difference was *intended according to the PR description* [V]. That is Repro's core idea, already published, with MIT code.
   - **Tusk Drift**, the closest commercial backend/Python analogue (traffic replay on every PR, deviation reports), was **sunset on Jun 10 2026** [V].
3. **No source documented the full combination Repro plans.** Nothing found offers all of these together:
   - local-first, isolated worktrees;
   - **function-level** behaviour traces of the blast radius, diffed **base vs head**;
   - API, dependency and performance diffs plus declared invariants;
   - **per-claim** verdicts citing engine evidence IDs, with an explicit *missing* list;
   - a replayable event log.

   Executors find bugs on the head side or test a preview. Their output is a *bug finding*, not a *claim verdict*. This is absence of evidence across roughly 100 primary pages read by the four tracks, not proof of absence.
4. **Agent authors now ship their own "proof of work":**
   - Screenshots and video: Copilot, Codex, Jules, Devin, Cursor and Claude Code Desktop.
   - Deterministic gates: Copilot cloud agent runs CodeQL, dependency checks, secret scanning and a Copilot review. Since **Jun 9 2026** it also runs them on Claude and Codex PRs [V].

   This evidence is produced by the *same* agent that wrote the code, or is generic SAST. It is not an independent behavioural check.
5. **The volume and trust problem is real and documented:**
   - Copilot coding agent opened 1M+ PRs from May to Sep 2025 [V].
   - Copilot code review now handles more than 1 in 5 code reviews on GitHub [V].
   - In the Stack Overflow 2025 survey, 46% distrust AI accuracy against 33% who trust it [V].
   - In the 2026 survey, the top trust answer (48%) is "trust it when I can easily verify the output" [V].
   - Faros found a +91% rise in PR review time on high-AI teams [V].
6. **The market is consolidating fast:**
   - Cursor bought Graphite (Dec 2025) [V].
   - CloudBees bought Launchable (2024), now renamed Smart Tests [V].
   - Tusk sunset (Jun 2026) [V].
   - Sonar bought Gitar (May 2026) [V].
   - Boost Security bought Korbit (May 2026) [V].
   - Cisco bought Galileo (2026) [V].
   - ClickHouse bought Langfuse (Jan 2026) [V].
   - Google shut down the consumer Gemini Code Assist GitHub reviewer (Jul 17 2026) [V].
   - Several orchestrators shut down: Terragon, Crystal and Vibe Kanban's company [V].

---

## 1. Comparison table

Column key:
- **Exec?** Does it execute the PR's code, its tests, or anything in a sandbox?
- **B-vs-H?** Does it compare base against head *behaviour*?
- **Evidence-cited?** Do its verdicts or findings carry concrete execution evidence?

| Tool | Category | Exec? | B-vs-H? | Evidence-cited? | OSS? | Notes |
|---|---|---|---|---|---|---|
| CodeRabbit | AI reviewer | **Partial.** Clones the repo into a sandbox (Cloud Run microVM plus Jailkit), installs dependencies, runs 20+ linters and scanners plus LLM-generated shell or Python "verification scripts". "Fix CI" works in a sandbox (Jul 2026). Running the PR's own test suite is not documented [V] | Not documented [V] | No. A "Verification" agent filters comments [V] | No [U] | Essentials $24, Team $48, Advanced $72 per user/mo, billed annually [V]. $143M Series C at $1.5B, Aug 2026 [S] |
| Graphite Agent (ex-Diamond) | AI reviewer, stacked PRs | Not documented [V] | No | No | No | Cursor deal announced Dec 19 2025 [V]. To merge with Bugbot [V]. Hobby free, Starter $20, Team $40 [V] |
| Greptile (with TREX) | AI reviewer | **Yes** (TREX beta, Jun 2026). Sandbox; writes and runs targeted tests [V] | **Not mentioned** [V] | **Yes, per finding.** Logs, screenshots, API traces, scripts, video [V] | No | Static "blast radius" from a code graph [V]. Pro $30/seat; free Starter [V] |
| Qodo 2.0 (ex-Qodo Merge) | AI reviewer | Not documented for review [V] | No | Agent reasoning per issue, no execution evidence [V] | No | Multi-agent with a judge agent. Self-reported F1 of 60.1% [V] |
| PR-Agent (Qodo, OSS) | AI reviewer (self-host) | No (LLM over PR content) [V] | No | No | **Yes, MIT** [V] | Now a "community-maintained legacy project" [V]. 13.4k stars [V] |
| GitHub Copilot code review | AI reviewer | Agentic tool calls on Actions runners. Playwright MCP is on by default. Running tests is not documented [V] | No | "Approval assessment" (preview) [V] | No | 60M+ reviews; more than 1 in 5 GitHub reviews [V]. Billed in AI credits plus Actions minutes [V] |
| Cursor Bugbot | AI reviewer | Not documented. Autofix spawns a Cloud Agent [V] | No | No | No | Usage-based. Composer 2.5; about 90 s per review (Jun 2026) [V] |
| Claude Code Review (managed) | AI reviewer | "Verification step checks candidates against actual code behavior". Execution is not stated explicitly [V] | No | "Why this was flagged" says how it was verified [V] | No | $15–25 per review, about 20 min. Neutral check run. "Pre-existing" severity [V] |
| Claude Code ultrareview | AI reviewer, on demand | **Yes.** Cloud sandbox; "every reported finding is independently reproduced and verified" [V] | Not documented | Verified findings; `bugs.json` [V] | No | $5–25 per review after 3 free runs [V] |
| Claude Code GitHub Action | Agent in CI | Yes, on your runner, if the prompt allows tools [V] | Only if you script it | No | **Yes, the action is MIT** [V] | Built on the Agent SDK [V] |
| OpenAI Codex code review | AI reviewer | **Yes, per OpenAI.** "executes code and tests to validate behavior" [V, browser] | No, but it **matches PR intent to the diff** [V, browser] | Codex tasks cite terminal logs and test outputs [V, browser] | No (review) | Flags only P0/P1 on GitHub; `AGENTS.md` review rules [V] |
| Sourcery | AI reviewer | Not documented [V] | No | No | No | Pro $15/mo, Team $30/mo [V] |
| Ellipsis | Pivoted to an agent platform | Agents run in a sandbox and can run pytest when prompted [V] | No | No | No | Now "build and run coding agents"; YC [V] |
| CodeAnt AI | AI reviewer, SAST | Not documented | No | No | No | Pricing page now shows only AI Pentesting [V] |
| Korbit | AI reviewer | n/a | n/a | n/a | No | Acquired by Boost Security, announced May 7 2026 [V] |
| Bito | AI reviewer | Not documented [V] | No | No | No | $12–25 per seat; metered by lines [V] |
| Amazon Q Developer for GitHub | AI reviewer | Not documented [V] | No | No | No | Still in **preview** [V] |
| Gemini Code Assist (GitHub) | AI reviewer | n/a | n/a | n/a | No | **Consumer app shut down Jul 17 2026.** No new Std/Ent purchases after Oct 9 2026 [V] |
| Gitar (now Sonar) | AI reviewer, CI fixer | Uses *your* CI. "iterates until your CI passes, then commits only on green" [V] | No | No | No | Acquired by Sonar (announced May 21 2026) [V] |
| Qodex.ai | AI reviewer, E2E tests | **Yes.** Playwright and HTTP scenarios against the per-PR preview or staging URL [V] | No | **Yes.** Failing request, response or screenshot [V] | No | Triages real bug vs stale test vs environment [V] |
| Macroscope | AI reviewer | **No.** Check Run Agents "cannot execute arbitrary code" [V] | No | No | No | Usage-based [V] |
| Jazzberry | AI bug finder | **Yes.** MicroVM; writes and executes code [V] | Not mentioned [V] | Markdown table in the PR [V] | No | Maker now listed as Cartpole (RL environments) [S] |
| Devin Review | AI reviewer | Not documented for review findings [V] | No | No | No | Billed in ACUs [V] |
| **Ito** (ito.ai) | Execution reviewer | **Yes.** A single-use copy of the app per PR in a sandbox; a "swarm of agents" drives the UI, APIs and DB [V] | Not described [V] | **Yes.** Video, screenshots, logs, repro steps; **states what was mocked** [V] | No | Pro $40/mo, 50 reviews per seat [V] |
| **QA.tech** | Execution reviewer (preview env) | **Yes.** Regression and exploratory tests on each PR's preview deploy [V] | Not described [V] | Verdict posted to the PR. **"Unverified" if tests never exercised the change**; pre-existing failures listed separately [V] | No | Checks Linear/Jira acceptance criteria [V] |
| Momentic | E2E against preview | Yes. Diff-selected tests on the preview URL [V] | No | PR status comment [V] | No | |
| Ranger | Agent browser verification | Yes. `ranger go` drives a real browser [V] | No | Screenshots, video, verdicts [V] | No | |
| **Meticulous** | Record and replay UI testing | **Yes.** Replays recorded sessions in a deterministic Chromium [V] | **Yes, base vs head**, as pixel screenshot diffs posted to the PR [V] | Screenshot diffs, approve or reject [V] | Core no; SDK ISC [V] | Frontend only. Raised $15M (Jul 2026) [V] |
| Keploy | API record and replay; OSS | Yes. eBPF capture, replay with mocks; PR Agent generates unit tests [V] | Implicit: new build vs recorded responses [U] | Coverage in CI or PR [V] | **Apache-2.0**, 18.6k stars [V] | Pro $19/user plus usage [V] |
| Speedscale / proxymock | Traffic replay | Yes [V] | **Yes**: new build vs recorded production responses, field-level [V] | Diff reports, latency [V] | CLI proprietary (free for small orgs) [V] | "AI wrote the code. Real traffic decides if it ships." [V] |
| Signadot Smart Tests | Kubernetes traffic diff | Yes [V] | **Yes**: changed service vs baseline; "a model flags meaningful differences" [V] | PR comment summary [V] | No | Kubernetes and microservices only [V] |
| Curtail ReGrade | HTTP diff | Yes [V] | **Yes**: replays against baseline and candidate builds, field-level diff [V] | PR annotations; approve intended changes [V] | No | Blog post Jun 2026 [V] |
| Diffy (twitter, then opendiffy) | Differential proxy | Yes, as a live proxy [V] | **Yes**: candidate vs primary, with a second primary to measure noise [V] | "Safe to ship" or regressions UI [V] | twitter/diffy Apache-2.0, **archived 2020**. opendiffy is **CC BY-NC-ND** [V] | The canonical noise-cancellation design |
| Tusk / Tusk Drift | AI test generation, API replay | Was: yes, replayed traffic on every PR [V] | Was: yes, recorded vs current responses [V] | Deviation reports on the PR [V] | SDKs Apache-2.0 [V] | **Sunset Jun 10 2026** [V] |
| Antithesis | Deterministic simulation | **Yes.** Custom hypervisor, fault injection [V] | No; property-based [V] | Exact repro, time-travel debugger [V] | No | **$105M Series A, Dec 2025**. Explicitly pitched at agent-written code [V] |
| Diffblue Cover / Testing Agent | Unit test generation | Yes. "verifies that every test compiles and passes" [V] | No; pins current behaviour [V] | No | No | Testing Agent GA Mar 24 2026, **Java and Python** [V] |
| Qodo Cover (cover-agent) | Test generation, OSS | Yes. Runs tests and checks coverage rises [V] | No | Per-test exit code and stdout [V] | **AGPL-3.0**, 5.7k stars [V] | **"no longer maintained"** since Jun 2025 [V] |
| CloudBees Smart Tests (ex-Launchable) | Predictive test selection | No; CI runs the tests [V] | No | n/a | No | Acquired Aug 2024; renamed [V] |
| Codecov ATS | Test selection (Python) | No [V] | No | n/a | No | Still "[Beta]"; no deprecation found [V] |
| Datadog Test Impact Analysis | Test selection | No [V] | No | n/a | No | Per-test coverage; $20 per committer [V] |
| pytest-testmon | Test selection; OSS | Runs within pytest [V] | No | n/a | **MIT** [V] | Coverage-based dependency DB; **reusable for Repro** |
| Trunk | Flaky tests, merge queue | No; consumes CI results [V] | No | n/a | No | Code Quality web features sunset in 2025 [V] |
| Symflower | LLM code quality, test generation | Symbolic and dynamic analysis [V] | No | n/a | No | Benchmark repo archived [V] |
| **Testora** (academic, ICSE '26) | Research prototype | **Yes.** LLM-generated tests run on **old and new** versions of **Python PRs** [V] | **Yes**, plus an LLM classifies each difference as intended or unintended from the PR text [V] | Differences, flakiness-checked [V] | **MIT** [V] | **Closest conceptual match to Repro** |
| Conductor | Orchestrator (Mac) | Runs scripts in workspaces. Cloud sandbox since Jul 30 2026 [V] | No | No | No [U] | Checks tab collects CI status [V] |
| Superset | Orchestrator | Agents run tests in worktrees [V] | No | No | Source-available (ELv2) [V] | "Worktrees do not sandbox processes" [V] |
| Emdash | Orchestrator | Shows CI check status [V] | No | No | **Apache-2.0** [V] | Native Windows support [V] |
| Claude Code (agent view, desktop, cloud) | Agent and orchestrator | Yes. Desktop `autoVerify` takes screenshots and inspects the DOM; `/verify` builds and runs the app [V] | No | Session "report" [V] | No | Worktree per background session [V] |
| OpenAI Codex cloud | Agent | Yes. Cloud sandbox; runs tests, linters and type checkers [V, browser] | No | **Citations to terminal logs and test outputs** [V, browser] | Codex CLI is Apache-2.0 [V]; the cloud service is not open source | Screenshots attached to PRs [V, browser] |
| Copilot cloud agent | Agent | Yes. Ephemeral environment; tests and linters; Playwright [V] | No | Screenshots; validation results [V] | No | Since Jun 2026 runs CodeQL, secret and dependency checks on Claude and Codex PRs too [V] |
| Devin 2.2 | Agent | Yes. Linux desktop; "Test the app" with a test plan [V] | No | **Annotated screen recordings** [V] | No | Owns Windsurf [V] |
| Jules | Agent | Yes. Cloud VM; Critic Agent; screenshots [V] | No | Screenshots; critic reasoning [V] | No | Auto-fixes CI (Feb 2026) [V] |
| Cursor cloud agents | Agent | Yes. VM with computer use [V] | No | Videos, screenshots, logs, but only inside Cursor [V] / [S forum] | No | "More than 30% of the PRs we merge at Cursor" come from agents [V] |

---

## 2. Category detail

### 2.1 AI code review tools

**CodeRabbit**

What it does:
- PR reviewer for GitHub, GitLab, Bitbucket and Azure DevOps, with a CLI and an IDE extension [V docs and pricing].

Execution:
- Google Cloud's case study (Apr 23 2025) says CodeRabbit runs untrusted customer code in Cloud Run. Each instance is a second-generation microVM, and processes inside are jailed with Jailkit and cgroups [V].
- The sandbox does this work [V]:
  - installs dependencies (`npm install`, `go mod download` and similar);
  - runs "20+ linters and security scanners";
  - runs LLM-generated shell scripts (cat, grep, ast-grep) and Python;
  - runs LLM-generated "verification scripts".
- The architecture docs say "Sandboxed cloud execution with your full repository cloned" and "50+ static analyzers, linters and SAST tools". They list a "Verification" agent next to Review, Chat and Pre-Merge Checks [V].
- **Neither source says the customer's test suite or app is run** [V].
- 2026 changelog [V]:
  - "Fix CI failures" (Jul 16) "works through a fix in a sandbox";
  - "Attack surface map" (Sep 4) tracks "verification evidence";
  - AI Deep Scan, an on-demand security scan.

Results:
- Walkthrough summary, inline comments, and "pre-merge checks". Built-in checks cover docstring coverage, title, description and linked-issue compliance. You can add custom agentic checks.
- CodeRabbit can switch its review to "Approve" once checks pass [S docs snippet].

Pricing [V pricing page]:
- Essentials $24, Team $48, Advanced $72 per user/mo, billed annually (20% off). The FAQ gives monthly prices of $30 and $60.
- CodeRabbit Engineer, an on-demand coding agent, costs $0.40 per agent-minute.

Other:
- Funding: $143M Series C at a $1.5B valuation, led by Atomico and Smash, around Aug 12 2026 [S: Wilson Sonsini page (403 on fetch), multiple secondary reports].
- Vendor report (Dec 2025): AI-co-authored PRs had 1.7x more issues [V].

**Graphite and Graphite Agent**

Product:
- On Oct 7 2025, Graphite merged its Diamond reviewer and Chat into "Graphite Agent" and retired the Diamond name [V].
- Pricing: Hobby free, Starter $20, Team $40 per user/mo (annual), with unlimited AI reviews on Team [V].

Acquisition:
- Cursor (Anysphere) announced the purchase of Graphite on **Dec 19 2025**. Terms were undisclosed; Axios reported "way over" Graphite's last valuation of $290M [V TechCrunch].
- Graphite will keep running as a separate product. It plans to combine "its AI Reviewer with Cursor's Bugbot" [V Graphite blog].
- The pricing page banner reads: "Cursor Cloud Agents are now in Graphite" [V].

Execution:
- No mention of executing code [V].

**Greptile**

How it reviews:
- Builds a graph of every function, class and call. On each change it queries call sites and dependencies, which "Identifies all code that could be affected by changes". In effect this is a static blast radius [V docs].

2026 changes:
- v4 (Mar 5 2026): $30 per developer per month including 50 reviews, then $1 per review [V].
- v5 (Aug 5 2026): parallel, narrowly scoped agents [V changelog].
- **TREX, "Test, Run, Execute"** (Jun 15 2026, public beta) [V blog and changelog]:
  - picks "the behavior worth running", "spins up a sandbox, runs the relevant code";
  - per the changelog it "writes and runs targeted tests in a sandbox … against the services and frameworks your repo already uses";
  - attaches logs, screenshots, API traces, execution scripts and UI video;
  - "The point is to show what happened, so you or a downstream agent can confirm it";
  - claims "catches 20% more bugs" in Greptile's own evals, with no method given.
- The TREX pages say nothing about comparing against base [V].
- Other changelog items (Jun–Sep 2026) [V]:
  - Model Inversion (experimental): a different model reviews the PR than the one that wrote it;
  - auto-approve for low-risk PRs (beta);
  - a confidence score in summaries;
  - a free Starter plan.

Pricing:
- Starter free (1 developer, 50 credits per month), Pro $30/seat, Enterprise custom with a self-host option [V].
- TREX costs "$2 per run after June" [S: search snippet only, not on the fetched page].

Benchmark:
- Greptile reported F1 of 60.8% on Martian's Code Review Bench (Jul 30 2026) [S].

**Qodo (formerly CodiumAI)**

- **Qodo 2.0 (Feb 4 2026)** [V]:
  - Mixture of expert agents plus a "judge" agent.
  - Output is one structured review: severity, category, reasoning and a remediation prompt.
  - Self-run benchmark: F1 60.1%, recall 56.7%.
  - Execution is not documented [V].
- **Qodo 2.1** adds a Rules System [S].
- **Pricing:** Pro Team $30 for up to 30 users, using credit pools at $0.012 per credit [V].
- **Funding:** $70M Series B, Mar 2026 [S].
- **PR-Agent** [V GitHub]:
  - Now "a community-maintained legacy project", being donated to an open-source foundation.
  - LICENSE file is **MIT** (copyright 2026, The PR Agent). Older secondary sources say Apache-2.0, so it was probably relicensed [U].
  - 13.4k stars.
- Qodo Cover: see §2.2.

**GitHub Copilot code review**

Architecture:
- Agentic tool-calling architecture became GA on **Mar 5 2026**. It "runs on GitHub Actions" [V changelog].

Docs [V]:
- The GitHub and Playwright MCP servers are "enabled by default".
- Effort levels: Lite and Balanced.
- Billing is in **AI credits**: about $0.05–$1 per review at Lite and $0.25–$5 at Balanced, plus Actions minutes.
- "Every Copilot code review includes an approval assessment" (preview).
- Can hand off to Copilot cloud agent.
- **No statement that it runs tests** [V].
- Static analysis (CodeQL, ESLint, PMD) inside the review is listed as public preview [S docs snippet]. GitHub Code Quality's CodeQL analysis is a separate product [V].

Scale (Mar 5 2026 blog) [V]:
- 60M+ reviews; more than 1 in 5 code reviews on GitHub.
- 71% of reviews surface actionable feedback.
- 12,000+ organisations run it automatically.

**Cursor Bugbot**

How it works [V docs]:
- Reviews the PR diff on every update and posts a `Cursor Bugbot` check run, which is neutral by default.
- Rules come from `.cursor/BUGBOT.md`, team rules and learned rules.
- Autofix "starts a Cloud Agent" that pushes fixes.
- Usage-based billing.
- Execution is not documented [V].

Updates and claims:
- Jun 10 2026: Composer 2.5 model, about 90 s per review, 0.62 bugs per review, 22% cheaper [V changelog].
- "70%+ of flags get resolved before merge" [V marketing].

**Claude Code Review, ultrareview, `/code-review` and `/verify` (Anthropic)**

Managed Code Review (launched **Mar 9 2026**, research preview for Team and Enterprise) [V blog and docs]:
- How it runs:
  - Agents work in parallel; then "a verification step checks candidates against actual code behavior to filter out false positives".
  - Severities: Important, Nit, and **Pre-existing** (a bug not introduced by this PR).
- How it reports:
  - A collapsed "Why this was flagged" says how each finding was verified.
  - The check run is always neutral and ends with machine-readable severity JSON.
  - `REVIEW.md` can set a "verification bar", for example requiring `file:line` citations.
- Internal stats:
  - substantive comments rose from 16% to 54% of PRs;
  - 84% of PRs over 1,000 lines get findings (7.5 on average);
  - under 1% of findings were marked incorrect.
- Cost and speed: $15–25 per review, about 20 min.

**Ultrareview** (`/code-review ultra`) [V]:
- A "fleet of reviewer agents in a cloud sandbox".
- "Every reported finding is independently reproduced and verified."
- Takes 5–10 minutes. Pro and Max get 3 free runs, then $5–25 per run.
- `claude ultrareview --json` prints `bugs.json`.

**`/verify`**, a bundled skill [V docs]:
- "Build and run your app to confirm a code change does what it should, without falling back to tests or type checks".
- Can run before commits (v2.1.286+).
- A Jul 22 2026 Claude blog post calls verification loops part of the agentic loop [V].

**GitHub Action** (`anthropics/claude-code-action@v1`) [V]:
- Runs Claude Code on your own runner, so it *can* run tests if it is allowed those tools.

**OpenAI Codex code review** [V learn.chatgpt.com; V, browser openai.com]
- Reviews the PR diff, follows a `## Code Review Rules` section in `AGENTS.md`, and flags only P0/P1 on GitHub.
- Triggered by `@codex review` or automatic review. `@codex security review` runs a separate security pass.
- The Sep 15 2025 post says code review "matches the stated intent of a PR to the actual diff, reasons over the entire codebase and dependencies, and **executes code and tests to validate behavior**". **This is the closest public statement to Repro's "judge claims against execution".** Its output is still review comments, not a per-claim verdict.

**Other reviewers**

- **Sourcery** [V]:
  - Pro $15/mo ($12 annual); Team $30/mo ($24 annual); free for open source; security scanning on Team.
  - No execution.
- **Ellipsis** [V homepage]:
  - Repositioned as a platform for "building and running coding agents", with YAML-defined agents in "an isolated cloud environment".
  - Its sample log shows `pytest -k pool`.
  - Testing happens only if your agent's prompt asks for it.
  - Raised a $2M seed (Jan 2026) [S].
- **CodeAnt AI**:
  - AI review plus SAST, secrets and IaC; Premium $24 per user [S].
  - The live pricing page shows only "AI Pentesting" [V].
- **Korbit** [V SecurityWeek, May 7 2026]:
  - Acquired by Boost Security alongside SecureIQx, with a $4M funding extension.
  - An earlier "shutdown" notice (Sep 2025) came from a competitor [S CodeAnt].
- **Bito** [V]: Team $12/$15, Professional $20/$25 per seat; 5K lines per seat per month, then $5 per 1K lines. No execution.
- **Amazon Q Developer for GitHub** [V AWS docs]:
  - "In preview release". Auto-reviews on PR open or reopen; `/q review`.
  - Rules in `.amazonq/rules`; a free monthly line quota.
  - No execution.
- **Gemini Code Assist on GitHub** [V Google deprecations page]:
  - Consumer app deprecated Jun 18 2026, shut down **Jul 17 2026**.
  - No new Standard or Enterprise purchases after Oct 9 2026.
  - Renewals end Jan 31 2027 (annual) and Dec 31 2027 (monthly).
- **Gitar** [V Sonar product page and community post]:
  - Acquired by **Sonar** (announced May 21 2026). Bills itself as "the code change verification agent".
  - Reads your CI, root-causes failures, retries flaky tests. "iterates until your CI passes, then commits only on green."
  - Core $20, Pro $40; Enterprise is priced per PR.
- **Qodex.ai** [V homepage]:
  - "Runs real API, UI and security tests on every pull request". Scenarios are Playwright or HTTP, run against "a per-PR preview deploy … otherwise a shared staging environment".
  - "Every finding carries the failing request, response or screenshot".
  - Failures are sorted into real bugs, stale tests and environment problems.
  - Reports through status checks. No base-vs-head comparison.
- **Macroscope** [V]: Check Run Agents are markdown-defined custom checks that "Cannot execute arbitrary code". New workspaces get $100 of free usage.
- **Jazzberry** [V YC launch page]:
  - Clones the repo into a microVM, then "can write and execute code" to find bugs; posts a markdown table to the PR.
  - The YC listing now shows its maker as Cartpole, an RL-environments company, so the product's status is unclear [S].
- **Devin Review** [V docs, from the orchestrator track]: smart diff grouping and a Bug Catcher with severities and CWE labels. Execution for findings is not documented.
- **Factory automated review** [V]: "analyzes the diff"; no execution described.
- **cubic, Propel, Augment Code Review** [S]: diff and context reviewers; no execution documented in what I found.
- **Benchmarks**:
  - Martian's Code Review Bench has an offline track (50 PRs from 5 repos, 136 "golden comments") and an online track [S arXiv 2606.15689 and vendor posts].
  - Leaders change month to month: Greptile and cubic have each claimed the top spot [S].
  - All entrants are scored on *comment* precision and recall, not on behavioural verification.

### 2.2 Tools that execute or verify behaviour

Research notes for this track:
- The web-search budget ran out near the end. Macroscope, Propel, cubic, Bito and Recurse therefore rest on snippets [S].
- The Diffblue pricing, Symflower docs and Meticulous pricing pages render with JavaScript and returned no content.
- Two fetched pages contained text addressed to AI agents: setup "instructions" in the Momentic docs, and unrelated appended text on the Symflower homepage. That text was treated as data and ignored.

**Unit-test generators**

- **Diffblue Cover / Diffblue Testing Agent**
  - Cover is a "reinforcement learning AI platform" that writes Java unit tests [V docs].
  - The **Testing Agent** went GA on **Mar 24 2026** for **Java and Python** [V press release via The AI Journal]:
    - it delegates test writing to the customer's Copilot or Claude Code;
    - it adds coverage analysis, planning, verification and PR prep;
    - it "verifies that every test compiles and passes, and rolls back any that don't".
  - Vendor benchmark: 81% line coverage vs 32% for a senior developer using Claude Code for 2 h [V].
  - It pins current behaviour and does not diff base against head.
  - Pricing could not be verified.
- **Qodo Cover / cover-agent** [V GitHub]
  - The README says "This repository is no longer maintained." (Jun 15 2025). It is not archived; last push Apr 2026.
  - AGPL-3.0, 5,660 stars.
  - It *did* execute: a test runner, a coverage parser, and per-test exit code and stdout.
  - Qodo's homepage now leads with "Qodo 3.0: Quality Control for the Agentic Software Factory", with no mention of sandboxed execution [V].
  - $70M Series B, Mar 30 2026 [S Globes].
- **Symflower** [V homepage]
  - Repositioned around improving LLM code: benchmarks, pre- and post-processing and repair, RAG, fine-tuning data. Mentions "symbolic and dynamic analyses".
  - Its DevQualityEval repo is archived (May 2025) [V].
  - No 2025–2026 news could be verified.

**Record, replay and differential tools**

- **Meticulous** (frontend; **the most mature commercial base-vs-head product**) [V homepage and glossary]
  - Records real sessions and replays them in a deterministic Chromium scheduler with stubbed network.
  - A "Test Run" happens on both the **base commit and the head commit**. A "Diff" is a pixel-level screenshot difference, marked Approved or Rejected, and **posted to the PR**.
  - Pitched as "Ship code at the speed your agents write it".
  - Raised $15M (blog, Jul 14 2026) [V].
  - Pricing not public.
  - Agent skills that classify each diff as intended or unintended [S].
- **Keploy** (OSS) [V GitHub, pricing, docs]
  - Apache-2.0, 18,561 stars, active.
  - eBPF captures API, DB and queue traffic; replays it with automatic mocks and time freezing; supports any language including Python.
  - Its PR Agent generates unit tests and posts a table. The docs don't say the tests are run.
  - Pro is $19/user/mo plus usage (e.g. $0.22 per test run).
- **Speedscale / proxymock** [V homepage, license]
  - Record, replay and mock for HTTP, gRPC and databases. "Replays diff each response against what production returned", field-level, with P50–P99 latency.
  - The CLI is **proprietary** but free for small orgs.
- **Signadot Smart Tests** [V]
  - Sends the same requests to the changed service and the baseline; "a model flags meaningful differences".
  - Has an MCP server and skills for coding agents, and a PR comment.
  - Kubernetes only.
- **Curtail ReGrade** [V blog, Jun 10 2026]
  - Records HTTP traffic from existing tests and replays it against the **baseline and candidate builds**, producing a field-level diff.
  - PR annotations; developers approve intended changes.
- **Diffy** [V GitHub]
  - The original twitter/diffy (Apache-2.0) was **archived on Jul 2 2020**.
  - opendiffy/diffy continues it (last push May 2026) under **CC BY-NC-ND 4.0**, which is not open source.
  - Design: send each request to **candidate**, **primary** and **secondary**. Primary and secondary run the same code, so their disagreement measures the noise floor.
  - **Steal this noise-cancellation idea**: run base twice to separate non-determinism from real behaviour change.
- **Tusk and Tusk Drift** [V usetusk.ai]
  - **"We are sunsetting the Tusk product on Jun 10, 2026"** (CEO post, Jun 11 2026). It recommends Devin, but no acquirer is named.
  - Before the sunset it called itself an "AI verification layer for coding agents".
  - **Tusk Drift** recorded live traffic, built API tests, replayed them "against every PR" in CI, and posted deviation reports.
  - It claimed to catch regressions in 43% of PRs [V homepage].
  - The Python SDK and the CLI remain open source (Apache-2.0) [V].
  - **The nearest commercial analogue to Repro for Python backends, and it died.** Treat that as a market signal; the cause is unknown.
- **Antithesis** [V homepage, PR Newswire]
  - Deterministic simulation on a custom hypervisor: fault injection, exact reproduction, time-travel debugging.
  - **$105M Series A (Dec 3 2025) led by Jane Street.** It explicitly sells "verifying that AI-developed software actually works", through agent skills, CLIs and APIs.
  - Property-driven, not base vs head.

**Test-selection tools** (these pick tests to run; none diffs behaviour)

- **CloudBees Smart Tests, formerly Launchable** [V]
  - CloudBees acquired Launchable on Aug 7 2024; the page says "Launchable is now CloudBees Smart Tests".
  - The CLI and the PyPI package were renamed to `smart-tests` / `smart-tests-cli`.
  - Selection uses LLMs and semantic similarity; customers report a 35–70% reduction in CI runtime (vendor figure).
- **Codecov Automated Test Selection** [V docs]
  - Still "[Beta]", "in Open Beta for Python" with pytest.
  - Combines static and label analysis against a BASE commit.
  - No deprecation notice; the docs were updated Nov 2025.
- **Datadog Test Impact Analysis** [V]
  - "formerly known as Intelligent Test Runner"; uses per-test coverage; supports Python.
  - Test Optimization costs $20 per active committer per month (annual).
- **pytest-testmon** [V GitHub, PyPI, testmon.org]
  - MIT; 2.2.0 released Dec 1 2025; Python 3.10+.
  - "selects tests affected by changed files and methods", using a Coverage.py-based dependency DB (`.testmondata`).
  - **A direct building block for Repro's blast-radius test selection.**
- **Trunk** [V]
  - Flaky-test detection and quarantine, a merge queue, AI failure analysis.
  - CI Analytics and Code Quality web features were sunset in 2025.
  - Free tier up to 5 committers.
  - It consumes CI results and does not execute the PR itself.

**2025–2026 startups explicitly "running" AI PRs**

These are covered in §2.1 (Greptile TREX, Qodex, Jazzberry) and in the table above (Ito, QA.tech, Momentic, Ranger). One more:

- **Cursor Bugbot Autofix** (blog, Feb 26 2026) "spawns cloud agents that work independently in their own virtual machines to test your software". Over 35% of autofixes are merged. Cursor describes "enabling Bugbot to verify its own findings" as a **future** goal [V].

**Academic and OSS prior art closest to Repro**

- **Testora**, "Using Natural Language Intent to Detect Behavioral Regressions" (M. Pradel, **ICSE '26**; arXiv 2503.18597) [V]
  - Method:
    - for **Python PRs**, an LLM generates tests for the changed code;
    - they run on the **old and new** versions;
    - output differences are reduced and checked for flakiness;
    - an LLM then classifies each difference as **intended or unintended**, using the PR title, description and commits.
  - Results:
    - 19 regressions and 11 coincidental fixes found in keras, marshmallow, pandas and scipy;
    - 11 of 13 reported regressions confirmed, 9 fixed;
    - classifier precision 55%, recall 67%;
    - about 12.3 min and $0.003 per PR.
  - MIT; 19 stars.
  - **This is Repro's core idea in research form.**
- **Collector-Sahab**, "Augmenting Diffs With Runtime Information" (IEEE TSE 2023; Java/Defects4J) [V]
  - Compares runtime program states between the original and patched program and attaches the differing values to the diff in code review.
  - Augmented 95% of 584 diffs.
- Related work [S]:
  - DiffTestGen (arXiv 2607.16024) and Mokav (arXiv 2406.10375);
  - small GitHub projects RengGyu/AgentProof, Agent-Proof "Proof Passport", and knowbody/diff0.

### 2.3 Parallel agent orchestrators and agent PR producers

**Conductor** (conductor.build, macOS)
- Runs Claude Code, Codex, Cursor and OpenCode in "isolated workspaces on your Mac". Each task gets its own branch, terminal, diff and review path [V].
- Worktree-backed [S vendor guide].
- **Conductor Cloud** (v0.78.0, Jul 30 2026) puts agents in an "isolated Linux sandbox" [V].
- The Checks tab collects "CI and status checks", todos and deployments, and may discourage merging while any are open [V].
- Has run scripts and setup scripts [V changelog titles].
- No verification beyond CI is described.
- Pricing: Free; Pro $50/mo including Cloud; Teams $60/user/mo [V].

**Superset** (superset.sh)
- Orchestrates any CLI agent with one git worktree per task [V].
- Says itself that "Worktrees do not sandbox processes or prevent merge conflicts" [V].
- Has a diff panel, an in-app browser, a mobile diff review app, and an SDK to "wire Superset into CI" [V].
- Elastic License 2.0 (source-available), about 15.1k stars [V].
- Free tier; Pro $20/seat [V]. macOS; Windows not yet available [V].

**Emdash** (github.com/generalaction/emdash, YC W26)
- Apache-2.0, about 6.0k stars [V].
- Runs many agent CLIs with a worktree per task. "Review diffs, create pull requests, inspect CI check status, and merge" [V].
- Keeps state in local SQLite and says nothing is sent to its servers [V].
- **Runs natively on Windows** [V].
- No verification features.

**Claude Code (Anthropic)**
- Agent view (`claude agents`) gives each background session its own worktree under `.claude/worktrees/`. Sessions end with "a report saying what it did and where the work is". PR rows are coloured by check status [V].
- The desktop app starts a dev server in a browser pane and "verify[s] its own changes automatically: it takes screenshots, inspects the DOM, clicks elements, fills forms". `autoVerify` is on by default [V].
- Cloud sessions run in "an isolated, Anthropic-managed VM" and can auto-fix CI and review comments on PRs [V].
- Code Review, ultrareview and `/verify`: see §2.1.

**OpenAI Codex (cloud)** [V, browser, openai.com; V learn.chatgpt.com changelog]
- Launch (May 16 2025):
  - Each task runs "in its own cloud sandbox environment, preloaded with your repository".
  - Runs "test harnesses, linters, and type checkers".
  - **"Codex provides verifiable evidence of its actions through citations of terminal logs and test outputs."**
- The published system prompt sets a citation format, `【F:<path>†L<start>-L<end>】` and `【<chunk_id>†L<start>】`. It says programmatic checks listed in `AGENTS.md` "MUST" be run [V].
- Sep 2025: Codex can "attach a screenshot of the result to the task and GitHub PR" [V, browser].
- Changelog [V]:
  - Apr 16 2026, "Verify more of your work": in-app browser and computer use;
  - Jul 9 2026: folded into the ChatGPT desktop app;
  - Aug 19 2026: GitLab support in cloud (beta).

**GitHub Copilot cloud agent** (renamed from "coding agent" in 2026 [S]; the docs use "cloud agent" [V])
- "can edit files and run tests and linters in an ephemeral cloud development environment" [V].
- Jul 2 2025: Playwright browser "to reproduce bugs and validate its work" and screenshots in the PR [V].
- Oct 28 2025: automatically runs **CodeQL, an Advisory Database dependency check, secret scanning, and a Copilot code review** on its own code and "attempts to resolve them" [V].
- Mar 18 2026: admins can configure which validation tools run, including "your project's tests and linter" [V].
- **Jun 9 2026: the same security validation went GA for third-party agents (Claude, Codex)** [V].

**Devin (Cognition)**
- Cognition agreed to buy Windsurf on Jul 14 2025 [V TechCrunch].
- Devin 2.2 (Feb 24 2026) [V]:
  - gets its own Linux desktop and "reviews its own output, catches issues, and fixes them" before opening a PR;
  - sends back "screen recordings".
- After a PR, a **"Test the app"** button runs a flow where Devin "reads the diff and creates a focused test plan". The result is an annotated recording [V docs].

**Jules (Google)** [V changelog]
- Cloud VM; "test verified patches" at launch (May 2025).
- Renders web apps and returns screenshots (Aug 2025).
- **Critic Agent** (Aug 8 2025) and Planning Critic (Jan 2026).
- Auto-fixes CI failures (Feb 2026).

**Cursor cloud agents**
- Isolated VMs [V].
- Computer use since **Feb 24 2026**: agents "build, test, and interact with the changed software", and PRs carry "artifacts (videos, screenshots, and logs)" [V].
- Cursor says "More than 30% of the PRs we merge at Cursor are now created by agents operating autonomously in cloud sandboxes" [V].
- Per Cursor staff, the artifacts are viewable only inside Cursor, not on the GitHub PR [S forum].

**Others**
- **Sculptor (Imbue)**: a container per agent; "Instruction audits" are planned [V].
- **Factory Droids**: "human approval checkpoints" [V]; $150M Series C [S].
- **Amp**: Orbs (remote machines) [V]; spun out of Sourcegraph [S].
- **Claude Squad**: AGPL-3.0, tmux plus worktrees [V].
- **Shutdowns and deprecations:**
  - **Vibe Kanban**: its company, bloop, shut down Apr 10 2026; the project is now community-maintained [V].
  - **Crystal**: deprecated Feb 2026 and replaced by Nimbalyst [V].
  - **Terragon**: shut down; open-source snapshot dated Jan 16 2026 [V].

**Do any orchestrators verify beyond CI?** None of the orchestrators do (Conductor, Superset, Emdash, Claude Squad, Crystal, Vibe Kanban, Sculptor). They stop at isolation, a diff view, and CI or check status.

The agent *producers* do go further, but only as **self-verification by the authoring agent**:
- screenshots and videos (Copilot, Codex, Jules, Devin, Cursor, Claude Desktop);
- critics or self-review (Jules Critic, Devin Review Autofix);
- citations to their own terminal logs (Codex);
- generic SAST and secret gates (Copilot validation, now also applied to third-party agents).

None of them documents an independent base-versus-head behavioural comparison, or a per-claim verdict.

### 2.4 Agent observability (UX bar only)

- **LangSmith**: hosted tracing and evals. Its trace view is a "run tree" of nested spans plus a "Trajectory" tab [V]. Server and UI are proprietary [S].
- **Langfuse**: open-source tracing and evals. **Acquired by ClickHouse on Jan 16 2026**; "stays open source and self-hostable" [V]. UI has a trace tree and timeline, an agent graph, and an Aug 2026 timeline that "zooms like a map" [S changelog].
- **Arize Phoenix**: self-hosted, ELv2, about 11.8k stars. OpenTelemetry/OpenInference traces, evals, and a playground that replays traced calls [V].
- **Braintrust**: traces, evals and playground on its "Brainstore" database. $80M Series B on Feb 17 2026 [V]; $800M valuation [S].
- **AgentOps**: session recording with a **Session Waterfall** of LLM, tool and error events; the app is open source [V].
- **Galileo**: agent reliability and guardrails, with graph, timeline and trace views [S]. **Cisco completed the acquisition on May 22 2026** [V].
- **UX takeaway:** the norm is a *static* trace tree, waterfall or agent graph. None of the products reviewed presents a live, animated "mission control" driven by an event stream [U, based on documented UIs only].

---

## 3. Evidence: agent-PR volume, trust and the review bottleneck (2025–2026)

All figures below were checked on the primary page unless tagged otherwise. Several sources are vendors with a commercial interest; this is noted where it applies.

**Volume**

- **GitHub Octoverse 2025** (Oct 28 2025, covers Sep 2024–Aug 2025) [V]:
  - Copilot coding agent created **1M+ PRs between May and Sep 2025**;
  - **518.7M PRs merged** (+29% YoY);
  - 36M+ new developers;
  - 80% of new developers use Copilot in their first week.
  - Octoverse 2026 is not out yet [V].
- **GitHub engineering blog** (Oct 6 2026) [V]:
  - **7.38B commits in Sep 2026**, a little over 5x a year earlier;
  - PR merges nearly 4x;
  - Actions runs at 3.26B for the month.
  - GitHub names agentic development as the driver.
- **GitHub, "60 million Copilot code reviews"** (Mar 5 2026) [V]: Copilot code review accounts for **more than 1 in 5 code reviews on GitHub**.
- **AIDev dataset** (arXiv 2507.15003) [V]:
  - **456,535 agentic PRs** from 5 agents across 61K repos.
  - In popular repos, acceptance was 76.8% for humans against 38.2–65.3% for agents (Table 5). The paper calls this a "trust and utility gap".
- **LogicStar/ETH "Agents in the Wild"** live tracker [V]: agents are about **5–10% of public GitHub PRs**. Codex has opened 6.07M PRs and Claude Code 3.94M since May 2025. The numbers change hourly.
- **Claude Code's share of public commits** [V]:
  - SemiAnalysis (Feb 2026) estimates about **4%** of public GitHub commits are authored by Claude Code, and projects 20%+ by the end of 2026. That is a projection, not a measurement.
  - Anthropic (Sep 2026) says more than 80% of code merged into its own codebase was authored by Claude.

**Trust**

- **Stack Overflow 2025** [V]:
  - 84% use or plan to use AI tools.
  - Trust in accuracy: **33%**; distrust: **46%**. Only 3.1% "highly trust".
  - **66%** name "almost right, but not quite" as their top frustration.
  - 45.2% say debugging AI code takes longer.
- **Stack Overflow 2026** (Oct 6 2026, n = 30,903) [V]:
  - The top trust answer is **"Trust it when I can easily verify the output" at 48.0%**.
  - The answer options changed, so 2026 can't be compared with 2025.
  - 93% say source attribution matters for trust.
- **Stack Overflow pulse, "Agents on a leash"** (May 2026, n = 1,100) [V]: 59% use agents at work; **63% rarely or never let them run on autopilot**.
- **DORA 2025** [V Google blogs]:
  - 90% use AI at work.
  - Only 24% trust AI output "a great deal" or "a lot"; 30% have little or no trust.
  - AI correlates with higher throughput but **lower delivery stability**.
- **DORA "Balancing AI tensions"** (Mar 2026) [V]: describes a **"verification tax"**, where time saved writing code is spent checking it.

**Review bottleneck and quality**

- **Faros AI 2025**, telemetry from 10k+ developers [V]. On high-AI teams:
  - PRs merged **+98%**;
  - **PR review time +91%**;
  - PR size +154%.
  - The report calls human approval "a critical bottleneck".
- **Faros Q2 2026**, about 22k developers [V]:
  - median PR review time **5x**;
  - incidents per PR +242.7%.
  - Vendor data, and correlational.
- **LinearB 2026**, 8.1M PRs [V]:
  - AI PR acceptance **32.7% vs 84.4%** for manual PRs;
  - AI PRs wait **4.6x longer** before review.
- **METR RCT** (Jul 2025) [V]: experienced OSS developers took **19% longer** with AI while believing they were 20% faster. The Feb 2026 follow-up is inconclusive because of selection bias [V].
- **Message–code inconsistency in agent PRs** (arXiv 2601.04886, Jan 2026) [V]:
  - 23,247 agent PRs studied;
  - 1.7% have high inconsistency between the PR description and the code;
  - the most common type, at **45.4%**, is "descriptions claim unimplemented changes";
  - high-inconsistency PRs are accepted far less often (**28.3% vs 80.0%**) and take about 3.5x longer to merge.
  - **This directly supports Repro's per-claim check.**
- **CodeRabbit** (vendor, Dec 2025): AI-co-authored PRs had 1.7x more issues [V]. Veracode: AI code introduced vulnerabilities in 45% of cases (2025) and showed a 56% security pass rate (2026) [V].
- **GitHub's own guidance** (May 2026): reviewers should "Require a new test that fails on the pre-change behavior" and require evidence beyond passing CI [V]. **That is a base-vs-head check, done by hand today.**

---

## 4. Gaps no one fills (as of 2026-10-13, per the sources read)

"No one" means: not documented in any primary source read by the four research tracks.

1. **Function-level base-vs-head behaviour diff for ordinary PRs, as a product.**
   - Differential *products* exist only at coarser levels:
     - UI pixels: Meticulous;
     - HTTP/API responses: Signadot, Curtail, Speedscale, Keploy, Diffy;
     - API traffic for Python and Node: Tusk Drift, now dead.
   - No product records the inputs, outputs and exceptions of the *functions in the change's blast radius* on both sides and reports "same input, different output".
   - The execution-capable reviewers run **head only** to find bugs: Greptile TREX, Claude ultrareview, Codex review, Ito, QA.tech, Qodex, Jazzberry.
   - The function-level, two-sided idea exists **only in research**:
     - Testora (ICSE '26), for Python PRs, using generated tests;
     - Collector-Sahab (TSE 2023), for Java, using program states.
2. **Fail-to-pass and pass-to-pass classification on real PRs.** GitHub tells reviewers to "Require a new test that fails on the pre-change behavior" [V]. SWE-bench-style FAIL_TO_PASS and PASS_TO_PASS sets are the standard idea [U]. No tool found computes this automatically on a PR and turns it into evidence for a "fixes X" claim. That is based on two searches; the search budget then ran out.
3. **Per-claim verdicts.** Reviewers emit *findings*. None emits supported, contradicted or unverifiable *per claim*. The nearest are:
   - Codex review, which "matches the stated intent of a PR to the actual diff" [V, browser];
   - QA.tech, which checks Linear and Jira acceptance criteria [V];
   - Qodo 2.0, which reports "requirement gaps" [V];
   - CodeRabbit's linked-issue pre-merge check [S];
   - Testora, which classifies each difference as intended or unintended against the PR text [V].

   The PR-MCI paper shows that claim-vs-code inconsistency is common in its worst form, and costly [V].
4. **A structured "missing" inventory.** **QA.tech is the one product that marks a PR "unverified" when its tests never exercised the change** [V]. Ito "notes what was mocked" [V]. Nobody produces a structured list of *what could not be checked and why*: code no test reaches, network skipped, non-deterministic output, environment failure. Most reviewers fall silent when they find nothing; Copilot code review posts nothing in 29% of reviews [V].
5. **"Unexplained behaviour change" as a first-class gate.** Testora's "unintended" class and Meticulous's approve/reject flow come closest. No tool uses the rule "any behaviour diff not covered by a stated claim flags" as its merge signal.
6. **Deterministic, replayable verification runs.** Antithesis offers deterministic replay of *bugs*, and Meticulous replays deterministically for screenshots. No PR verifier stores an event log from which the whole verdict, evidence included, can be replayed.
7. **Local-first, independent verification.** Every execution-capable reviewer runs in the *vendor's* cloud or against your preview deploy. Among orchestrators only Emdash (Apache-2.0, Windows too) and Superset are local-first, and neither verifies anything.
8. **Independence from the authoring agent.** The "proof of work" (screenshots, videos, critics, citations to its own logs) comes from the agent that wrote the code. Copilot's third-party validation (Jun 2026) is vendor-neutral, but it is SAST and secrets scanning, not behaviour.

---

## 5. Implications for Repro (opinionated)

### 5.1 Positioning: what to say now

**Retire the slogan "AI reviewers read the diff; Repro runs it."** It is false for:
- Codex review (Sep 2025);
- Greptile TREX (Jun 2026);
- Claude ultrareview;
- Ito, QA.tech, Qodex and Jazzberry.

A reviewer would rebut it in one link. Also drop any claim that base-vs-head diffing is novel: Meticulous does it commercially for UI, and Testora published it for Python PRs.

Claims that remain true:
- *"Others run your code to find bugs. Repro runs **both sides** and shows **what changed**, then checks each change against what the PR **claims**."*
- *"Not 'does it work?' but 'what did it change, and did it say so?'"*
- *"Every verdict cites evidence you can replay on your own machine."*

### 5.2 Where the defensible wedge really is

Narrowest and strongest first:

1. **Unexplained behaviour change at function level, for backend and library code.** This is the gap between head-only executors (they find crashes and wrong outputs that some test or probe notices) and UI/HTTP differentials (they see only the surface). Make the **Gap panel** and the rule "an unexplained diff always flags" the hero of the product.
2. **Claim verdicts plus an explicit Missing list, as a contract.**
   - Lean on PR-MCI: the commonest inconsistency type is "descriptions claim unimplemented changes" (45.4%), and those PRs get far lower acceptance.
   - Lean on Stack Overflow 2026, whose top trust answer is "trust it when I can easily verify the output" (48%). The Reproduction Card is the "easily verify" artifact.
   - QA.tech's "unverified" verdict shows the idea resonates commercially. Repro goes further by itemising *why*.
3. **Fail-to-pass and pass-to-pass as automatic evidence.** It falls out of the base-vs-head runner almost for free. It is very legible ("C1 'fixes X' is SUPPORTED: test T fails on base and passes on head"), it automates GitHub's own reviewer advice, and nobody ships it.
4. **Local-first, replayable, vendor-neutral.**
   - Code never leaves the machine, and every verdict replays from the event log.
   - It treats Codex, Claude, Copilot, Cursor and human PRs identically.
   - Vendor reviewers are tied to their own clouds and they churn: Gemini's GitHub reviewer shut down, Tusk sunset, Korbit and Gitar were acquired, Qodo Cover was abandoned. A local OSS tool is a credible hedge for teams.

### 5.3 What to copy

| Source | Idea | Repro use |
|---|---|---|
| **Testora** (MIT, Python) | Generate tests for changed code; run old and new; reduce diffs; check flakiness; LLM classifies intended vs unintended from the PR text | Read the paper before M3–M5. Reuse its flakiness checks and its classification prompt design. Use its 55% precision / 67% recall as **the academic baseline to beat** |
| **Diffy** | Run *two* copies of the known-good version to measure the noise floor, then judge candidate-vs-primary against it | Run base twice, or replay a sample, so non-determinism is measured rather than guessed. Put noisy fields in "Missing", not in "Gap" |
| **Meticulous** | Base and head replay; per-diff Approve/Reject; agent skill that needs every diff explained | Per-diff "explained by C2 / unexplained" state in the Gap panel |
| **Claude Code Review** | Neutral check run by default; machine-readable last line; collapsed "Why this was flagged"; **"Pre-existing"** severity | Same output contract. Repro can make *pre-existing vs introduced* rigorous, because it actually ran base |
| **Codex** | Published citation grammar for file lines and terminal-output chunks | Stable, clickable evidence IDs that resolve to stored artifacts |
| **Greptile TREX, Ito** | Attach scripts, logs and traces "so you or a downstream agent can confirm it"; state what was mocked | A minimal reproducer per behaviour diff. List mocks and skipped I/O under Missing |
| **QA.tech, Qodex** | "Unverified" when the change wasn't exercised; triage into real bug, stale test, environment | Map onto FLAGGED / UNVERIFIABLE / Missing(env) |
| **pytest-testmon** (MIT) | Coverage-based test↔code dependency DB | Use it, or its approach, for blast-radius test selection instead of building from scratch |

### 5.4 What to avoid

- **Auto-fix and code generation.** It is table stakes everywhere and it dilutes the "independent verifier" role. The current non-goal is right.
- **Competing on generic bug-finding F1** (Martian Code Review Bench). That is where well-funded incumbents fight.
- **Building another orchestrator.** That layer is commoditising: Claude Code ships agent view, and Terragon, Crystal and Vibe Kanban's company all folded in 2026.
- **Early hosted SaaS, or record/replay of production traffic.** Tusk tried the traffic-replay path for Python backends and **sunset in Jun 2026**. Speedscale, Keploy and Signadot already occupy it.

### 5.5 Honest risks

1. **Prior art weakens any novelty claim.** Testora covers the core loop on Python PRs: run old and new, diff, judge against PR intent. Repro must present itself as *productising and extending* it (function-level traces, invariants, claims and missing, local cockpit, replay) and should cite it.
2. **Platform risk is high.** OpenAI, Anthropic, Greptile, GitHub and Cursor already have sandboxes, test execution, evidence attachment and intent matching. "Also run base and diff" is a small step for any of them. Cursor calls "Bugbot verifying its own findings" a future goal [V]. The moat has to be **quality**:
   - trace normalisation;
   - noise handling;
   - blast-radius selection;
   - the claims/missing semantics;
   - trust from running locally;

   not merely "we execute".
3. **The commercial signal is mixed.** Tusk died. Meticulous raised money with base-vs-head, but in UI. Antithesis raised $105M pitching verification of agent code. Demand for "verify agent code" is real; the willingness to pay for *backend behavioural diff* is unproven.
4. **Environment setup is the real cost.** Installing arbitrary Python repos twice, with services, secrets, flaky tests and long suites, is where competitors spend their engineering (Greptile "runs against the services … your repo already uses"; Ito builds an app copy per PR; Devin and Claude have run recipes). Plan an early "UNVERIFIABLE (environment)" path and a flake quarantine (Trunk-style) from day one.
5. **Noise.** Traces will differ on timestamps, IDs, dict ordering and hash seeds. Without Diffy-style noise measurement, the Gap panel becomes the new noisy AI reviewer that teams switch off. Pragmatic Engineer (Sep 2026) reports a company that dropped AI review for noise [V].
6. **The benchmark plan is too weak as written.** M8 compares Repro only against a *diff-only* LLM reviewer. In late 2026 that won't support "beats industry tools". Add:
   - **Testora** as the academic baseline;
   - at least one **execution-capable** reviewer: Claude `/code-review ultra`, Greptile with TREX, or Codex review.

   Report catch rate and false-flag rate *per bug class*. Repro should win on silent behaviour change, unclaimed side effects and API breaks behind passing tests, and need not win on crash bugs.
7. **Scope.** Python plus pytest only, while TypeScript is #1 by contributors on GitHub [V Octoverse]. Fine for an MVP, but it caps the market until M8+.

---

## 6. Sources

All accessed 2026-10-13. The tag is the strongest level reached for that source.

### AI reviewers (reviewer track)
- [V] https://techcrunch.com/2025/12/19/cursor-continues-acquisition-spree-with-graphite-deal (TechCrunch: Cursor continues acquisition spree with Graphite deal)
- [V] https://graphite.com/blog/graphite-joins-cursor (Graphite: Graphite joins Cursor)
- [V] https://graphite.com/blog/introducing-graphite-agent-and-pricing (Graphite: Introducing Graphite Agent and pricing)
- [V] https://graphite.com/pricing (Graphite pricing)
- [V] https://www.greptile.com/blog/greptile-v4 (Greptile v4 + New Pricing)
- [V] https://www.greptile.com/blog/trex (Introducing TREX: Greptile Now Runs Your Code)
- [V] https://greptile.com/changelog (Greptile changelog)
- [V] https://www.greptile.com/pricing (Greptile pricing)
- [V] https://www.greptile.com/docs/how-greptile-works/graph-based-codebase-context (Greptile: graph-based codebase context)
- [V] https://cursor.com/docs/bugbot (Cursor Bugbot docs)
- [V] https://cursor.com/bugbot (Cursor Bugbot page)
- [V] https://cursor.com/changelog/bugbot-updates-june-2026 (Bugbot updates, June 2026)
- [V] https://www.coderabbit.ai/pricing (CodeRabbit pricing)
- [V] https://docs.coderabbit.ai/overview/architecture (CodeRabbit architecture)
- [V] https://docs.coderabbit.ai/changelog (CodeRabbit changelog, read to about the Jul 15 2026 entry)
- [V] https://cloud.google.com/blog/products/ai-machine-learning/how-coderabbit-built-its-ai-code-review-agent-with-google-cloud-run (Google Cloud: How CodeRabbit built its AI code review agent with Cloud Run, Apr 23 2025)
- [S] https://docs.coderabbit.ai/pr-reviews/pre-merge-checks (pre-merge checks, search snippet)
- [S] https://ecvc.wsgr.com/news/wilson-sonsini-advises-coderabbit-on-dollar143-million-series-c-funding (Series C; 403 on fetch)
- [V] https://www.qodo.ai/blog/introducing-qodo-2-0/ (Introducing Qodo 2.0)
- [V] https://www.qodo.ai/pricing/ (Qodo pricing)
- [V] https://github.com/qodo-ai/pr-agent and https://raw.githubusercontent.com/qodo-ai/pr-agent/main/LICENSE (PR-Agent README and LICENSE)
- [S] https://www.globenewswire.com/news-release/2026/02/04/3232129/0/en/qodo-2-0-redefines-ai-code-review-for-accuracy-and-enterprise-trust.html (Qodo 2.0 press release)
- [V] https://github.blog/changelog/2026-03-05-copilot-code-review-now-runs-on-an-agentic-architecture/ (Copilot code review agentic architecture)
- [V] https://docs.github.com/en/copilot/concepts/agents/code-review (Copilot code review concepts)
- [S] https://github.blog/changelog/2025-10-28-new-public-preview-features-in-copilot-code-review-ai-reviews-that-see-the-full-picture/ (CodeQL and ESLint in review, preview)
- [V] https://claude.com/blog/code-review (Claude: Code Review launch, Mar 9 2026)
- [V] https://code.claude.com/docs/en/code-review (Claude Code docs: Code Review)
- [V] https://code.claude.com/docs/en/ultrareview (Claude Code docs: ultrareview)
- [V] https://code.claude.com/docs/en/github-actions (Claude Code docs: GitHub Actions)
- [V] https://raw.githubusercontent.com/anthropics/claude-code-action/main/LICENSE (claude-code-action LICENSE, MIT)
- [V] https://code.claude.com/docs/en/skills (Claude Code docs: skills, `/verify`)
- [V] https://claude.com/blog/building-verification-loops-in-claude-code-with-skills (Claude blog, Jul 22 2026)
- [V] https://learn.chatgpt.com/docs/third-party/github (Codex code review in GitHub; redirect target of developers.openai.com/codex/integrations/github)
- [V, browser] https://openai.com/index/introducing-upgrades-to-codex/ (Introducing upgrades to Codex, Sep 15 2025; WebFetch got 403, read in browser by the orchestrator track)
- [V] https://docs.sourcery.ai/admin/plans/ (Sourcery plans)
- [V] https://www.ellipsis.dev (Ellipsis homepage)
- [S] https://www-origin.ellipsis.dev/blog/ellipsis-raises-a-2m-seed-round (Ellipsis seed)
- [V] https://www.codeant.ai/pricing (CodeAnt pricing)
- [V] https://bito.ai/pricing/ (Bito pricing)
- [V] https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/github-code-reviews.html (Amazon Q Developer in GitHub)
- [V] https://developers.google.com/gemini-code-assist/docs/deprecations (Gemini Code Assist deprecations)
- [V] https://krm.fyi/blog/gemini-code-assist-deprecation.html (K. Maynard blog on the deprecation; secondary context)
- [V] https://www.securityweek.com/boost-security-raises-4-million-for-sdlc-defense-platform/ (SecurityWeek, May 7 2026)
- [S] https://www.codeant.ai/blogs/migrate-from-korbit-ai-to-codeant-ai (Korbit shutdown claim, competitor source)
- [V] https://www.sonarsource.com/products/gitar/ (Introducing Gitar)
- [V] https://community.sonarsource.com/t/welcoming-gitar-to-the-sonar-family-ai-code-review-that-fixes-prs-and-gets-your-build-to-green/182642 (Sonar community, May 21 2026)
- [V] https://qodex.ai (Qodex homepage)
- [V] https://qodex.ai/blog/korbit-alternatives (Qodex blog; vendor)
- [V] https://macroscope.com/content/check-run-agents-custom-ai-checks-pull-requests (Macroscope Check Run Agents, Apr 7 2026)
- [V] https://www.ycombinator.com/launches/NQN-jazzberry-ai-bug-finding-with-real-code-execution (Jazzberry YC launch)
- [S] https://www.ycombinator.com/companies/cartpole (Cartpole listing)
- [V] https://factory.com/articles/reviewing-agent-generated-pull-requests (Factory, Sep 24 2026)
- [V] https://sourcegraph.com/blog/automated-code-review-tools (Sourcegraph, Sep 30 2026)
- [V] https://newsletter.pragmaticengineer.com/p/what-is-happening-with-code-reviews (Pragmatic Engineer, Sep 8 2026; partly paywalled)
- [S] https://www.augmentcode.com/changelog/introducing-augment-code-review (Augment Code Review)
- [S] https://www.greptile.com/content-library/greptile-martian-code-review-benchmark and https://arxiv.org/pdf/2606.15689 (Martian Code Review Bench)
- [S] https://docs.cubic.dev/ai-review/introduction (cubic)
- [V] https://arxiv.org/abs/2601.04886 (Gong et al., Analyzing Message-Code Inconsistency in AI Coding Agent-Authored PRs)
- [V] https://arxiv.org/abs/2212.11077 (Etemadi et al., Augmenting Diffs With Runtime Information, IEEE TSE 2023)
- [V] https://github.blog/ai-and-ml/generative-ai/agent-pull-requests-are-everywhere-heres-how-to-review-them/ (GitHub, May 7 2026)

### Execution and verification tools (execution track)
- [V] https://aijourn.com/new-diffblue-testing-agent-automatically-generates-comprehensive-regression-test-suites-to-derisk-application-modernization/ (Diffblue Testing Agent release)
- [V] https://docs.diffblue.com/ and https://cover-docs.diffblue.com/ (Diffblue docs)
- [S] https://www.businesswire.com/news/home/20251104720918/en (Diffblue, Nov 2025; 403)
- [V] https://github.com/qodo-ai/qodo-cover and https://api.github.com/repos/qodo-ai/qodo-cover (Qodo Cover)
- [V] https://www.qodo.ai/ (Qodo homepage, "Qodo 3.0")
- [S] https://en.globes.co.il/en/article-1001538970 (Qodo Series B)
- [V] https://www.meticulous.ai/, https://app.meticulous.ai/docs/concepts/glossary.md, https://www.meticulous.ai/blog (Meticulous)
- [S] https://raising.fi/news/meticulous-series-a-july-2026 (Meticulous round)
- [V] https://github.com/keploy/keploy, https://keploy.io/pricing, https://keploy.io/docs/running-keploy/utg-pr-agent/ (Keploy)
- [V] https://speedscale.com/, https://speedscale.com/pricing/, https://docs.speedscale.com/proxymock/reference/license (Speedscale)
- [V] https://www.signadot.com/ and https://signadot.com/docs/reference/smart-tests/traffic-capture-diffs (Signadot)
- [V] https://curtail.com/blog/catch-ai-generated-code-regressions-before-ship (Curtail ReGrade)
- [V] https://github.com/twitter/diffy and https://github.com/opendiffy/diffy (Diffy)
- [V] https://www.usetusk.ai, https://www.usetusk.ai/resources/tusk-is-sunsetting, https://www.usetusk.ai/resources/how-metricwire-catches-api-regressions-with-tusk-drift (Tusk)
- [V] https://github.com/Use-Tusk/tusk-cli and https://api.github.com/repos/Use-Tusk/drift-python-sdk (Tusk OSS)
- [V] https://antithesis.com/ and https://tools.prnewswire.com/en-us/live/20813/release/20251203EN37581 (Antithesis, $105M Series A)
- [V] https://www.cloudbees.com/newsroom/cloudbees-acquires-launchable-to-boost-genai-efforts-across-devsecops, https://www.cloudbees.com/capabilities/cloudbees-smart-tests, https://docs.cloudbees.com/docs/cloudbees-smart-tests/latest/ (CloudBees Smart Tests)
- [V] https://docs.codecov.com/docs/automated-test-selection (Codecov ATS)
- [V] https://docs.datadoghq.com/tests/test_impact_analysis/ and https://www.datadoghq.com/pricing/list/ (Datadog TIA)
- [V] https://github.com/tarpas/pytest-testmon, https://pypi.org/pypi/pytest-testmon/json, https://testmon.org/ (pytest-testmon)
- [V] https://trunk.io/, https://trunk.io/pricing, https://docs.trunk.io/changelog/2025-05-09-sunsetting-ci-analytics-and-code-quality-web-issue-browser (Trunk)
- [V] https://symflower.com/en/ and https://api.github.com/repos/symflower/eval-dev-quality (Symflower)
- [V] https://ito.ai/, https://ito.ai/pricing, https://www.producthunt.com/products/ito-ai-code-review-that-runs-code (Ito)
- [V] https://qa.tech/product/pr-testing (QA.tech PR testing)
- [V] https://momentic.ai/docs/guides/use-cases/pr-testing (Momentic)
- [V] https://www.ranger.net/ (Ranger)
- [V] https://cursor.com/blog/bugbot-autofix (Bugbot Autofix, Feb 26 2026)
- [V] https://jazzberry.ai/ (redirects to cartpole.com)
- [V] https://arxiv.org/html/2503.18597v3 and https://api.github.com/repos/michaelpradel/Testora (Testora, ICSE '26)
- [S] https://arxiv.org/pdf/2607.16024 (DiffTestGen) and https://arxiv.org/pdf/2406.10375 (Mokav)
- [S] https://github.com/RengGyu/AgentProof and https://github.com/knowbody/diff0/pull/19 (small OSS projects)

### Orchestrators and agents (orchestrator track)
- [V] https://conductor.build, https://www.conductor.build/docs, https://www.conductor.build/docs/reference/checks, https://www.conductor.build/docs/cloud-beta, https://www.conductor.build/pricing, https://www.conductor.build/changelog (Conductor)
- [V] https://superset.sh and https://superset.sh/compare/superset-vs-claude-code (Superset)
- [V] https://github.com/generalaction/emdash (Emdash)
- [V] https://code.claude.com/docs/en/agent-view.md, https://code.claude.com/docs/en/desktop.md, https://code.claude.com/docs/en/claude-code-on-the-web (Claude Code)
- [V, browser] https://openai.com/index/introducing-codex/ (Introducing Codex, May 16 2025)
- [V] https://learn.chatgpt.com/docs/changelog (Codex changelog)
- [V] https://raw.githubusercontent.com/openai/codex/main/LICENSE (Codex CLI LICENSE, Apache-2.0)
- [S] https://the-decoder.com/openai-expands-codex-and-its-api-at-devday-with-security-scans-a-decisions-api-and-ultrafast/ (DevDay 2026)
- [V] https://github.blog/changelog/2025-07-02-copilot-coding-agent-now-has-its-own-web-browser/
- [V] https://github.blog/changelog/2025-10-28-copilot-coding-agent-now-automatically-validates-code-security-and-quality/
- [V] https://github.blog/changelog/2026-03-18-configure-copilot-coding-agents-validation-tools/
- [V] https://github.blog/changelog/2026-06-09-security-validation-for-third-party-coding-agents
- [V] https://docs.github.com/en/copilot/concepts/agents/coding-agent/about-coding-agent (About Copilot cloud agent)
- [V] https://www.techcrunch.com/2025/07/14/cognition-maker-of-the-ai-coding-agent-devin-acquires-windsurf/
- [V] https://cognition.com/blog/introducing-devin-2-2, https://docs.devin.ai/work-with-devin/computer-use, https://docs.devin.ai/work-with-devin/devin-review (Devin)
- [V] https://jules.google/docs/ and https://jules.google/docs/changelog/ (Jules)
- [V] https://cursor.com/docs/cloud-agent, https://cursor.com/blog/agent-computer-use, https://cursor.com/changelog/02-24-26 (Cursor cloud agents)
- [S] https://forum.cursor.com/t/cursor-cloud-agents-do-not-post-their-screenshots-or-videos-to-pr/152974 (Cursor forum)
- [V] https://imbue.com/sculptor (Sculptor)
- [V] https://github.com/BloopAI/vibe-kanban and https://vibekanban.com/blog/shutdown (Vibe Kanban)
- [V] https://github.com/smtg-ai/claude-squad (Claude Squad)
- [V] https://github.com/stravu/crystal (Crystal)
- [V] https://github.com/terragon-labs/terragon-oss (Terragon)
- [V] https://factory.com/ (Factory); [S] https://sacra.com/research/factory (funding)
- [V] https://ampcode.com/manual (Amp); [S] https://tessl.io/blog/sourcegraph-spins-out-ai-coding-agent-amp-as-a-standalone-company/ (spin-out)

### Observability (orchestrator track)
- [V] https://docs.langchain.com/langsmith/observability-quickstart (LangSmith)
- [V] https://langfuse.com/blog/joining-clickhouse (Langfuse joins ClickHouse); [S] https://langfuse.com/changelog/2026-08-28-responsive-timeline.md (Langfuse timeline)
- [V] https://github.com/Arize-ai/phoenix (Arize Phoenix)
- [V] https://www.braintrust.dev/blog/announcing-series-b (Braintrust); [S] https://siliconangle.com/2026/02/17/braintrust-breaks-80m-series-b-funding-round-become-observability-layer-ai/ (valuation)
- [V] https://docs.agentops.ai/v2/introduction (AgentOps)
- [V] https://blogs.cisco.com/news/cisco-announces-the-intent-to-acquire-galileo (Cisco and Galileo); [S] https://galileo.ai/agent-reliability (Galileo UI)

### Stats (stats track)
- [V] https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/ (Octoverse 2025)
- [V] https://octoverse.github.com/ (Octoverse landing page, still the 2025 edition)
- [V] https://github.blog/engineering/architecture-optimization/building-git-infrastructure-for-agent-scale-development/ (GitHub, Oct 6 2026)
- [V] https://github.blog/ai-and-ml/github-copilot/60-million-copilot-code-reviews-and-counting/ (GitHub, Mar 5 2026)
- [V] https://survey.stackoverflow.co/2025/ai (Stack Overflow 2025, AI section)
- [V] https://survey.stackoverflow.co/2026/ai and https://stackoverflow.blog/2026/10/06/the-results-of-the-2026-developer-survey-are-here/ (Stack Overflow 2026)
- [V] https://stackoverflow.blog/2026/05/27/agents-on-a-leash-agentic-ai-remains-mostly-monitored-at-work/ (Agents on a leash)
- [V] https://blog.google/technology/developers/dora-report-2025/ and https://cloud.google.com/blog/products/ai-machine-learning/announcing-the-2025-dora-report (DORA 2025)
- [V] https://dora.dev/insights/balancing-ai-tensions/ (DORA, Mar 10 2026)
- [V] https://arxiv.org/abs/2507.15003 (AIDev dataset)
- [V] https://arxiv.org/abs/2509.14745 (Watanabe et al., Claude Code PRs)
- [V] https://insights.logicstar.ai (Agents in the Wild tracker)
- [V] https://simonwillison.net/2025/Oct/1/prarena/ (S. Willison, agent PR counts)
- [V] https://newsletter.semianalysis.com/p/claude-code-is-the-inflection-point (SemiAnalysis; preview only)
- [V] https://www.anthropic.com/institute/recursive-self-improvement (Anthropic Institute)
- [V] https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ and https://metr.org/blog/2026-02-24-uplift-update/ (METR)
- [V] https://www.faros.ai/blog/ai-software-engineering and https://faros.ai/research/ai-acceleration-whiplash (Faros AI)
- [V] https://linearb.io/resources/engineering-benchmarks-report (LinearB 2026)
- [V] https://www.coderabbit.ai/blog/state-of-ai-vs-human-code-generation-report (CodeRabbit, Dec 17 2025)
- [V] https://www.veracode.com/press-release/ai-generated-code-poses-major-security-risks-in-nearly-half-of-all-development-tasks-veracode-research-reveals/ (Veracode 2025)
- [V] https://www.veracode.com/news/llms-are-getting-smarter-but-not-safer-veracode-2026-genai-code-security-report-finds-ai-generated-code-security-has-stalled-at-56%25-pass-rate/ (Veracode 2026)
