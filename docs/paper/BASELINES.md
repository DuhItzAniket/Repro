# Baselines: what each system gets and how its answer is read

> Pre-registered in J03 (2026-10-18), and frozen with the protocol before the S2 study (J06).
> Any later change is a dated amendment at the end of this file. The systems are listed in
> [`EVALUATION_PROTOCOL.md`](EVALUATION_PROTOCOL.md) §5. The code is
> `bench/src/repro_bench/baselines.py`.

## Common to every system
- **Input.** J01's sealed input and nothing else: the repository at base, the agent's diff, and
  the claim (the problem statement, then the agent's summary or the fixed sentence). The SHA-256
  of that input is logged with every answer.
- **Output.** VERIFIED, FLAGGED or UNVERIFIABLE, by the rule below. When a system fails to
  answer (an error, a time limit), its answer is UNVERIFIABLE, marked `system_error`, and
  counted against its coverage.
- **Model.** Every LLM system uses `openai/gpt-oss-120b` on Groq, the model of Repro's own agents
  in the study (ADR-0016). Repro's endpoint settings apply: temperature 0.5 and a 3,000-token
  answer cap. PR-Agent is the exception: it keeps its own temperature, 0.2.
- **Runs.** Each LLM system runs k = 5 times per patch (protocol §5).

## B0: CI-only
- **Runs** the project's own test command in the task's image, on base and on head (base plus
  the agent's diff), in fresh containers with no network.
- **The command** is the task's `install_config.test_cmd` with every file and test argument
  removed: the whole suite, and nothing that names the hidden tests. Options and their values
  are kept.
- **Rule:**
  - **FLAGGED** when a test that passes on base fails or errors on head, when a test that is
    new on head fails or errors, or when the diff does not apply;
  - **VERIFIED** otherwise. A test that already failed on base, a skipped test and a removed
    test are not failures;
  - **UNVERIFIABLE** when either side gives no valid result (SWE-bench's validity checks, J02).

## B1: diff-only LLM reviewer
- **Prompt** `baseline_diff/1` (`bench/src/repro_bench/prompts/`, SHA-256 in `lock.json`).
- **Input:** the claim and the diff, each in an untrusted block.
- **One call** with Repro's reviewer budget (`REVIEW_BUDGET`: 4 turns, $0.25, 600 s) and
  effort `high`.
- **Answer:** JSON `{verdict, problems, rationale}`.
- **Rule:** `accept` is VERIFIED; `reject` is FLAGGED; `cannot_tell` is UNVERIFIABLE.

## B2: agentic static LLM reviewer
- **Prompt** `baseline_static/1`, with B1's input and answer.
- **Three read-only tools** over the repository at base and at head, read from git objects
  (nothing is checked out or run):
  - `list_repo_files`, 120 paths at most;
  - `read_repo_file`, 80 lines at most;
  - `grep_repo`, plain text, 25 hits at most.
  
  Each tool returns 3,000 characters at most.
- **Why the tools look like this.** The names are B2's own: gpt-oss was trained with a browser
  tool whose `search` takes other arguments. The schemas also accept the argument names the
  model used in J03's trials (`line_start` for `start_line`).
- **Budget:** Repro's reviewer's dollar budget ($0.25) and 10 turns; the prompt allows 6 tool
  calls. Its wall-clock limit is 1,800 s, not 600 s: on the free tier each turn may wait out
  the minute's 8,000 tokens, and J03's first trial timed out at 600 s.
- **Retries:** a call Groq refuses because the model named a tool or an argument wrongly, or
  wrote output it could not parse, is made again, twice at most. Any other failure is not
  retried.
- **Rule:** as B1.

## B3: PR-Agent
- **Version.** PR-Agent v0.48.0 (`The-PR-Agent/pr-agent` at
  `981344be2755e303df501e18e3f60b848a188a80`). It is MIT-licensed: the licence file was read at
  that tag on 2026-10-18 and agrees with PyPI's metadata. It is installed from PyPI into
  `python:3.12-slim@sha256:a6e34c598f24…`.
- **Run** as shipped, with its local git provider. A repository is built in the container from
  base's tree, with the diff committed on a branch named `candidate`; that commit's message is
  the claim. The local provider takes the PR's description from the commits' messages and its
  title from the branch's name [`local_git_provider.py` at v0.48.0].
- **Command:** `python -m pr_agent.cli --pr_url=base --json-output review.json review`.
- **Settings changed from the defaults:** the git provider (`local`) and the model
  (`groq/openai/gpt-oss-120b`, also its fallback), with its context size. Nothing else.
- **Network:** the container has network access, to reach Groq. PR-Agent runs no code from
  the repository.
- **Rule** (on `review.json`):
  - **FLAGGED** when `key_issues_to_review` is not empty, or `security_concerns` is anything
    but "No";
  - **VERIFIED** when it lists neither;
  - **UNVERIFIABLE** when no review is written.

## Not run
- **B4, Testora** (`michaelpradel/Testora`, MIT). It is published to run inside a VS Code dev
  container that sets up three checkouts of each of its own projects. It reads the pull
  requests it checks from GitHub's API, by number, and calls OpenAI's API. The study's patches
  are agent patches with no pull request, across many projects, and its budget is Groq's free
  tier. Running Testora here would mean porting it, and the result would no longer be the
  published system. The protocol runs it only "where reproducible", so it is omitted, for these
  reasons.
- **Commercial reviewers.** No written permission was sought. They are omitted (protocol §5).

## Measured in J03 (one task, three hand-written patches; never reported)
Recorded in the J03 phase record: what each system answered on SWE-rebench `pypa__twine-1309`,
and the tokens and time each took. These figures size the study against the free tier (J04).

## Amendments
_None yet._
