# repro-bench

The evaluation harness for Repro (Stage J): SWE-format dataset adapters, baselines,
ground-truth tooling and analysis. The protocol is in
[`docs/paper/EVALUATION_PROTOCOL.md`](../docs/paper/EVALUATION_PROTOCOL.md).

What is here so far:

| Module | Phase | What it measures |
|---|---|---|
| `repro_bench.claims` | G04 | The reader agent on labelled PR descriptions, from cassettes |
| `repro_bench.verdicts` | G09 | Reviewed PRs end to end: verdict accuracy, flips, cost |
| `repro_bench.scale` | H02 | `repro run` on three pinned real repositories, cold and warm |
| `repro_bench.swe` | J01 | SWE-format instances and agent patches as sealed inputs, a manifest, and `repro run` on them |
| `repro_bench.truth`, `difftest`, `groundtruth` | J02 | Ground truth: tier A (hidden tests, full suite) and tier B (differential tests) in the task's image |
| `repro_bench.labels`, `annotate` | J02 | Blinded annotation pages, Cohen's κ, adjudication, the label freeze |
| `repro_bench.baselines` | J03 | B0 CI-only, B1 diff-only LLM, B2 agentic static LLM, B3 PR-Agent, on sealed inputs |
| `repro_bench.seed`, `memo`, `power` | J04 | Seeded S0 patches, the memorisation probe, McNemar sample sizes |
| `repro_bench.tasks`, `generate`, `edits` | J05 | S2's candidate tasks, and agent patches from a two-call localize-and-repair scaffold |
| `repro_bench.analysis` | J06 | The registered analysis: rates, coverage, exact McNemar with Holm, cluster bootstrap |

Each runs `repro run` through its CLI, or calls the agents as the engine does, and reads what a
run stored through `repro.store`. Results go to `bench/results/`.

`data/s2-candidates.jsonl` lists S2's candidate tasks by identifier, with each row's SHA-256,
from [nebius/SWE-rebench-leaderboard](https://huggingface.co/datasets/nebius/SWE-rebench-leaderboard)
(CC-BY-4.0) at revision `34d5a58864acf91613740a09ec5d205228dcfa39`. The tasks themselves are
fetched by identifier, never stored here; each repository keeps its own licence.

