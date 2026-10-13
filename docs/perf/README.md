# Performance records

Measured, never assumed (DESIGN.md "Performance budget"). Each file records its method,
hardware and raw numbers; summaries live in the phase records.

| File | Phase | What |
|---|---|---|
| [`B04-stress-bench.json`](B04-stress-bench.json) | B04 | Stage foundation under the stress load (10k edges, 2,048 streaks) on an integrated GPU, DPR 1–2 (corrected run; see its `correction` field) |
| [`B05-web-bench.json`](B05-web-bench.json) | B05 | The real dependency-web layers (10k edges, blast markers, bundles) plus proxies, same machine and method |
| [`B06-ring-bench.json`](B06-ring-bench.json) | B06 | Web plus the real ring (cards, ticks); only streaks are still a proxy |
| [`B07-streams-bench.json`](B07-streams-bench.json) | B07 | The complete stage, every layer real, 2,048 live streaks at peak |

## Reproducing the stage benchmark

```
pnpm --filter @repro/web dev
# open http://localhost:5173/bench.html?seconds=8&dpr=1,1.5,2   (add &layers=proxy for B04's proxies only)
# results appear on the page and in window.__REPRO_BENCH__
```

Keep the page visible while it runs: hidden pages throttle `requestAnimationFrame`, and the
report counts visibility changes (`hiddenDuringRun`) so a throttled run can be discarded.
