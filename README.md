# Repro

**Every agent-written change, reproduced and verified before it merges.**

Repro runs both sides of a pull request (base and head) in isolation, records what each side
actually *does*, and checks every behavioural difference against what the PR *claims*. The
result is a **Reproduction Card** with one of three verdicts:

- **VERIFIED**: every claim is supported by evidence, nothing changed that wasn't claimed, and
  invariants hold.
- **FLAGGED**: there is a contradicted claim, an unexplained behaviour change, a broken or
  weakened test, or a failed invariant.
- **UNVERIFIABLE**: too much could not be checked, and the card says exactly what and why.

> Not "does it work?", but **"what did it change, and did it say so?"**

> **Status: v1.2.0, Stages A to I done, Stage K's first items built.** Repro runs both sides
> of a change in a sandbox, compares what they do, checks invariants, has agents judge the
> PR's claims against the evidence, and shows it all live in the cockpit; on GitHub, its
> Action reports each pull request's card and signs it. The evaluation study (Stage J) is
> prepared and deferred. Progress is tracked in the [roadmap](docs/ROADMAP.md).

## Why

Coding agents now open pull requests faster than people can review them. Tests pass, the
description sounds right, and the change still does something else. Published examples:

- About 30% of "plausible" agent patches on SWE-bench Verified behave differently from the
  reference fix ([Wang, Pradel & Liu, ICSE 2026](https://arxiv.org/abs/2503.15223)).
- In agent PRs whose description doesn't match the code, the most common mismatch is claiming
  changes that were never made ([Gong et al., 2026](https://arxiv.org/abs/2601.04886)).

Repro produces the evidence a reviewer needs to trust or reject such a change.

## How it works

```
PR ─► READ claims ─► BUILD isolated snapshots + blast radius ─► RUN base ‖ base′ ‖ head
   ─► DIFF outcomes · tests · behaviour · API · deps · perf ─► CHECK invariants
   ─► REVIEW claims against cited evidence ─► CARD (deterministic status)
```

- **Function-level behaviour diff.** Tests that exercise the change run on both sides. A
  `sys.monitoring` tracer records inputs, outputs and exceptions of affected functions. A second
  base run measures noise, so only stable differences count.
- **Generated probes.** Changed code that existing tests don't reach is exercised by generated
  differential tests.
- **Claims are checked, not trusted.** LLM reviewers may only issue verdicts that cite evidence
  IDs produced by the engine. Uncited verdicts are rejected. The final status comes from
  deterministic rules.
- **Nothing is silently unverified.** Anything Repro could not check appears under *Missing*,
  with a reason.
- **Isolated and honest about it.** Target code runs in throwaway snapshots inside a container
  with networking disabled when Docker is available. The card always states the isolation level
  actually achieved.
- **Replayable.** Every run is an append-only event log. The live, animated cockpit and the card
  are pure projections of it.

## Install

Repro needs [uv](https://docs.astral.sh/uv/) and git. Docker is optional: with it, runs reach
isolation level L3, the target's code in a container with no network.

Each GitHub release from v1.0.0 carries two wheels, `repro-engine` (the command and the
cockpit) and `repro-events` (the event schemas). Install both as one tool, with Python 3.13:

```
uv tool install --python 3.13 --from "repro-engine @ https://github.com/DuhItzAniket/Repro/releases/download/v<version>/repro_engine-<version>-py3-none-any.whl" --with "repro-events @ https://github.com/DuhItzAniket/Repro/releases/download/v<version>/repro_events-<version>-py3-none-any.whl" repro-engine
repro doctor
repro run --repo <path> --base <ref> --head <ref>
```

`repro doctor` says what this machine can do. `repro run` serves the cockpit and prints its
address, which follows the run live (`--open` opens it in the browser). CI makes this same
install, and a first run on a small repository, on Linux and Windows for every change, inside
ten minutes (`scripts/install_check.py`). PyPI comes later. To work on Repro itself, run it
from a checkout: `uv sync`, `pnpm install` and `pnpm build`, then `uv run repro ...`
([CONTRIBUTING](CONTRIBUTING.md)).

New to Repro? The [quickstart](docs/guide/quickstart.md) goes from nothing to a first card, and
[the demo](docs/guide/demo.md) shows one run, from the command to the card. To run it on every
pull request: [the GitHub Action](docs/guide/github-action.md).

## Documentation

**Using Repro:** [the guide](docs/guide/README.md): the [quickstart](docs/guide/quickstart.md),
[reading a card](docs/guide/reading-a-card.md), [`repro.yml`](docs/guide/repro-yml.md),
[troubleshooting](docs/guide/troubleshooting.md) and [the demo](docs/guide/demo.md).

**How it is made:** start with [docs/README.md](docs/README.md). Key documents:
[Product](docs/PRODUCT.md) ·
[Research & positioning](docs/RESEARCH.md) ·
[Architecture](docs/ARCHITECTURE.md) ·
[Roadmap](docs/ROADMAP.md) ·
[Implementation plan](docs/IMPLEMENTATION_PLAN.md) ·
[Design](docs/DESIGN.md) ·
[Threat model](docs/THREAT_MODEL.md) ·
[Development process](docs/process/SDLC.md)

## Roadmap at a glance

| Stage | Outcome | Release |
|---|---|---|
| A Foundation | Monorepo, event schema as contract, CI on Windows + Linux | v0.1 |
| B Cockpit | Animated mission-control UI driven by recorded event logs | v0.2 |
| C Engine core | Live graph and blast radius of a real repository | v0.3 |
| D Execution | Sandboxed base/head test runs, outcome and test-tampering evidence | v0.4 |
| E Behaviour evidence | Silent behaviour changes caught without failing tests | v0.5 |
| F Policy & card | Invariants and a complete deterministic card | v0.6 |
| G Agents | Claim extraction, evidence-constrained verdicts, generated probes | v0.7 |
| H Hardening | Installable, documented, hardened | **v1.0** |
| I GitHub | Check runs, sticky PR comments, signed attestations | v1.1 |
| J Evaluation | Reproducible benchmark and paper | v1.2 |

## Contributing & security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Repro executes untrusted
code by design. Please report isolation issues privately.

## License

[Apache License 2.0](LICENSE). Third-party components keep their own licences. For example, the
JetBrains Mono font (from Stage B) is under the SIL Open Font License 1.1, and its licence ships
alongside it.
