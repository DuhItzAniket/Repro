# Performance records

Measured, never assumed (DESIGN.md "Performance budget"). Each file records its method,
hardware and raw numbers; summaries live in the phase records.

| File | Phase | What |
|---|---|---|
| [`B04-stress-bench.json`](B04-stress-bench.json) | B04 | Stage foundation under the stress load (10k edges, 2,048 streaks) on an integrated GPU, DPR 1–2 |

## Reproducing the stage benchmark

```
pnpm --filter @repro/web dev
# open http://localhost:5173/bench.html?seconds=8&dpr=1,1.5,2
# results appear on the page and in window.__REPRO_BENCH__
```

Keep the page visible while it runs: hidden pages throttle `requestAnimationFrame`, and the
report counts visibility changes (`hiddenDuringRun`) so a throttled run can be discarded.
