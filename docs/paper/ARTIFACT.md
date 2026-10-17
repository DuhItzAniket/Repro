# The artifact: how to check it

> Prepared in J09 (2026-10-18). The study's results do not exist yet: S2 waits for its
> budget, its labels and the freeze (`PREREGISTRATION.md`). This guide covers what can be
> checked now, and it gains the results' commands when J07 and J08 produce them. The archive
> with a DOI is made by the owner (see "Archiving" below).

## What is in it
| Part | Where |
|---|---|
| Repro, the tool | `engine/`, `apps/web/`, `packages/events/`; released as wheels on each GitHub release |
| The study's code | `bench/src/repro_bench/`: adapters, ground truth, baselines, generation, analysis |
| The registered design | `docs/paper/EVALUATION_PROTOCOL.md`, `BASELINES.md`, `ANNOTATION_GUIDELINE.md`, `PREREGISTRATION.md` |
| S2's candidate tasks | `bench/data/s2-candidates.jsonl`: identifiers and SHA-256 per row, fetched by ID (CC-BY-4.0) |
| Every prompt, locked | `bench/src/repro_bench/prompts/lock.json`, `engine/src/repro/agents/prompts/lock.json` |
| The research log | `docs/paper/LOG.md`, negative results included |

## Requirements
- Python 3.13 through `uv` (`uv python install 3.13`), Node.js 22.12 or newer with pnpm 12.11.2
  (for the cockpit), and git.
- Docker with Linux containers: the study runs every task in its own image.
- About 10 GB of disk for one task's image and the caches; network access the first time.
- Windows, macOS or Linux on x86-64. The study's images are `linux/amd64`.

## Kick the tires (about 30 minutes, no API key)
```
uv sync
uv run python scripts/kick_the_tires.py --work <an empty directory>
```
It runs the deterministic part of the pipeline on one fresh task (SWE-rebench
`pypa__twine-1309`) with two patches: the gold patch, and a seeded wrong one.
1. It fetches the task's row and checks it against the SHA-256 the study pinned.
2. It seals both patches under the input contract, with the image pinned by digest.
3. It runs tier A of the ground truth (hidden tests and full suite) in the task's image.
4. It runs B0 (CI-only), then Repro in the task's own image.

It ends with a table and four checks:
- tier A finds the gold patch plausible;
- tier A labels the seeded one INCORRECT_auto;
- CI-only passes both, since no existing test covers the case;
- Repro makes a card for each.

Exit status 0 means all four held. Most of the time is the first pull of the task's image
(about 4.5 GB).

## The tool on its own
`docs/guide/quickstart.md` installs Repro from the release's wheels and makes a first card on a
public repository, in about ten minutes.

## What needs a model
The LLM baselines (B1, B2, B3), Repro's agents, the differential tests and the patch generation
call `openai/gpt-oss-120b` (and `qwen/qwen3.8-27b` for generation) on Groq. They need
`GROQ_API_KEY`. Each records its calls as cassettes. A recorded study replays them with
`--mode replay` and no key, and returns the same answers.

## Archiving (the owner)
- `.zenodo.json` and `CITATION.cff` at the repository's root describe the software. Zenodo's
  GitHub integration reads `.zenodo.json` when a release is published [developers.zenodo.org].
- Before the first archive, check them:
  - the creators' names (a GitHub handle stands in, since the repository carries no personal
    names);
  - the licence identifier Zenodo expects;
  - the description.
- The study's data (labels, answers, event logs, cassettes) is archived with the results, after
  J07: identifiers and digests for third-party tasks, never their content.
