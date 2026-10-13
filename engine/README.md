# repro-engine

The Repro engine: orchestrator, event bus, storage, sandboxed two-sided execution, behaviour
tracing, diffing, policy, agents and card export. The design is in
[`docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

The import package is `repro` (src layout: `engine/src/repro/`). The console script is `repro`.

```
uv run repro --version
uv run pytest
```
