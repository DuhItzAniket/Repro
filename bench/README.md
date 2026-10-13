# repro-bench

The evaluation harness for Repro (Stage J): SWE-format dataset adapters, baselines,
ground-truth tooling and analysis. The protocol is in
[`docs/paper/EVALUATION_PROTOCOL.md`](../docs/paper/EVALUATION_PROTOCOL.md).

The benchmark drives Repro through its CLI and API only. It never imports engine internals.
