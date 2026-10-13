# Perf gate baseline

`frame-cost-baseline.json` is the reference for the frame-cost gate
(`src/perf/frame-cost.perf.ts`, B12). It is recorded **in CI only**, on the runner the gate runs
on. A developer machine has different relative speeds: on the machine B12 was built on, the
calibrated p50 ratio was about 0.037, against 0.0496 in CI.

- **Source:** the `perf` artifact of the CI `gates` job (ubuntu-latest, Node 24.21.0), run
  38462556161, recorded on 2026-10-13.
- **Values:** p50 0.27 ms, p95 1.50 ms per frame on the stress burst; calibration 5.46 ms.
- **Gate:** the calibrated p50 and p95 may be at most 30% above these ratios.

To refresh after an intended change: delete this file and push. The `gates` job then records a
new candidate, uploads it as the `perf` artifact, and fails until the candidate is committed
here.
