# J01 — Benchmark infrastructure & input contract

| | |
|---|---|
| **Stage** | J — Evaluation & research |
| **Status** | done |
| **Depends on** | H05 |
| **Branch / PR** | `phase/J01-benchmark-infra` · [#82](https://github.com/DuhItzAniket/Repro/pull/82) |
| **Started / finished** | 2026-10-18 / 2026-10-18 |

## Objective
SWE-format tasks and agent patches become Repro runs under the evaluation's input contract
(`docs/paper/EVALUATION_PROTOCOL.md` §2, ADR-0010): every system sees the repository at base,
the agent's diff and the claim text, and nothing of the ground truth. What ran is pinned in a
manifest.

## Scope
- **The formats, as published.** An instance: `instance_id`, `repo`, `base_commit`,
  `problem_statement`, and the ground truth `patch`, `test_patch`, `FAIL_TO_PASS`,
  `PASS_TO_PASS`, `hints_text` [SWE-bench dataset card, princeton-nlp/SWE-bench, checked
  2026-10-18]. SWE-rebench adds the task's environment image (`docker_image`, `image_name`)
  [nebius/SWE-rebench dataset card, checked 2026-10-18]. A prediction: one JSON object a line
  with `instance_id`, `model_name_or_path`, `model_patch` [SWE-bench,
  `docs/guides/evaluation.md`, checked 2026-10-18].
- **Sealing** (`repro_bench.swe.seal`): a system's input is built from an allow-list (`repo`,
  `base_commit`, the diff, the claim), so a field a dataset adds later is withheld too. The claim
  is the problem statement, then the agent's summary or the protocol's fixed sentence. The
  instance ID is withheld as well: it carries a GitHub number (`repo_owner__repo_name-
  issue_number`, as SWE-bench's guide writes it) that leads to the fix.
- **Two steps, so the runner never reads a dataset.** `seal` reads instances and predictions
  and writes `sealed.jsonl` and `manifest.jsonl`; `run` reads `sealed.jsonl` alone. A sealed row
  whose input was changed (its SHA-256 no longer matches) or widened (any key beyond the four)
  is refused.
- **Base and head.** Base is fetched by its hash into a bare mirror. Head is the diff applied to
  a temporary index of base (`read-tree`, `apply --cached`, `write-tree`, `commit-tree`, fixed
  identity and dates): no working tree, nothing of the target checked out (ground rule 5), and
  the same input makes the same commit.
- **Repro's input.** `repro run --repo <mirror> --base <sha> --head <sha> --pr-file <file>`:
  the title is the claim's first line (the issue's title), the description the claim. A file,
  not arguments: a problem statement can pass Windows' command-line limit.
- **Results** (`results.jsonl`): instance, model, patch SHA-256, the sealed input's SHA-256,
  head, run ID, the card's status or why there is none, seconds, Repro's version; each card in
  `cards/<run id>.json`.
- **The manifest**: instance, dataset, split and revision, repository, base commit, image by
  digest, patch SHA-256, model, label (CORRECT, INCORRECT or UNCERTAIN, once J02/J06 give one).
  An image is pinned by the registry digest Docker recorded when it pulled it; an unpinned
  reference is refused.

## Out of scope
- Running Repro inside a task's environment image: Repro provisions its own environment
  (D03). Whether and how it uses the task's is J04's pipeline shake-out (see Known gaps).
- Ground truth (J02), baselines (J03), the datasets themselves (J04, J05).

## Acceptance criteria
- [x] AC1 (roadmap): instance + patch → base/head, without a working tree.
- [x] AC2 (roadmap): images managed by digest; the manifest format, checked on read and write.
- [x] AC3 (roadmap): a test proves no withheld field reaches the engine.
- [x] AC4: one real SWE-format instance runs end to end and its card says what happened.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_bench_swe.py`: head is base plus the diff, the mirror is bare with nothing checked out, the same input makes the same commit, a diff that does not apply is refused |
| AC2 | Manifest round trip; an unpinned image and an unknown label refused; image references named as Docker records them; pinning against recorded digests (Docker faked) |
| AC3 | A canary in every withheld field, in a field the dataset does not have yet and in the instance ID: none in the sealed input, the PR text, `repro run`'s event log or its card, from a real `repro run` |
| AC4 | SWE-bench Verified's `pallets__flask-5014`, sealed and run |

---
*Filled in at the end of the phase:*

## What shipped
- **`repro_bench.swe`**: `Instance`, `Prediction`, `Sealed`, `Task`, `seal`, `fetch_base`,
  `head_commit`, `run_task`, the manifest (`Entry`, `write_manifest`, `read_manifest`), images
  (`repository`, `pinned`), and the command (`python -m repro_bench.swe seal | run`).
- **The card names a warning that stopped a run.** `error_line` took `Error`, `Exception` and
  `Exit` lines only, so a run stopped by a warning the project makes an error
  (`filterwarnings = error`) was reported by pytest's first line, "ImportError while loading
  conftest". It now names the warning (`readable.py`).
- **The protocol** (§2): the sealing as built, and the open question below for J04.
- **Tests**: `test_bench_swe.py` (18), `test_readable.py` (2).

## Evidence
- **A real instance**, SWE-bench Verified `pallets__flask-5014` (dataset revision
  `c104f840cc67`), with its gold patch standing in for an agent's (a smoke test, never a
  result). Sealed, fetched and run with the process sandbox in 13 to 21 s: UNVERIFIABLE, with
  `run_incomplete` on both sides. Run twice, the head commit (`38f01b801287`) and the input's
  SHA-256 were the same.
- **Why it could not run**, reproduced in a throwaway container: the task pins pytest 7.2.2
  (`requirements/tests.txt`), whose assertion rewriter touches `ast.Str`; Python 3.13 warns, and
  Flask's `filterwarnings = ["error"]` makes the warning an error before any test runs. Before
  the fix the card said only "ImportError while loading conftest"; after it, the warning.
- **Locally**: `test_bench_swe.py` 18 passed; `test_readable.py` 2 passed.
- CI run: linked in the PR (#82).

## Deviations from spec
None.

## Known gaps
- **The task's environment.** Repro's tracer needs Python ≥ 3.12 (`sys.monitoring`), and Repro
  installs a project's dependencies itself. A task's pins can fail there, as Flask's did. J04
  decides, before any S2 data exists, between S2 tasks whose environment runs on Python ≥ 3.12
  and running older ones without traces, and records it in the protocol.
- **Mirrors are kept** under `--mirrors` and never pruned.

## Dependencies added
None.

## Research notes
- **An instance's ID is ground truth too.** The protocol's withheld list named the gold patch,
  test patch, test lists and hints. The ID carries a GitHub number that leads to the fix, so a
  system with web access, or a model that saw the repository's history, could use it. The
  sealed input leaves it out, and the PR title Repro gets is the issue's title.
- **Old tasks and new interpreters.** A benchmark task's environment is part of the task: a
  2023 task's pinned test tools do not run on the interpreter Repro needs. This is a selection
  effect for any execution-based reviewer that needs a recent Python, and is stated as such.
