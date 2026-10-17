# I01 — PR ingestion

| | |
|---|---|
| **Stage** | I — GitHub integration |
| **Status** | in progress |
| **Depends on** | H05 |
| **Branch / PR** | `phase/I01-pr-ingestion` · PR pending |
| **Started / finished** | 2026-10-17 / — |

## Objective
`repro run --pr <url>` reproduces a GitHub pull request from its URL alone: the commits it
compares, its title and description, from a fork or not, with nothing to clone or check out
by hand.

## Scope
- **The PR, from GitHub's REST API.** `GET /repos/{owner}/{repo}/pulls/{pull_number}`, with
  `Accept: application/vnd.github+json` and `X-GitHub-Api-Version: 2026-03-10`, the newest
  version (`2022-11-28`, the default, is supported until 2028-03-10; the newer one removes
  `merge_commit_sha`, which Repro does not use) [GitHub REST API docs, "API versions" and
  "Breaking changes", checked 2026-10-17]. A token from `GITHUB_TOKEN`, else `GH_TOKEN`, when
  one is set: public repositories need none, at 60 requests an hour, against 5,000 with a
  personal token and 1,000 for an Actions `GITHUB_TOKEN` per repository [GitHub REST API docs,
  "Rate limits for the REST API", checked 2026-10-17].
- **The commits, fetched into a mirror of Repro's own** (`<data dir>/repos/<host>/<owner>/
  <repo>.git`, bare): the base branch and `refs/pull/<n>/head`, the read-only ref GitHub keeps
  on the base repository for every pull request, a fork's included [GitHub docs, "Checking out
  pull requests locally", checked 2026-10-17]. With a token, git authenticates as
  `actions/checkout` does, an `AUTHORIZATION: basic` header of `x-access-token:<token>` for the
  host [actions/checkout `src/git-auth-helper.ts`, checked 2026-10-17], set through git's
  `GIT_CONFIG_COUNT` variables, so it is on no command line [git-config docs, ENVIRONMENT,
  checked 2026-10-17].
- **What is compared.** Head is the PR's head commit, checked against what the API says it is.
  Base is the merge base of the PR's base and head commits: the change the PR itself makes, as
  GitHub's "Files changed" shows it, not what the base branch did since.
- **What the run records.** `run.started` carries the repository (`owner/repo`, its URL) and the
  PR (title, number, URL), fields the schema has had since A05. The PR's title and description
  are the reader's PR text, as `--pr-title` and `--pr-body` are. A fork's head is named by its
  label (`owner:branch`).
- **`--repo` with `--pr`**: a local clone instead of the mirror, fetched by nobody: if a commit
  is not in it, `repro run` says which `git fetch` brings it.
- **Errors in words**: a PR that does not exist (or is private, without a token), a token
  refused, a rate limit (with when it resets), no network. Exit 2, the token never printed.

## Out of scope
- Reporting back to GitHub (check run, comment, summary): I02.
- The GitHub Action and attestation signing: I03.
- GitHub Enterprise Server beyond pointing `github_api_url` at its API.

## Design notes
- **Stdlib HTTP.** The engine has no HTTP client among its runtime dependencies; one GET with
  JSON needs none (`urllib.request`), and adds no dependency to the release's wheels.
- **The mirror is Repro's**, under its data directory, never the user's clone: fetching into a
  user's repository would add refs and objects they did not ask for.
- **Untrusted text.** The PR's title and description are the author's: they reach the reader in
  untrusted blocks (G03), and the card's `pr.title` is capped by the schema.

## Acceptance criteria
- [x] AC1 (roadmap): a PR URL becomes refs, description and commits; from a fork too.
- [x] AC2: the token is used for the API and the fetch, and reaches no event, log, card or
  command line.
- [x] AC3: every failure to read the PR exits 2 with a reason a person can act on.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | A fake GitHub API (stdlib server) and a local bare repository with `refs/pull/1/head` on a commit no branch holds (a fork's): `repro run --pr` records the PR and the merge base |
| AC2 | The fake API sees the token; the fetch's environment carries the header; neither the events nor the logs hold the token |
| AC3 | 404, 401, 403 with the rate limit spent, a refused connection |

---
*Filled in at the end of the phase:*

## What shipped
- **`repro.integrations.github`**:
  - `api` (`GitHubApi`: one GET, the version and `User-Agent` headers, the token as `Bearer`, a
    redirect to another host without it, failures in words);
  - `pr` (`PrUrl`, `read_pr`: the API's answer checked, commits as 40 hex digits, the base
    branch's name as a ref);
  - `mirror` (the bare mirror, the fetch with the token in `GIT_CONFIG_*`, a clone URL that is
    not `https` refused unless the API is a loopback test server, the merge base);
  - `ingest`.
- **`repro run --pr <url>`**, with `--repo` for a clone of the user's own. `--repo`, `--base`
  and `--head` are now optional: both refs, or a pull request. Its first line names the pull
  request, its state, a fork, its head and the merge base; never its title, which is its
  author's text.
- **The run records the pull request**: `run.started`'s `repo` (name and URL) and `pr` (title,
  number, URL), through `Change` and `RunSpec`. The Markdown card links the repository and the
  pull request and shows the title as text, escaped, never as Markdown.
- **Setting `github_api_url`** (`REPRO_GITHUB_API_URL`): `https`, or `http` on a loopback address
  for tests.
- **Docs**: the quickstart ("Or give it a pull request"), troubleshooting (pull requests, two
  settings), reading a card (a pull request's base and head), the engine README, ARCHITECTURE
  §4 (ingest), THREAT_MODEL T12 (where the token goes), CLAUDE.md's commands.
- **Tests**: `test_github_ingest.py` (23), `test_card.py` (the pull request on the card),
  `test_cli.py` (both refs, or a pull request).

## Evidence
- **A real pull request**, `https://github.com/pallets/itsdangerous/pull/378`, read anonymously
  from GitHub's API and fetched into a fresh mirror (`--analyse-only`): head `pallets:fips-sha1`
  at 7f4dcf83a07b, compared with `main` where it branched, 93ae366874bb. That is the pair H06's
  first reviewer chose by hand from the repository's history. `run.started` carried
  `pallets/itsdangerous` and the pull request's number, title and URL.
- **Locally**: `test_github_ingest.py` 23 passed, and the CLI, card, run, config, paths,
  orchestrator and doctor tests around the change.
- CI run: linked in the PR.

## Deviations from spec
- **Commits from git, not the API.** The roadmap names the API for the commits; the reader's
  commit messages are read from the mirror (`git log` from the merge base to the head), which
  has them all, where the API lists at most 250 [GitHub REST API docs, "List commits on a pull
  request", checked 2026-10-17].

## Known gaps
- **GitHub Enterprise Server** is reached through `github_api_url` alone, untested against a
  real server.
- **A base branch rewritten since the pull request was last updated** can leave its recorded
  base commit out of what is fetched; the run then stops, saying the pull request moved.
- **The mirrors are kept** under the data directory and never pruned: deleting `repos/` there
  reclaims the space; the next `--pr` fetches again.

## Dependencies added
None: the standard library's `urllib` reads the API.

## Research notes
- **The merge base, not the base branch's tip.** Comparing a pull request's head with its base
  branch as it is now would count every change the base branch made since as the pull
  request's, reversed. GitHub's "Files changed" compares with the merge base, and so does
  Repro. Testing the merge result instead would need GitHub's test merge commit, which the
  2026-03-10 API version no longer returns (`merge_commit_sha`) [GitHub REST API docs,
  "Breaking changes", checked 2026-10-17].
