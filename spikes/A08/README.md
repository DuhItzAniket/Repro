# A08 feasibility spikes

Measurement code for phase A08. The findings are in [`RESULTS.md`](RESULTS.md) and the raw data
in `results/`. These scripts are deliberately simple and are not part of the product. Stage D/E
code replaces them.

| Script | Measures | Needs |
|---|---|---|
| `tracer_bench.py` | `sys.monitoring` vs `sys.settrace` overhead: dispatch, capture, budgeted capture | Python 3.12+ only (stdlib) |
| `sandbox_roundtrip.py` | Docker L3 round trip for the `honest-fix` fixture, plus a network-block probe | Docker, the uv workspace |
| `provision_bench.py` | Cold, warm and offline `uv sync` of `pallets/click` 8.5.0 in containers, plus its suite sandboxed | Docker, network (PyPI, GitHub) |

## Reproduce

From the repository root:

```
uv python install 3.12 3.13 3.14
python3.13 -I spikes/A08/tracer_bench.py drive --rounds 5 --repeats 15 > out.json
uv run python spikes/A08/sandbox_roundtrip.py --repeats 3
uv run python spikes/A08/provision_bench.py
```

The Linux-host versions run in CI through `.github/workflows/spikes.yml`, either manually
(`workflow_dispatch`) or when these files change. That workflow uploads the JSON as an artifact.
