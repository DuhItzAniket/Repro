# I03 — GitHub Action & attestation signing

| | |
|---|---|
| **Stage** | I — GitHub integration |
| **Status** | in progress |
| **Depends on** | I02, H04 |
| **Branch / PR** | `phase/I03-action` · PR pending |
| **Started / finished** | 2026-10-17 / — |

## Objective
A repository adds one step to a workflow, and every pull request gets its Reproduction Card: the
check run, the comment, the job's summary, and on a public repository a signed attestation.

## Owner decisions (2026-10-17)
- **Forks: safe by default, opt-in.** A pull request from the repository itself is posted to.
  A fork's pull request is run, and its card goes to the job's summary and an artifact; posting
  for forks is the maintainer's opt-in (`post-on-forks`), which needs `pull_request_target`,
  with the risk documented and gVisor recommended.
- **The signed subject is the card.** GitHub's attestations take `sha256` subjects only; the
  Action signs the card's canonical JSON, with the head commit, the log's digest and the
  evidence in Repro's predicate (ADR-0012, implementation note I03).

## Scope
- **`action.yml`** at the repository's root (`uses: DuhItzAniket/Repro@<ref>`), a composite
  action: `setup-uv`, Repro installed from the Action's own checkout (`uv sync --frozen
  --no-dev`), then plan, run, keep the card (`actions/upload-artifact`), report, sign
  (`actions/attest`). Every action it uses pinned to a commit.
- **`repro.integrations.github.action`**: `plan` (from the event: the pull request, fork or not,
  post or not, sign or not), `run` (Repro on the pull request; `card.json` exactly the card's
  canonical bytes, `card.md`, the predicate), `report` (to the pull request, or the summary
  alone).
- **Caching**: Repro's mirror and test maps (`actions/cache`), keyed by the base commit.
- **The guide**: `docs/guide/github-action.md`, with both workflows and how to check a signed card.

## Out of scope
- A GitHub App (I04, built only if users ask for it).
- Publishing the Action to the Marketplace.

## Design notes
- **Composite, not a container action.** Repro runs target code in its own Docker sandbox; a
  container action would need Docker inside it. Run on the runner, Repro uses the runner's
  Docker directly. Container actions are also Linux-only and slower to start [GitHub docs,
  "About custom actions", checked 2026-10-17].
- **No checkout of the pull request.** Repro fetches it into its mirror, as I01 does, and
  writes it only into its own scratch copies, which it reads on the runner and runs only in
  the sandbox.
- **Containers only.** The Action sets `REPRO_SANDBOX=docker`. With `auto`, a runner without
  Docker would fall back to a contained process (L2), which runs as the job's user and so
  beside the token; with `docker`, such a runner's run says the sandbox could not start
  instead.
- **Logic in Python.** What the YAML would otherwise decide in expressions is in a module with
  tests; the YAML's steps are checked against it (every output a step reads is one written).

## Acceptance criteria
- [x] AC1 (roadmap): the Action runs Repro on Linux runners with Docker, caches, and signs with
  `actions/attest` using the Repro predicate.
- [x] AC2: a fork's pull request is not posted to unless the workflow opts in under
  `pull_request_target`.
- [x] AC3: the signed subject's digest is the card's own, and Repro's checker accepts it.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_github_action.py`: `run` and `report` end to end against the fake GitHub; `action.yml` pinned and consistent. On GitHub itself: Gate I |
| AC2 | `plan` for each event: this repository, a fork under each trigger, with and without the opt-in, a deleted fork, a private repository |
| AC3 | `card.json`'s SHA-256 equals the predicate's `cardDigest`; `test_exports.py`: a statement with the card as subject gives the card back, a wrong digest none |

---
*Filled in at the end of the phase:*

## What shipped
- **`action.yml`**: the composite action, its six inputs (`token`, `post-on-forks`, `attest`,
  `agents`, `docker-runtime`, `analyse-only`) and four outputs (`status`, `run-id`, `card`,
  `attestation-url`). It pins `astral-sh/setup-uv` v10.3.0, `actions/cache` v6.1.0,
  `actions/upload-artifact` v7.0.2 and `actions/attest` v4.2.2 to their commits, and runs the
  pull request's code in containers only (`REPRO_SANDBOX=docker`).
- **`repro.integrations.github.action`**: `plan`, `run`, `report`, and `main` for the steps.
- **`card_from_attestation`** accepts the card itself as the subject, checked against
  `cardDigest`, beside the head commit.
- **Docs**: `docs/guide/github-action.md` (both workflows, permissions, forks, checking a signed
  card, agents, caching), the guide's index, the README, ADR-0012 (implementation note I03),
  the predicate's description, ARCHITECTURE §4, THREAT_MODEL T20 (a fork's pull request and a
  write token).
- **Tests**: `test_github_action.py` (9), `test_exports.py` (the card as subject).

## Evidence
- **Locally**: `test_github_action.py` 9 passed: every plan; `run` and `report` against the fake
  GitHub, with `card.json`'s SHA-256 equal to the predicate's `cardDigest`, a fork's report to
  the summary alone and a posted one making the check run and the comment; `action.yml` pinned,
  its steps' outputs and inputs consistent, containers required. `test_exports.py` 14 passed.
- CI run: linked in the PR.

## Deviations from spec
- **A composite action, not a Docker container action.** The roadmap's "Docker-based Action" is
  met by Repro's Docker sandbox on the runner; a container action would need Docker inside a
  container to run Repro's own (design notes).

## Known gaps
- **Not yet run on GitHub**: Gate I runs it on the owner's public test repository.
- **Environments are not cached.** In containers they are Docker volumes, which `actions/cache`
  does not keep; each run builds them again. The mirror and the test maps are cached.
- **A runner without Docker** gets a card saying the sandbox could not start, by design: the
  Action does not fall back to a contained process.

## Dependencies added
None in the engine. The Action uses four pinned actions (above).

## Research notes
- **Where the token lives decides the design.** Under `pull_request_target` the job that runs a
  fork's code holds a write token. Repro's isolation keeps the code in containers and the token
  out of them, but the token is still on the runner; so posting for forks is an opt-in, and a
  contained process, which shares the job's user, is never used by the Action.
