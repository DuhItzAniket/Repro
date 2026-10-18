# K03 — Repro as an MCP server

| | |
|---|---|
| **Stage** | K — Expansion backlog |
| **Status** | done |
| **Depends on** | — |
| **Branch / PR** | `phase/K03-mcp` · [#90](https://github.com/DuhItzAniket/Repro/pull/90) |
| **Started / finished** | 2026-10-18 / 2026-10-18 |

## Objective
Agents can request verification and receive evidence, while the verifier stays independent
(roadmap).

## Scope
- **`repro mcp`**: an MCP server on stdio, built on the official Python SDK.
  - The SDK is `mcp` 2.3.0, MIT, `MCPServer`. It is now declared directly
    (`mcp>=2.3.0,<3`); Repro already shipped it as a dependency of the Claude Agent SDK.
  - The SDK handles the protocol's revisions. The current one (2026-07-28) carries the
    version in every request's `_meta`; earlier ones use an `initialize` handshake
    [modelcontextprotocol.io, "Versioning and Compatibility", checked 2026-10-18].
- **Six tools**:
  - one that starts a run: `start_verification` (a repository, two commits, the claim);
  - five that only read and are annotated so: status, card (Markdown or JSON), the evidence
    list, one evidence item, the recent runs.
- **Independence**: the agent names commits, and Repro reads them from git objects and runs
  them in its sandbox. A run is `repro run --no-serve` in its own process, with the engine's
  settings. The agent cannot write to the store.
- **`repro run --no-serve` prints `repro: <run id> started`** when the run begins, so a caller
  can follow it. The server uses that line.
- **The user guide**: `docs/guide/mcp.md`.

## Acceptance criteria
- [x] AC1: an agent starts a verification and reads its card and evidence through MCP.
- [x] AC2: the agent cannot provide results or change them: commits only, read-only tools.
- [x] AC3: unknown runs, a store with nothing yet, and a path that is not a repository are
  answered in words, not errors.

## Test plan
| Criterion | Check |
|---|---|
| AC1 | `test_mcp_server.py`, through the SDK's `Client`, in-process: a real `repro run` started by the tool on a tiny repository, polled to its end, then its card (both forms) and evidence read |
| AC2 | The six tools, and that exactly one is not read-only by its annotations |
| AC3 | An unknown run, an engine with no database, a path that is not a repository |

---
*Filled in at the end of the phase:*

## What shipped
- `repro.integrations.mcp_server` (`Verifier`, `server`), `repro mcp`, the start line.
- `docs/guide/mcp.md`.
- Tests: `test_mcp_server.py` (3).

## Evidence
- Through the SDK's own client: a verification started by the tool ran `repro run` on a tiny
  repository (process sandbox, analyse only, as a test) and ended with a card. Its status, its
  card as Markdown and as JSON, and its evidence were read back through the tools.
- `test_run_command.py`, `test_github_action.py` and `test_cli.py` (32) pass with the new
  start line.
- **A race, found by CI on Windows**: `repro run` names its run before the first commit to
  the store, so a `verification_status` call right after `start_verification` could answer
  `no such run`. `start_verification` now answers only once the run is stored, and the
  test checks the status at once.
- CI run: linked in the PR (#90).

## Deviations from spec
None.

## Known gaps
- stdio only. Streamable HTTP would need its own authentication, as the cockpit's API has.
- A run started through MCP cannot be stopped through it; it ends as any run does.

## Dependencies added
`mcp>=2.3.0,<3`, declared directly. It was already installed with the Claude Agent SDK, so
the lockfile adds no package.
